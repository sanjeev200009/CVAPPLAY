from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .config import settings

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z0-9.-]+")
APPLY_BY_EMAIL_HINTS = re.compile(
    r"(email (?:us|your|the|our|your (?:cv|resume|application))?(?: ?your)? ?(?:cv|resume|application)?\s*(?:to|at)?)|"
    r"(send (?:your )?(?:cv|resume|application|cover letter|details)\s*(?:to|via|by|at)?)|"
    r"(apply (?:via|by|through)? email)|"
    r"(mail (?:your )?(?:cv|resume))|"
    r"(reach out to)|"
    r"(contact (?:us at)?)|"
    r"(submit (?:your )?(?:cv|resume|application)\s*(?:to|at)?)|"
    r"(forward (?:your )?(?:cv|resume)\s*(?:to|at)?)",
    re.IGNORECASE,
)


def extract_apply_email(description: str, apply_url: str = "") -> str | None:
    """Finds a recruiter/application email address from the job description or mailto apply_url."""
    # 1. Check if apply_url is a mailto: link
    if apply_url and "mailto:" in apply_url.lower():
        match = EMAIL_RE.search(apply_url)
        if match:
            return match.group(0).lower()

    if not description:
        return None

    desc = description[:6000]
    seen: set[str] = set()

    # 2. Check for explicit hiring email prefixes first
    for match in EMAIL_RE.finditer(desc):
        email = match.group(0).lower().rstrip(".,;:")
        if email in seen:
            continue
        seen.add(email)

        # Ignore common non-hiring placeholder emails
        if any(x in email for x in ("example.com", "example.org", "noreply", "no-reply", "@linkedin.com", "@greenhouse.io", "@ashbyhq.com", "@lever.co", "sentry.io", "w3.org")):
            continue

        # If it's a dedicated hiring address, accept directly
        if any(email.startswith(prefix) for prefix in ("jobs@", "careers@", "hiring@", "recruitment@", "recruiting@", "talent@", "apply@", "hr@", "contact@", "info@")):
            return email

        # Or if in the proximity of apply hints
        start = max(0, match.start() - 300)
        window = desc[start : match.end() + 100]
        if APPLY_BY_EMAIL_HINTS.search(window):
            return email

    # 3. Fallback: return ANY valid non-blacklisted email found in description
    for match in EMAIL_RE.finditer(desc):
        email = match.group(0).lower().rstrip(".,;:")
        if not any(x in email for x in ("example.com", "example.org", "noreply", "no-reply", "@linkedin.com", "@greenhouse.io", "@ashbyhq.com", "@lever.co", "w3.org")):
            return email

    return None


# Dictionary of verified, active Sri Lanka tech hiring emails
VERIFIED_COMPANY_EMAILS: dict[str, str] = {
    "sysco labs": "careers@syscolabs.lk",
    "99x": "careers@99x.io",
    "wso2": "careers@wso2.com",
    "rootcode": "careers@rootcode.ai",
    "surge global": "careers@surge.global",
    "calcey": "careers@calcey.com",
    "creative software": "careers@creativesoftware.com",
    "ascentic": "careers@ascentic.lk",
    "zone24x7": "careers@zone24x7.com",
    "virtusa": "careers.lk@virtusa.com",
    "ifs": "careers.lk@ifs.com",
    "axienta": "careers@axienta.com",
    "pearson": "careers.lanka@pearson.com",
    "codegen": "careers@codegen.net",
    "millenniumit": "careers@mitesp.com",
    "lseg": "careers.lk@lseg.com",
    "bistec": "careers@bistecglobal.com",
    "eficode": "careers.lk@eficode.com",
    "fortude": "careers@fortude.co",
    "tiqri": "careers@tiqri.com",
    "simcentric": "careers@simcentric.com",
    "aeturnum": "careers@aeturnum.com",
    "cambio": "careers.lk@cambio.se",
    "inova": "careers@inovait.com",
    "directfn": "careers.lk@directfn.com",
}


def derive_company_email(company_name: str, apply_url: str = "") -> str | None:
    """
    Returns a verified hiring email address for known Sri Lanka IT companies,
    or None if no verified email exists (preventing email bounces).
    """
    if not company_name:
        return None

    clean = company_name.lower()
    for key, email in VERIFIED_COMPANY_EMAILS.items():
        if key in clean:
            return email

    return None





def build_application_email(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str,
    attachment_name: str,
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = formataddr((f"{settings.candidate_first_name} {settings.candidate_last_name}", settings.email_user))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as fh:
            part = MIMEApplication(fh.read(), _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=attachment_name)
            msg.attach(part)
    return msg


def send_application_email(
    to_email: str, subject: str, body: str, cv_path: str
) -> None:
    if not settings.email_app_password:
        raise RuntimeError("EMAIL_APP_PASSWORD not set - create a Gmail App Password first")
    msg = build_application_email(
        to_email, subject, body, cv_path, settings.cv_file_name
    )
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=60) as server:
        server.starttls(context=context)
        server.login(settings.email_user, settings.email_app_password)
        server.send_message(msg)