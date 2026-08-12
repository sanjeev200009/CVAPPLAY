from __future__ import annotations

import email
from email.header import decode_header
import imaplib
import json
import os
import re
import time
from typing import Any

from .config import settings
from .telegram import TelegramClient

SEEN_IDS_FILE = os.path.join(os.path.dirname(__file__), "..", ".seen_reply_ids.json")

# Keywords that strongly indicate a human HR recruiter / hiring manager reply
RECRUITER_KEYWORDS = re.compile(
    r"\b(interview|shortlist|shortlisted|application|candidate|schedule|call|availability|"
    r"next step|hiring|cv|resume|position|role|opportunity|career|discussion|assessment|"
    r"screening|test|assignment|offer|joining|technical round)\b",
    re.IGNORECASE,
)

# Automated noise and auto-responder subjects to ignore
IGNORE_SENDERS = (
    "no-reply", "noreply", "mailer-daemon", "postmaster", "google.com", "github.com",
    "linkedin.com", "facebookmail.com", "accounts.google.com", "bounce",
    "security-noreply", "notifications", "support@github.com",
)

AUTO_REPLY_SUBJECTS = re.compile(
    r"\b(automatic reply|auto-reply|out of office|undeliverable|delivery status|failure notice)\b",
    re.IGNORECASE,
)


def _decode_str(header_val: Any) -> str:
    if not header_val:
        return ""
    if isinstance(header_val, bytes):
        return header_val.decode("utf-8", errors="replace")
    decoded = decode_header(str(header_val))
    parts = []
    for val, enc in decoded:
        if isinstance(val, bytes):
            parts.append(val.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(val))
    return "".join(parts)


def _load_seen_ids() -> set[str]:
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_seen_ids(seen: set[str]) -> None:
    try:
        # Keep last 2000 IDs to avoid file bloat
        lst = list(seen)[-2000:]
        with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(lst, f)
    except Exception:
        pass


class InboxTracker:
    def __init__(self) -> None:
        self.telegram = TelegramClient()
        self.seen_ids = _load_seen_ids()

    def check_new_replies(self) -> int:
        """
        Checks Gmail INBOX for new recruiter replies and pings Telegram instantly.
        Returns the number of new recruiter replies discovered.
        """
        if not settings.email_user or not settings.email_app_password:
            return 0

        replies_count = 0
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(settings.email_user, settings.email_app_password)
            mail.select("INBOX")

            # Search for UNSEEN messages
            status, data = mail.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                mail.logout()
                return 0

            msg_ids = data[0].split()
            # Inspect the most recent 20 unread emails
            for msg_id in msg_ids[-20:]:
                msg_id_str = msg_id.decode()
                if msg_id_str in self.seen_ids:
                    continue

                status, msg_data = mail.fetch(msg_id, "(RFC822.HEADER BODY[TEXT])")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                if isinstance(raw_email, tuple):
                    raw_email = raw_email[1]

                msg = email.message_from_bytes(raw_email)

                msg_unique_id = msg.get("Message-ID") or msg_id_str
                if msg_unique_id in self.seen_ids:
                    continue

                self.seen_ids.add(msg_unique_id)
                self.seen_ids.add(msg_id_str)

                sender = _decode_str(msg.get("From", ""))
                subject = _decode_str(msg.get("Subject", ""))
                date_str = _decode_str(msg.get("Date", ""))

                # Skip emails sent by ourselves, auto-responders, or known noise
                sender_lower = sender.lower()
                if settings.email_user.lower() in sender_lower:
                    continue
                if any(x in sender_lower for x in IGNORE_SENDERS):
                    continue
                if AUTO_REPLY_SUBJECTS.search(subject):
                    continue

                # Extract text body snippet
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disp = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disp:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode("utf-8", errors="replace")
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode("utf-8", errors="replace")

                clean_snippet = re.sub(r"\s+", " ", body_text).strip()[:350]
                combined_text = f"{subject} {clean_snippet}"

                # Check if this is a recruiter reply
                if RECRUITER_KEYWORDS.search(combined_text):
                    replies_count += 1
                    alert = (
                        f"📩 RECRUITER REPLY RECEIVED!\n\n"
                        f"👤 From: {sender}\n"
                        f"📌 Subject: {subject}\n"
                        f"📅 Date: {date_str}\n\n"
                        f"💬 Message Snippet:\n\"{clean_snippet}...\"\n\n"
                        f"👉 ACTION REQUIRED: Check your Gmail ({settings.email_user}) and reply to the hiring manager!"
                    )
                    self.telegram.send_message(alert)
                    print(f"  [inbox_tracker] Recruiter reply detected from {sender}: {subject}")

            _save_seen_ids(self.seen_ids)
            mail.logout()

        except Exception as exc:
            print(f"[inbox_tracker] Warning during check: {exc}")

        return replies_count


def check_inbox() -> int:
    tracker = InboxTracker()
    return tracker.check_new_replies()
