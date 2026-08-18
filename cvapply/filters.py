from __future__ import annotations

import re

from .config import settings
from .sources.base import Job

TITLE_BLOCK_RE = re.compile(
    r"\b(senior|sr\.|sr\b|lead|leader|staff|principal|manager|head of|director|vice president|vp|architect|expert|intermediate|mid-level|mid level)\b",
    re.IGNORECASE,
)

# Junk / non-tech / sales / marketing listings to exclude
BAD_TITLE_RE = re.compile(
    r"\b(beekeeper|handyman|electrician|plumber|carpenter|welder|machinist|janitor|"
    r"cleaner|housekeeper|maid|driver|delivery|warehouse|laborer|labourer|barista|"
    r"cashier|receptionist|security guard|security officer|landscaper|painter|roofer|"
    r"mechanic|technician|maintenance|janitorial|sales|account executive|business development|"
    r"call center|gig|hustle|freelance|interdisciplinary|expression of interest|"
    r"academy of achievement|beekeeper|service professional|detail specialist|"
    r"psychic|tarot|back office|administrator|paralegal|counsel|recruiter|talent community|"
    r"talent pool|copywriter|content writer|marketing|seo|growth marketing|customer support specialist|"
    r"jobs|hiring|work from home|remote opportunity)\b",
    re.IGNORECASE,
)

# Target software, networking, IT support, systems, and tech roles
TECH_TITLE_RE = re.compile(
    r"\b(software|developer|engineer|frontend|front-end|backend|back-end|fullstack|full-stack|"
    r"web|python|react|javascript|typescript|ai|ml|data|node|api|qa|sqa|test|tester|intern|internship|"
    r"graduate|associate|trainee|support|it support|network|networking|sysadmin|systems|system|administrator|"
    r"helpdesk|technician|infrastructure|cyber|security|cloud|devops|linux|database|dba|technical|it|ict)\b",
    re.IGNORECASE,
)


EXPERIENCE_RE = re.compile(
    r"(?P<years>\d{1,2})\s*(?:\+|to|-|–|—)?\s*(?:to\s+)?\d{0,2}\s*"
    r"(?:years?|yrs?|yr)\b(?:\s*(?:of)?\s*(?:experience|exp))?",
    re.IGNORECASE,
)

SALARY_RE = re.compile(
    r"((?:[\$€£]|USD|EUR|GBP)\s*\d{1,3}(?:,\d{3})*(?:k)?\s*(?:-|to|–|—)\s*(?:[\$€£]|USD|EUR|GBP)?\s*\d{1,3}(?:,\d{3})*(?:k)?(?:\s*(?:USD|EUR|GBP))?(?:\s*(?:\/|per|a)\s*(?:year|yr|month|mo|hr|hour|annum))?|"
    r"(?:[\$€£]|USD|EUR|GBP)\s*\d{1,3}(?:,\d{3})*(?:k)?(?:\s*(?:USD|EUR|GBP))?\s*(?:\/|per|a)\s*(?:year|yr|month|mo|hr|hour|annum))",
    re.IGNORECASE,
)


KEEP_TIERS: set[str] = {"sri_lanka", "worldwide"}


def title_blocked(title: str) -> bool:
    return bool(TITLE_BLOCK_RE.search(title))


def extract_salary(text: str) -> str:
    match = SALARY_RE.search(text)
    if match:
        return match.group(0).strip()
    return "Not specified"


def required_experience_years(text: str) -> int | None:
    for match in EXPERIENCE_RE.finditer(text):
        try:
            years = int(match.group("years"))
            if years >= 2:
                return years
        except (ValueError, IndexError):
            continue
    return None



def location_tier(location: str, remote: bool) -> str:
    """Classify a job's location into one of:
    sri_lanka | worldwide | restricted_remote | onsite
    """
    loc = str(location or "").lower()
    if "sri lanka" in loc or "colombo" in loc:
        return "sri_lanka"
    if any(w in loc for w in ("anywhere", "worldwide", "global", "everywhere")):
        return "worldwide"
    # Locations listing continents/regions that include Asia (e.g.
    # "Americas, Europe, Asia, Africa, Oceania", "South Asia") are open to
    # Sri Lanka unless explicitly restricted.
    if "asia" in loc and "only" not in loc and "residents" not in loc:
        return "worldwide"
    if remote:
        # Any leftover token after removing "remote"/punctuation means the role
        # is restricted to a specific country/region (e.g. "Remote, Italy",
        # "Remote (USA)", "Remote - Poland") -> not open to Sri Lanka.
        leftover = (
            loc.replace("remote", "")
            .replace(" ", "")
            .strip(",-–—()/;:.")
        )
        if not leftover:
            return "worldwide"
        return "restricted_remote"
    return "onsite"


def filter_job(job: Job) -> tuple[bool, str | None, str]:
    """Returns (keep, reason_if_rejected, location_tier)."""
    tier = location_tier(job.location, job.remote)
    allowed_tiers = {"sri_lanka"} if settings.only_sri_lanka else KEEP_TIERS
    if tier not in allowed_tiers:
        return False, tier, tier
    if title_blocked(job.title):
        return False, "title_blocked", tier
    if BAD_TITLE_RE.search(job.title):
        return False, "title_junk", tier
    if not TECH_TITLE_RE.search(job.title):
        return False, "non_tech_role", tier
    text = f"{job.title}\n{job.description}"
    years = required_experience_years(text)
    if years is not None and years > settings.max_experience_years:
        return False, f"experience_requirement>{settings.max_experience_years}y", tier
    return True, None, tier