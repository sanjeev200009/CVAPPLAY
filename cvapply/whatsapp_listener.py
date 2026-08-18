"""
WhatsApp Job Vacancy Ingestion Engine for CV Apply.
Parses job postings forwarded from Sri Lanka IT & Tech WhatsApp groups,
extracts recruiter contact emails & titles, and immediately dispatches application CVs.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from cvapply.apply_email import verify_email_recipient_exists
from cvapply.config import settings
from cvapply.convex_api import ConvexClient
from cvapply.apply_email import send_application_email
from cvapply.telegram import TelegramClient


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_URL_RE = re.compile(r"https?://[^\s<'\"]+")


def _slug_id(key: str) -> str:
    return hashlib.md5(f"whatsapp:{key}".encode()).hexdigest()[:20]


def extract_whatsapp_job(text: str) -> dict[str, Any]:
    """
    Parses a raw WhatsApp message text to extract job vacancy details.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Extract email addresses
    emails = _EMAIL_RE.findall(text)
    clean_emails = [
        e.lower()
        for e in emails
        if not any(x in e.lower() for x in ("example.com", "whatsapp.com", "noreply"))
    ]
    recruiter_email = clean_emails[0] if clean_emails else None

    # Extract application URLs
    urls = _URL_RE.findall(text)
    apply_url = urls[0] if urls else (f"mailto:{recruiter_email}" if recruiter_email else "")

    # Extract Job Title & Company from text headers
    company = "Sri Lanka IT Employer (WhatsApp)"
    title = "Software Engineer / IT Vacancy"

    for line in lines[:8]:
        line_clean = re.sub(r"[^\w\s\-\.\:\(\)]", "", line).strip()
        if re.search(r"\b(company|employer|hiring at|firm|organization)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE):
            m = re.search(r"\b(company|employer|hiring at|firm|organization)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE)
            if m:
                company = m.group(2).strip()
        elif re.search(r"\b(position|role|vacancy|job title|hiring for)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE):
            m = re.search(r"\b(position|role|vacancy|job title|hiring for)\s*[:\-]\s*([^\n]+)", line, re.IGNORECASE)
            if m:
                title = m.group(2).strip()
        elif re.search(r"\b(engineer|developer|trainee|intern|associate|qa|devops|network|support)\b", line, re.IGNORECASE):
            if len(line_clean) < 80 and not title or title == "Software Engineer / IT Vacancy":
                title = line_clean

    return {
        "company": company[:100],
        "title": title[:120],
        "description": text[:5000],
        "recruiter_email": recruiter_email,
        "apply_url": apply_target if (apply_target := (f"mailto:{recruiter_email}" if recruiter_email else apply_url)) else apply_url,
    }


def ingest_whatsapp_job(text: str, submit: bool = True) -> dict[str, Any]:
    """
    Ingests a WhatsApp group vacancy into Convex Cloud DB, scores it,
    and automatically emails the candidate CV if a recruiter email is found.
    """
    if not text or len(text.strip()) < 10:
        return {"status": "error", "message": "WhatsApp text too short"}

    extracted = extract_whatsapp_job(text)
    company = extracted["company"]
    title = extracted["title"]
    email = extracted["recruiter_email"]
    apply_url = extracted["apply_url"]
    description = extracted["description"]

    external_id = _slug_id(text[:100])
    convex = ConvexClient()
    telegram = TelegramClient()

    # Score job with NVIDIA LLM
    from cvapply.cv import load_cv
    from cvapply.llm import OpenRouterClient
    from cvapply.sources.base import Job
    from cvapply.store import upsert_job

    job_obj = Job(
        source="whatsapp",
        external_id=external_id,
        company=company,
        title=title,
        location="Colombo, Sri Lanka",
        remote=False,
        description=description,
        apply_url=apply_url,
    )

    cv_text = load_cv()
    llm = OpenRouterClient()
    score_result = llm.score_job(title, description, cv_text)
    match_score = float(score_result.get("score", 85.0))
    summary = score_result.get("summary", f"{title} at {company}")

    upsert_job(convex, job_obj, status="scored", tier="sri_lanka")
    job_id = external_id

    applied = False
    error_msg = None

    if email and verify_email_recipient_exists(email):
        try:
            email_res = llm.generate_email_application(
                company=company,
                job_title=title,
                job_desc=description,
                cv_text=cv_text,
                match_reason=score_result.get("reason", "Strong fit for early-career tech role"),
            )
            subject = email_res["subject"]
            letter = email_res["body"]
            send_application_email(email, subject, letter, settings.cv_file_path)
            from cvapply.apply import _log_application
            _log_application(
                convex,
                job_id,
                letter,
                "success",
                None,
                {"channel": "email", "recruiter_email": email, "subject": subject},
            )

            msg = (
                f"📱 **WHATSAPP JOB AUTO-APPLIED!**\n\n"
                f"🏢 **Company**: {company}\n"
                f"💼 **Role**: {title}\n"
                f"📧 **Recruiter Email**: {email}\n"
                f"🎯 **Fit Score**: {match_score}/100\n\n"
                f"📝 **Summary**: {summary}\n\n"
                f"✅ **Application CV Dispatched via Gmail SMTP!**"
            )
            telegram.send_message(msg)
            applied = True
        except Exception as exc:
            error_msg = str(exc)
            msg = (
                f"📱 **WHATSAPP JOB INGESTED (Email Failed)**\n\n"
                f"🏢 **Company**: {company}\n"
                f"💼 **Role**: {title}\n"
                f"📧 **Email**: {email}\n"
                f"⚠️ Error: {error_msg}"
            )
            telegram.send_message(msg)
    else:
        msg = (
            f"📱 **WHATSAPP JOB INGESTED (Portal Apply)**\n\n"
            f"🏢 **Company**: {company}\n"
            f"💼 **Role**: {title}\n"
            f"🎯 **Fit Score**: {match_score}/100\n"
            f"🔗 **Link**: {apply_url}\n\n"
            f"ℹ️ Added to Dashboard & Telegram for 1-click Portal Apply."
        )
        telegram.send_message(msg)

    return {
        "status": "success",
        "job_id": job_id,
        "company": company,
        "title": title,
        "match_score": match_score,
        "email": email,
        "applied": applied,
        "error": error_msg,
    }
