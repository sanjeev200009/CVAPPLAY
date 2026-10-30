"""
Telegram Instant Job Ingestion & Auto-Application Listener.
Listens for forwarded or pasted job descriptions sent to the candidate's Telegram bot,
automatically parses the JD, validates the recruiter email, generates a tailored cover letter,
attaches the PDF CV, and dispatches the application via Gmail SMTP.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from .apply import _log_application
from .apply_email import (
    BLOCKED_EMAIL_DOMAINS,
    BLOCKED_EMAILS,
    extract_apply_email,
    send_application_email,
    verify_email_recipient_exists,
)
from .config import settings
from .convex_api import ConvexClient
from .cv import load_cv
from .llm import OpenRouterClient
from .sources.base import Job
from .store import upsert_job_doc
from .telegram import TelegramClient

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z0-9.-]+")
_OFFSET_FILE = os.path.join(os.path.dirname(__file__), "..", ".telegram_offset.json")


def _slug_id(key: str) -> str:
    return hashlib.md5(f"telegram_ingest:{key}".encode()).hexdigest()[:20]


def _load_offset() -> int | None:
    if os.path.exists(_OFFSET_FILE):
        try:
            with open(_OFFSET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("offset")
        except Exception:
            pass
    return None


def _save_offset(offset: int) -> None:
    try:
        with open(_OFFSET_FILE, "w", encoding="utf-8") as f:
            json.dump({"offset": offset}, f)
    except Exception:
        pass


class TelegramListener:
    def __init__(self, submit: bool = True) -> None:
        self.telegram = TelegramClient()
        self.convex = ConvexClient()
        self.llm = OpenRouterClient()
        self.submit = submit
        self.offset = _load_offset()
        self._running = False

    def parse_job_from_text(self, text: str) -> dict[str, Any]:
        """
        Uses LLM with regex fallback to extract structured fields from JD text.
        """
        # Clean glued TLDs (e.g. 'user@gmail.comJob Title' -> 'user@gmail.com Job Title')
        cleaned_text = re.sub(
            r"(\.(?:com|lk|io|ai|net|org|co|tech|global|co\.uk|ac\.lk|se|me|app|gov|info|biz))([A-Za-z])",
            r"\1 \2",
            text or "",
            flags=re.IGNORECASE,
        )

        # 1. Direct regex email extraction first
        direct_email = extract_apply_email(cleaned_text)
        if not direct_email:
            for m in _EMAIL_RE.finditer(cleaned_text):
                em = m.group(0).lower().rstrip(".,;:")
                domain = em.split("@")[-1] if "@" in em else ""
                if domain not in BLOCKED_EMAIL_DOMAINS and em not in BLOCKED_EMAILS:
                    direct_email = em
                    break

        # 2. Regex fallback for company & title
        fallback_company = "Sri Lanka Employer"
        fallback_title = "Executive"
        for line in [l.strip() for l in cleaned_text.splitlines() if l.strip()][:10]:
            clean_l = re.sub(r"[^\w\s\-\.\:\(\)]", "", line).strip()
            if re.search(r"\b(company|employer|hiring at|firm|organization)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE):
                m = re.search(r"\b(company|employer|hiring at|firm|organization)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE)
                if m:
                    fallback_company = m.group(2).strip()
            elif re.search(r"\b(position|role|vacancy|job title|hiring for)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE):
                m = re.search(r"\b(position|role|vacancy|job title|hiring for)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE)
                if m:
                    fallback_title = m.group(2).strip()
            elif re.search(r"\b(software engineer|developer|intern|associate|qa|devops|fullstack|frontend|backend|executive|officer|manager|lead)\b", line, re.IGNORECASE):
                if len(clean_l) < 80:
                    fallback_title = clean_l

        # 3. LLM Structured Extraction
        system_prompt = "You are an expert HR data parser. Extract structured job details and return ONLY a strict JSON object with keys: company, title, email, location, key_skills."
        user_prompt = f"""Extract the structured details from this forwarded job posting / JD text:

JOB TEXT:
\"\"\"{cleaned_text[:4000]}\"\"\"

