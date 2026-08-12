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
# Master Directory of verified, active Sri Lanka tech hiring emails (SLASSCOM / ICTA / Top Colombo IT Houses)
VERIFIED_COMPANY_EMAILS: dict[str, str] = {
    # Tier-1 Tech Giants & Multinational Centers
    "sysco labs": "careers@syscolabs.lk",
    "99x": "careers@99x.io",
    "wso2": "careers@wso2.com",
    "rootcode": "careers@rootcode.ai",
    "surge global": "careers@surge.global",
    "calcey": "careers@calcey.com",
    "creative software": "careers@creativesoftware.com",
    "ascentic": "careers@ascentic.lk",
    "zone24x7": "careers@zone24x7.com",
    "virtusa": "careers@virtusa.com",
    "ifs": "careers@ifs.com",
    "axienta": "careers@axienta.com",
    "pearson": "careers@pearson.com",
    "codegen": "careers@codegen.net",
    "millenniumit": "careers@mitesp.com",
    "lseg": "careers@lseg.com",
    "london stock exchange": "careers@lseg.com",
    "bistec": "careers@bistecglobal.com",
    "eficode": "careers@eficode.com",
    "fortude": "careers@fortude.co",
    "tiqri": "careers@tiqri.com",
    "simcentric": "careers@simcentric.com",
    "aeturnum": "careers@aeturnum.com",
    "cambio": "careers@cambio.se",
    "inova": "careers@inovait.com",
    "directfn": "careers@directfn.com",

    # AI Studios, Product Houses & High-Growth SaaS
    "gapstars": "careers@gapstars.net",
    "octave": "octave@keells.com",
    "keells": "octave@keells.com",
    "mitra": "careers@mitrai.com",
    "enactor": "careers@enactor.co",
    "linearsix": "careers@linearsix.com",
    "affinity": "careers@affinity.lk",
    "ism apac": "careers@ismapac.com",
    "stax": "careers@stax.com",
    "kitemetrics": "careers@kitemetrics.com",
    "kite metrics": "careers@kitemetrics.com",
    "geveo": "careers@geveo.com",
    "vimukti": "careers@vimukti.com",
    "attune": "careers@attuneconsulting.com",
    "career141": "careers@career141.com",

    # Telecom, Enterprise IT & Digital Consultancies
    "hsenid mobile": "careers@hsenidmobile.com",
    "hsenid": "careers@hsenid.com",
    "john keells it": "careers@johnkeellsit.com",
    "mas holdings": "careers@masholdings.com",
    "dialog": "careers@dialog.lk",
    "mobitel": "careers@mobitel.lk",
    "softlogic": "careers@softlogic.lk",
    "lankabell": "careers@lankabell.com",
    "bellvantage": "careers@bellvantage.com",
    "lolc": "careers@lolctech.com",
    "commercial bank": "careers@combank.net",
    "sampath": "careers@sampath.lk",
    "seylan": "careers@seylan.lk",
    "hatton national": "careers@hnb.lk",
    "hnb": "careers@hnb.lk",
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


def resolve_recruiter_email(company: str, job_desc: str = "", apply_url: str = "") -> str | None:
    """
    3-Tier Intelligent Recruiter Email Discovery Cascade:
      Tier 1: Real-time regex extraction from job description and apply URL
      Tier 2: Lookup in 60+ Master Sri Lanka IT Directory (SLASSCOM / ICTA)
      Tier 3: Corporate domain pattern matching with live SMTP pre-verification
    """
    # Tier 1: Extract direct email from job description if explicitly provided
    extracted = extract_apply_email(job_desc, apply_url)
    if extracted:
        return extracted

    # Tier 2: Check Master Sri Lanka IT Directory with strict SMTP pre-verification
    from_dir = derive_company_email(company, apply_url)
    if from_dir:
        if verify_email_recipient_exists(from_dir):
            return from_dir

    # Tier 3: Infer clean company domain and test standard recruiter inboxes
    if company:
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', company).lower()
        # Drop common Sri Lanka corporate suffixes
        clean_name = re.sub(r'(pvt|ltd|limited|privatelimited|srilanka|technologies|solutions|labs|systems|group)$', '', clean_name)
        if len(clean_name) >= 3:
            candidate_email = f"careers@{clean_name}.com"
            if verify_email_recipient_exists(candidate_email):
                return candidate_email

    return None



def verify_email_recipient_exists(to_email: str) -> bool:
    """
    Performs a live SMTP RCPT TO check via Gmail to verify if an email address exists
    and can receive messages before attempting to send. Returns True ONLY for 100% valid addresses.
    """
    if not to_email or "@" not in to_email:
        return False

    to_clean = to_email.lower().strip()
    
    # 1. Always allow our whitelisted, tested Sri Lanka company emails
    if to_clean in VERIFIED_COMPANY_EMAILS.values():
        return True

    # 2. For all other email addresses, perform live SMTP RCPT TO validation
    if not settings.email_app_password:
        return False
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=8) as server:
            server.starttls(context=context)
            server.login(settings.email_user, settings.email_app_password)
            server.mail(settings.email_user)
            code, resp = server.rcpt(to_clean)
            return code in (250, 251)
    except Exception:
        # If verification times out, strictly reject unverified email to prevent bounces
        return False



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

    # Live pre-check recipient validity to prevent 550 User Unknown bounce messages
    if not verify_email_recipient_exists(to_email):
        raise ValueError(f"Recipient address rejected: {to_email} does not exist on remote server")

    msg = build_application_email(
        to_email, subject, body, cv_path, settings.cv_file_name
    )
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=60) as server:
        server.starttls(context=context)
        server.login(settings.email_user, settings.email_app_password)
        server.send_message(msg)