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
}

# Job aggregators, job boards, and ATS platforms — NEVER send direct emails to these domains
BLOCKED_EMAIL_DOMAINS: set[str] = {
    # Sri Lankan job boards & aggregators
    "itpro.lk", "topjobs.lk", "xpress.jobs", "devjobs.lk", "dreamjobs.lk",
    "jobseeker.lk", "itjobs.lk", "ikman.lk", "jobstreet.lk", "jobstreet.com",
    "careers.lk", "jobsinlanka.com", "sljobportal.lk", "rozee.pk",
    # Global job boards & platforms
    "linkedin.com", "indeed.com", "glassdoor.com", "wellfound.com",
    "himalayas.app", "remotive.com", "weworkremotely.com", "jobicy.com",
    "arbeitnow.com", "landingjobs.co", "fourdayweek.io", "getonbrd.com",
    "workatastartup.com", "startup.jobs", "pyjobs.com", "jobgether.com",
    "nodesk.co", "naukri.com", "hirist.com", "monster.com", "dice.com",
    "careerbuilder.com", "ziprecruiter.com", "simplyhired.com",
    # ATS and tracking systems (must use web portal / handler, not direct email)
    "greenhouse.io", "ashbyhq.com", "lever.co", "workday.com",
    "smartrecruiters.com", "workable.com", "bamboohr.com", "icims.com",
    "recruitee.com", "breezy.hr", "pinpointhq.com", "dover.com", "rippling.com",
    "myworkdayjobs.com", "taleo.net", "successfactors.com", "jobvite.com",
    # Placeholders & non-routable domains
    "example.com", "example.org", "w3.org", "sentry.io", "google.com", "facebook.com",
}

# Individual email addresses known to bounce (550 No Such User) or block external applications
BLOCKED_EMAILS: set[str] = {
    "careers@ebeyonds.com",  # Blocked by Microsoft 365 Exchange tenant policy (EXOSmtpErrors)
    "careers@itpro.lk",      # 550 No Such User Here (job board, not employer)
    "info@itpro.lk",
    "contact@itpro.lk",
}


