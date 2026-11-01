"""
Job validation layer.
Detects scam listings, stale jobs, misleading descriptions, and ATS redirect duplicates
before they are inserted into the database or sent to scoring.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from .sources.base import Job

# ── Scam / spam signal patterns ──────────────────────────────────────────────
_SCAM_DESC_RE = re.compile(
    r"\b("
    r"earn from home|earn money from home|"
    r"no experience needed.{0,20}high pay|high pay.{0,20}no experience|"
    r"commission.?only|100%\s*commission|"
    r"multi.?level|mlm|network marketing|pyramid|referral bonus scheme|"
    r"make \$\d{3,} (per day|daily)|"
    r"work from (anywhere|home).{0,20}unlimited (income|earning)|"
    r"be your own boss.{0,40}(income|earn)|"
    r"no (degree|qualification) (needed|required).{0,20}(\$\d|high salary)|"
    r"data entry.{0,30}earn|"
    r"urgent hiring.{0,30}no experience|"
    r"part.?time.{0,20}\$\d{3,}|"
    r"investment (opportunity|scheme)|"
    r"crypto (trading|investment) (job|opportunity)|"
    r"forex (trading|job)|"
    r"quick (cash|money)|"
    r"easy (money|cash|income)|"
    r"work (just )?\d+ hours.{0,20}earn"
    r")\b",
    re.IGNORECASE,
)

_SCAM_COMPANY_RE = re.compile(
    r"\b("
    r"hiring now|careers now|jobs now|"
    r"global (recruitment|staffing|opportunity)|"
    r"work from home opportunity|"
    r"remote opportunity llc|"
    r"virtual staffing|"
    r"dream job recruiter"
    r")\b",
    re.IGNORECASE,
)

# Suspicious URL patterns (URL shorteners, WhatsApp, Telegram application links)
_SUSPICIOUS_URL_RE = re.compile(
    r"(bit\.ly|tinyurl\.com|goo\.gl|t\.co|ow\.ly|is\.gd|buff\.ly|"
    r"wa\.me|whatsapp\.com/|t\.me/|telegram\.me/|"
    r"forms\.gle|docs\.google\.com/forms)",
    re.IGNORECASE,
)

# Known legitimate ATS platforms — these are fine in apply_url
_LEGIT_ATS_DOMAINS = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workday.com",
    "smartrecruiters.com", "workable.com", "bamboohr.com", "icims.com",
    "taleo.net", "successfactors.com", "jobvite.com", "recruitee.com",
    "breezy.hr", "pinpointhq.com", "dover.com", "rippling.com",
    "xpress.jobs", "topjobs.lk", "itpro.lk", "devjobs.lk",
    "linkedin.com", "indeed.com", "glassdoor.com", "wellfound.com",
    "himalayas.app", "remotive.com", "weworkremotely.com", "jobicy.com",
    "arbeitnow.com", "landingjobs.co", "fourdayweek.io",
    "getonbrd.com", "workatastartup.com", "startup.jobs", "pyjobs.com",
    "jobgether.com", "nodesk.co", "jobstreet.lk",
}

# How old a job can be (in days) before it's considered stale
_MAX_AGE_DAYS = 90
_MAX_AGE_MS = _MAX_AGE_DAYS * 24 * 3600 * 1000


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def validate_job(job: Job) -> tuple[bool, str]:
    """
    Returns (is_valid, reason).
    is_valid=True means the job passed all checks and should proceed.
    is_valid=False means the job should be dropped with the given reason.
    """
    title = job.title or ""
    company = job.company or ""
    desc = job.description or ""
    apply_url = job.apply_url or ""
    posted_at = job.posted_at

    # ── 1. Stale listing check ─────────────────────────────────────────────
    if posted_at is not None:
        now_ms = int(time.time() * 1000)
        age_ms = now_ms - posted_at
        if age_ms > _MAX_AGE_MS:
            age_days = age_ms // (24 * 3600 * 1000)
            return False, f"stale_listing ({age_days} days old)"

    # ── 2. Scam signals in description ────────────────────────────────────
    if _SCAM_DESC_RE.search(desc):
        matched = _SCAM_DESC_RE.search(desc)
        snippet = matched.group(0)[:60] if matched else ""
        return False, f"scam_signal_desc: {snippet}"

    # ── 3. Scam signals in company name ───────────────────────────────────
    if _SCAM_COMPANY_RE.search(company):
        return False, f"scam_signal_company: {company[:60]}"

    # ── 4. Suspicious apply_url (URL shorteners, WhatsApp, Telegram) ──────
    if apply_url and _SUSPICIOUS_URL_RE.search(apply_url):
        matched = _SUSPICIOUS_URL_RE.search(apply_url)
        snippet = matched.group(0) if matched else apply_url[:60]
        return False, f"suspicious_url: {snippet}"

    # ── 5. Empty/invalid apply URL (must have something to apply to) ───────
    if not apply_url or apply_url.strip() in ("", "#", "javascript:void(0)"):
        return False, "missing_apply_url"

    # ── 6. Apply URL redirects to unrelated non-job website ───────────────
    domain = _domain_of(apply_url)
    if domain and not any(legit in domain for legit in _LEGIT_ATS_DOMAINS):
        # If it's not mailto: and not a known job domain, check for obviously unrelated domains
        if not apply_url.startswith("mailto:") and not apply_url.startswith("http"):
            return False, f"invalid_apply_url_scheme: {apply_url[:80]}"

    # ── 7. Company name is suspiciously generic (all-caps junk) ───────────
    if re.match(r'^[A-Z\s\d]{10,}$', company.strip()) and len(company) > 10:
        return False, f"suspicious_company_name: {company[:60]}"

    # ── 8. Description is too short to be a real job posting ──────────────
    if len(desc.strip()) < 40:
        return False, "description_too_short"

    # ── 9. Title is suspiciously generic or a spam title ──────────────────
    spam_title_patterns = [
        r"^(work from home|remote opportunity|hiring now|urgent vacancy|"
        r"earn money|data entry|online job|part time|freelancer needed)$",
    ]
    title_lower = title.lower().strip()
    for pat in spam_title_patterns:
        if re.match(pat, title_lower, re.IGNORECASE):
            return False, f"spam_title: {title[:60]}"

    return True, ""