JSON keys:
- "company": string
- "title": string
- "email": string or null
- "location": string
- "key_skills": list of strings"""

        try:
            raw = self.llm.chat(
                model=settings.openrouter_fallback_model,
                system=system_prompt,
                user=user_prompt,
                max_tokens=400,
                json_mode=True,
            )
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean)
            if not data.get("email") and direct_email:
                data["email"] = direct_email
            if not data.get("company") or data.get("company") in ("Company Name", "null", "None"):
                data["company"] = fallback_company
            if not data.get("title") or data.get("title") in ("Job Title", "null", "None"):
                data["title"] = fallback_title
            return data
        except Exception as exc:
            print(f"  [telegram-ingest] LLM parse warning ({exc}), using regex extraction")
            return {
                "company": fallback_company,
                "title": fallback_title,
                "email": direct_email,
                "location": "Colombo, Sri Lanka",
                "key_skills": ["Operations", "Communication"],
            }

    def process_incoming_job(self, text: str, message_id: int) -> None:
        """
        Parses the text, generates a tailored application, sends the email, and confirms in Telegram.
        """
        # Clean glued TLDs
        cleaned_text = re.sub(
            r"(\.(?:com|lk|io|ai|net|org|co|tech|global|co\.uk|ac\.lk|se|me|app|gov|info|biz))([A-Za-z])",
            r"\1 \2",
            text or "",
            flags=re.IGNORECASE,
        )
        print(f"\n[telegram-ingest] Received new message ({len(cleaned_text)} chars)")
        self.telegram.reply_message("⏳ Reading JD & preparing tailored application...", message_id)

        parsed = self.parse_job_from_text(cleaned_text)
        company = parsed.get("company", "Company").strip()
        title = parsed.get("title", "Job Position").strip()
        email = (parsed.get("email") or "").strip().lower()

        if not email:
            msg = (
                f"⚠️ **Could not find a recruiter email in this post.**\n\n"
                f"🏢 Company: {company}\n"
                f"💼 Role: {title}\n\n"
                f"Please reply with the email address (e.g. `careers@example.com`) to send your application."
            )
            self.telegram.reply_message(msg, message_id)
            return

        if not verify_email_recipient_exists(email):
            msg = (
                f"❌ **Email address rejected: {email}**\n\n"
                f"This address is blacklisted, belongs to a job portal domain, or failed DNS checks.\n"
                f"Please provide a verified direct hiring email."
            )
            self.telegram.reply_message(msg, message_id)
            return

        cv_text = load_cv()
        print(f"  🧠 Generating custom cover letter for {company} — {title} -> {email}")
        try:
            email_result = self.llm.generate_email_application(
                company=company,
                job_title=title,
                job_desc=text,
                cv_text=cv_text,
                match_reason="Direct candidate referral via Telegram Ingest",
            )
            subject = email_result["subject"]
            body = email_result["body"]

            # Save job to Convex
            ext_id = _slug_id(f"{company}:{title}:{time.time()}")
            job_obj = Job(
                source="telegram_ingest",
                external_id=ext_id,
                company=company,
                title=title,
                location=parsed.get("location", "Colombo, Sri Lanka"),
                remote=False,
                description=text[:5000],
                apply_url=f"mailto:{email}",
            )
            doc_id = upsert_job_doc(self.convex, job_obj, status="applied", tier="sri_lanka")
            job_id = doc_id or ext_id

            if self.submit:
                send_application_email(email, subject, body, settings.cv_file_path)
                _log_application(
                    self.convex,
                    job_id,
                    body,
                    "success",
                    None,
                    {"channel": "telegram_ingest", "to": email, "subject": subject},
                )
                print(f"  ✅ Email dispatched to {email}")

                reply_msg = (
                    f"✅ **APPLICATION SENT TO RECRUITER!**\n\n"
                    f"🏢 **Company**: {company}\n"
                    f"💼 **Role**: {title}\n"
                    f"📧 **Sent To**: `{email}`\n"
                    f"📎 **Attached**: `{settings.cv_file_name}`\n"
                    f"📌 **Subject**: {subject}\n\n"
                    f"📝 **Cover Letter Preview**:\n"
                    f"_{body[:300]}..._\n\n"
                    f"🎯 Logged into your CV Apply Convex Dashboard."
                )
                self.telegram.reply_message(reply_msg, message_id)
            else:
                reply_msg = (
                    f"ℹ️ **DRY RUN (Application Not Sent)**\n\n"
                    f"🏢 Company: {company}\n"
                    f"💼 Role: {title}\n"
                    f"📧 Would send to: `{email}`\n"
                    f"📌 Subject: {subject}\n\n"
                    f"Body preview:\n_{body[:250]}..._"
                )
                self.telegram.reply_message(reply_msg, message_id)

        except Exception as exc:
            print(f"  ❌ Failed to process Telegram job: {exc}")
            err_msg = (
                f"❌ **Failed to send application**\n\n"
                f"🏢 Company: {company}\n"
                f"💼 Role: {title}\n"
                f"📧 Email: {email}\n"
                f"⚠️ Error: {str(exc)[:300]}"
            )
            self.telegram.reply_message(err_msg, message_id)

    def poll_once(self) -> int:
        """
        Polls for new updates from Telegram. Returns the number of messages processed.
        """
        updates = self.telegram.get_updates(offset=self.offset, timeout=5)
        if not updates:
            return 0

        processed = 0
        for update in updates:
            upd_id = update.get("update_id")
            if upd_id is not None:
                self.offset = upd_id + 1
                _save_offset(self.offset)

            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue

            # Security: Only process messages from candidate's authorized chat ID
            from_chat_id = str(msg.get("chat", {}).get("id", ""))
            if from_chat_id != str(settings.telegram_chat_id):
                print(f"[telegram-ingest] Ignored message from unauthorized chat_id: {from_chat_id}")
                continue

            text = msg.get("text") or msg.get("caption") or ""
            message_id = msg.get("message_id")
            if not text.strip() or not message_id:
                continue

            # Handle bot commands
            cmd = text.strip().lower()
            if cmd in ("/start", "/help"):
                welcome = (
                    "👋 **CV Apply Instant Bot Ready!**\n\n"
                    "Forward or paste any Job Description (JD) containing a recruiter email here.\n\n"
                    "The bot will automatically:\n"
                    "1. Parse the company & role.\n"
                    "2. Generate a custom tailored cover letter.\n"
                    "3. Attach your CV (`Sanjeev_CV.pdf`).\n"
                    "4. Send the email and reply here with confirmation!"
                )
                self.telegram.reply_message(welcome, message_id)
                processed += 1
                continue
            elif cmd == "/status":
                status_txt = f"🤖 **CV Apply Status**: Active\n• Mode: {'Submit Real Applications' if self.submit else 'Dry Run'}\n• Daily Cap: {settings.daily_app_cap}"
                self.telegram.reply_message(status_txt, message_id)
                processed += 1
                continue

            self.process_incoming_job(text, message_id)
            processed += 1

        return processed

    def listen_loop(self) -> None:
        """Runs continuous long polling loop."""
        self._running = True
        print("[telegram-listener] Started listening for incoming Telegram JDs...")
        backoff = 0
        last_err = ""
        while self._running:
            try:
                self.poll_once()
                if backoff:
                    print("[telegram-listener] recovered")
                backoff = 0
                time.sleep(1)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                # ponytail: exponential backoff + dedup so an offline spell logs a
                # handful of lines instead of thousands. Cap 5min.
                backoff = min(backoff * 2 or 5, 300)
                err = str(exc)[:200]
                if err != last_err:
                    print(f"[telegram-listener] poll error: {err} (retry in {backoff}s)")
                    last_err = err
                time.sleep(backoff)


def start_telegram_listener_thread(submit: bool = True) -> TelegramListener:
    """Spawns the Telegram listener in a background daemon thread."""
    import threading
    listener = TelegramListener(submit=submit)
    thread = threading.Thread(target=listener.listen_loop, daemon=True, name="TelegramListenerThread")
    thread.start()
    return listener
