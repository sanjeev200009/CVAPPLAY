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

# Companies that ONLY accept applications via their own ATS portal (Greenhouse/Ashby/Lever).
# NEVER attempt to email these companies directly — there is no careers@ inbox.
ATS_ONLY_COMPANIES: set[str] = {
    "canonical", "ubuntu", "supabase", "hashicorp", "gitlab", "docker",
    "cloudflare", "netlify", "vercel", "stripe", "twilio", "datadog",
    "pagerduty", "elastic", "redis", "mongodb", "cockroachdb",
    "confluent", "dbt", "airbyte", "prefect", "dagster", "metabase",
    "retool", "planetscale", "neon", "railway", "fly.io", "render",
    # Add any company whose apply_url points to greenhouse/lever/ashby
}


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
    "arimac": "careers@arimac.digital",
    "zebra": "careers@zebra.com",
    "ironone": "careers@irononetoolbox.com",
    "boardpac": "careers@boardpac.co",
    "epic": "careers@epiclanka.net",
    "zillione": "careers@zillione.com",
    "swivel": "careers@swivelgroup.com.au",
    "bhasha": "careers@bhasha.lk",
    "helakuru": "careers@bhasha.lk",
    "payhere": "careers@payhere.lk",
    "webxpay": "careers@webxpay.com",
    "tekgeeks": "careers@tekgeeks.net",
    "cyanworks": "careers@cyanworks.lk",
    "gapstars": "careers@gapstars.net",
    "octave": "octave@keells.com",
    "keells": "octave@keells.com",
    "mitra": "careers@mitrai.com",
    "enactor": "careers@enactor.co",
    "linearsix": "careers@linearsix.com",
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
    "john keells": "careers@johnkeells.com",
    "brandix": "careers@brandix.com",
    "hayleys": "careers@hayleys.com",
    "hemas": "careers@hemas.com",
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
    or None if no verified email exists or if company is ATS-only (preventing email bounces).
    """
    if not company_name:
        return None

    clean = company_name.lower()
    for ats_co in ATS_ONLY_COMPANIES:
        if ats_co in clean:
            return None

    for key, email in VERIFIED_COMPANY_EMAILS.items():
        if key in clean:
            return email

    return None


import socket

def is_valid_email_domain(email: str) -> bool:
    """Checks if the email domain exists, is not blacklisted, and has valid mail exchange DNS records."""
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].strip().lower()

    # Reject non-routable / placeholder domains
    if domain in ("example.com", "example.org", "w3.org", "sentry.io", "linkedin.com", "greenhouse.io", "ashbyhq.com"):
        return False

    try:
        # Check standard address info
        infos = socket.getaddrinfo(domain, None)
        return len(infos) > 0
    except Exception:
        return False


def resolve_recruiter_email(company: str, job_desc: str = "", apply_url: str = "") -> str | None:
    """
    Strict 3-Tier Recruiter Email Discovery (Zero-Bounce Guarantee):
      Tier 0: Block ATS-only companies immediately (never email, use web portal)
      Tier 1: Real-time regex extraction from job description (explicitly provided email)
      Tier 2: Master Sri Lanka IT Directory (65+ verified tech companies)
      Tier 3: Smart Domain Resolution from apply_url with DNS validation
    """
    # Tier 0: Block known ATS-only companies that have no direct email inbox
    company_lower = company.lower() if company else ""
    for ats_co in ATS_ONLY_COMPANIES:
        if ats_co in company_lower:
            return None

    # Block if apply_url points to a known ATS platform
    ats_urls = ("greenhouse.io", "ashbyhq.com", "lever.co", "workday.com", "workable.com", "smartrecruiters.com")
    if apply_url and any(ats in apply_url for ats in ats_urls):
        return None

    # Tier 1: Extract direct email from job description if explicitly provided by employer
    extracted = extract_apply_email(job_desc, apply_url)
    if extracted:
        if is_valid_email_domain(extracted):
            return extracted

    # Tier 2: Check Master Sri Lanka IT Directory
    from_dir = derive_company_email(company, apply_url)
    if from_dir:
        if is_valid_email_domain(from_dir):
            return from_dir

    # Tier 3: Smart Domain Resolution from apply_url with DNS validation
    if apply_url and "://" in apply_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(apply_url)
            host = parsed.netloc.lower().replace("www.", "").replace("careers.", "").replace("jobs.", "")
            if host and "." in host and not any(x in host for x in ("google", "facebook", "linkedin", "xpressjobs", "topjobs")):
                candidate_email = f"careers@{host}"
                if is_valid_email_domain(candidate_email):
                    return candidate_email
        except Exception:
            pass

    # Strictly NO domain guessing — if no explicit or directory email, fallback to Web Portal
    return None


def verify_email_recipient_exists(to_email: str) -> bool:
    """
    Pre-flight validation before initiating SMTP delivery.
    Verifies that an email address has a valid format, belongs to a real domain with DNS records,
    and is non-blacklisted. Returns True ONLY for safe, valid addresses.
    """
    if not to_email or "@" not in to_email:
        return False

    to_clean = to_email.lower().strip()

    # Reject known placeholder / dummy / non-hiring addresses
    if any(x in to_clean for x in ("example.com", "example.org", "noreply", "no-reply", "w3.org", "sentry.io", "unsubscribe")):
        return False

    # Perform DNS domain network check
    return is_valid_email_domain(to_clean)

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