def extract_apply_email(description: str, apply_url: str = "") -> str | None:
    """Finds a recruiter/application email address from the job description or mailto apply_url."""
    # 1. Check if apply_url is a mailto: link
    if apply_url and "mailto:" in apply_url.lower():
        match = EMAIL_RE.search(apply_url)
        if match:
            email = match.group(0).lower().rstrip(".,;:")
            domain = email.split("@")[-1] if "@" in email else ""
            if domain not in BLOCKED_EMAIL_DOMAINS and email not in BLOCKED_EMAILS:
                return email

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

        domain = email.split("@")[-1] if "@" in email else ""
        if domain in BLOCKED_EMAIL_DOMAINS or email in BLOCKED_EMAILS:
            continue

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
        domain = email.split("@")[-1] if "@" in email else ""
        if domain in BLOCKED_EMAIL_DOMAINS or email in BLOCKED_EMAILS:
            continue
        if not any(x in email for x in ("example.com", "example.org", "noreply", "no-reply", "@linkedin.com", "@greenhouse.io", "@ashbyhq.com", "@lever.co", "w3.org")):
            return email

    return None


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
    "orel it": "careers@orelit.com",
    "orelit": "careers@orelit.com",
    "hcl": "careers_srilanka@hcl.com",
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
    "sliit": "careers@sliit.lk",
    "sltc": "careers@sltc.ac.lk",
    "abans": "careers@abansgroup.com",
    "daraz": "careers@daraz.lk",
    "nations trust": "careers@ntb.lk",
    "pan asia": "careers@pabcbank.com",
    "ndb": "careers@ndbbank.com",
    "singhagiri": "careers@singhagiri.lk",
    "toyota lanka": "careers@toyotalanka.lk",
    "konnect bpo": "careers@konnectbpo.com",
    "elevex": "careers@elevex.lk",
    "geoid": "careers@geoidit.com",
    "micronet": "careers@micronetglobal.net",
    "vs technologies": "careers@vstechnologies.lk",
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
    Returns a verified hiring email address for known Sri Lanka IT companies from the curated directory.
    Never guesses emails from arbitrary URLs or job aggregator domains.
    """
    if not company_name:
        return None

    clean = company_name.lower().strip()
    for ats_co in ATS_ONLY_COMPANIES:
        if ats_co in clean:
            return None

    for key, email in VERIFIED_COMPANY_EMAILS.items():
        if key in clean:
            domain = email.split("@")[-1] if "@" in email else ""
            if domain not in BLOCKED_EMAIL_DOMAINS and email not in BLOCKED_EMAILS:
                return email

    return None


import socket

def is_valid_email_domain(email: str) -> bool:
    """Checks if the email domain exists, is not blacklisted, and has valid mail exchange DNS records."""
    if not email or "@" not in email:
        return False
    clean_email = email.lower().strip()
    from .bounces import load_bounced

    if clean_email in BLOCKED_EMAILS or clean_email in load_bounced():
        return False

    domain = clean_email.split("@")[-1].strip()
    if domain in BLOCKED_EMAIL_DOMAINS:
        return False

    return _domain_accepts_mail(domain)


_MX_CACHE: dict[str, bool] = {}


def _domain_accepts_mail(domain: str) -> bool:
    """True only if the domain publishes a mail route.

    A plain A-record lookup (what this used to do) passes any domain that merely
    has a website, which is why guessed careers@ addresses bounced 550. 10 of the
    88 directory domains have a site but no mail server at all.
    """
    if domain in _MX_CACHE:
        return _MX_CACHE[domain]
    ok = False
    try:
        import dns.resolver

        try:
            ok = len(dns.resolver.resolve(domain, "MX")) > 0
        except (dns.resolver.Timeout, dns.resolver.NoNameservers, dns.exception.DNSException) as exc:
            # Transient lookup failure (burst timeouts, flaky link) is NOT proof
            # the domain cannot receive mail. Caching it would blacklist a real
            # employer for the whole run -- skip this send, retry next cycle.
            if isinstance(exc, (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)):
                _MX_CACHE[domain] = False
            return False
        except Exception:
            # No MX published. RFC 5321 allows an A-record fallback, but probing
            # port 25 is useless here: the ISP blocks outbound 25, so real mail
            # hosts (wso2.com) time out while proxies on non-mail domains answer
            # -- backwards signal. Any employer posting jobs publishes MX, so a
            # missing MX is treated as undeliverable.
            ok = False
    except ImportError:
        # ponytail: dnspython absent -> A-record check only, the old behaviour.
        # Bounces come back, so install dnspython rather than trusting this path.
        try:
            ok = len(socket.getaddrinfo(domain, None)) > 0
        except Exception:
            ok = False
    _MX_CACHE[domain] = ok
    return ok



_PAGE_EMAIL_CACHE: dict[str, str | None] = {}


def extract_email_from_page(apply_url: str) -> str | None:
    """Read the employer's real address off the live listing page.

    Stored descriptions are ~800-char summaries, so only 8 in 500 jobs carry an
    email. The full page often does (ikman.lk listings quote the employer's
    address directly). Board/aggregator addresses are filtered by the existing
    BLOCKED_EMAIL_DOMAINS set, so support@ikman.lk can never be picked.
    """
    if not apply_url or not apply_url.startswith(("http://", "https://")):
        return None
    if any(ats in apply_url for ats in ("greenhouse.io", "ashbyhq.com", "lever.co",
                                        "workday.com", "workable.com", "smartrecruiters.com")):
        return None
    if apply_url in _PAGE_EMAIL_CACHE:
        return _PAGE_EMAIL_CACHE[apply_url]

    # The board's own support address lives on the page too. Blocking by the
    # listing host covers every aggregator without maintaining a domain list
    # (ikman.lk vs ikman.com was exactly that gap).
    from urllib.parse import urlparse

    host = (urlparse(apply_url).hostname or "").lower().lstrip("www.")
    host_stem = host.split(".")[0] if host else ""

    found = None
    try:
        import requests

        html = requests.get(
            apply_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}
        ).text
        for cand in dict.fromkeys(EMAIL_RE.findall(html)):
            low = cand.lower().strip(".,;:")
            if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".css", ".js", ".svg", ".webp")):
                continue
            domain = low.split("@")[-1]
            if domain in BLOCKED_EMAIL_DOMAINS or low in BLOCKED_EMAILS:
                continue
            # same registrable name as the board we scraped -> it's the board
            if host_stem and domain.split(".")[0] == host_stem:
                continue
            if any(x in low for x in ("noreply", "no-reply", "example.", "sentry.io",
                                      "unsubscribe", "wordpress", "sentry", "@w3.org")):
                continue
            if is_valid_email_domain(low):
                found = low
                break
    except Exception as exc:
        print(f"  [email] page scan failed for {apply_url[:60]}: {str(exc)[:80]}")

    _PAGE_EMAIL_CACHE[apply_url] = found
    return found


def resolve_recruiter_email(company: str, job_desc: str = "", apply_url: str = "") -> str | None:
    """
    Strict Recruiter Email Discovery (Zero-Bounce Guarantee):
      Tier 0: Block ATS-only companies immediately (never email, use web portal)
      Tier 1: Real-time regex extraction from job description (explicitly provided email by employer)
      Tier 2: Master Sri Lanka IT Directory with DNS verification
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

    # Tier 1.5: Read the live listing page. Still the employer's own stated
    # address -- accurate, unlike the directory guess below.
    from_page = extract_email_from_page(apply_url)
    if from_page:
        return from_page

    # Tier 2: Check Master Sri Lanka IT Directory (GUESSED careers@ addresses --
    # last resort, gated by MX + the learned bounce blocklist)
    from_dir = derive_company_email(company, apply_url)
    if from_dir:
        if is_valid_email_domain(from_dir):
            return from_dir

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
    from .bounces import load_bounced

    if to_clean in BLOCKED_EMAILS or to_clean in load_bounced():
        return False

    domain = to_clean.split("@")[-1]
    if domain in BLOCKED_EMAIL_DOMAINS:
        return False

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

    # Force IPv4 socket resolution to prevent [Errno 101] Network is unreachable on cloud containers
    orig_getaddrinfo = socket.getaddrinfo
    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo
    try:
        # Try SSL port 465 first (most reliable on cloud platforms like Render)
        sent = False
        last_error = None
        ports_to_try = [465, 587] if settings.email_smtp_port == 465 else [settings.email_smtp_port, 465]
        for port in list(dict.fromkeys(ports_to_try)):
            try:
                if port == 465:
                    with smtplib.SMTP_SSL(settings.email_smtp_host, 465, context=context, timeout=25) as server:
                        server.login(settings.email_user, settings.email_app_password)
                        server.send_message(msg)
                        sent = True
                        break
                else:
                    with smtplib.SMTP(settings.email_smtp_host, port, timeout=25) as server:
                        server.starttls(context=context)
                        server.login(settings.email_user, settings.email_app_password)
                        server.send_message(msg)
                        sent = True
                        break
            except Exception as e:
                last_error = e
                continue
        if not sent and last_error:
            raise last_error
    finally:
        socket.getaddrinfo = orig_getaddrinfo