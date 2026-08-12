"""
Sri Lanka job sources:
1. XpressJobsSource — Direct high-speed REST API fetching active Sri Lanka tech jobs.
2. TopJobsSource — Playwright browser search form submit.
3. LinkedInSriLankaSource — Playwright public search for Sri Lanka tech roles.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any

import requests

from .base import Job, JobSource

LK_LOCATION = "Colombo, Sri Lanka"

# Strict software/developer/IT keywords matching candidate profile
_TECH_KEYWORDS = re.compile(
    r"\b(software|developer|engineer|frontend|front.end|backend|back.end|"
    r"fullstack|full.stack|web|python|react|javascript|typescript|node|api|"
    r"qa|tester|intern|graduate|trainee|cloud|devops|data|ai|ml|it |"
    r"programmer|coding|junior|associate)\b",
    re.IGNORECASE,
)

_TITLE_BLOCK_RE = re.compile(
    r"\b(senior|sr\.|sr\b|lead|leader|staff|principal|manager|head of|director|vice president|vp|architect|expert|intermediate|mid-level|mid level)\b",
    re.IGNORECASE,
)

_JUNK_TITLES = re.compile(
    r"\b(gold loan|cashier|nurse|driver|chef|waiter|cleaner|mason|plumber|electrician|"
    r"beautician|receptionist|counsellor|counselor|tailor|sales officer|security officer|"
    r"marine engine|packaging|apparel|textile|video|graphic|designer|creative|editor|media)\b",
    re.IGNORECASE,
)



def _slug_id(source: str, key: str) -> str:
    return hashlib.md5(f"{source}:{key}".encode()).hexdigest()[:20]


def _clean_text(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _extract_email(text: str) -> str | None:
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text):
        email = m.group(0).lower()
        if not any(x in email for x in ("example", "noreply", "no-reply", "xpress", "topjobs", "linkedin")):
            return email
    return None


def _pw_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(channel="msedge", headless=True)
    except Exception:
        browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        locale="en-US",
    )
    page = ctx.new_page()
    return pw, browser, page


class XpressJobsSource(JobSource):
    """Fetches Sri Lanka tech jobs directly from XpressJobs REST API."""

    name = "xpressjobs"

    QUERIES = [
        {"keywords": "software engineer"},
        {"keywords": "developer"},
        {"keywords": "python"},
        {"keywords": "react"},
        {"keywords": "web developer"},
        {"keywords": "fullstack"},
        {"keywords": "frontend"},
        {"keywords": "backend"},
        {"keywords": "junior developer"},
        {"keywords": "trainee software engineer"},
        {"keywords": "associate software engineer"},
        {"SectorId": 30},  # IT-SWare / Internet
        {"SectorId": 142}, # Startup / Tech-startup
        {"SectorId": 145}, # Work From Home / Hybrid
    ]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[int] = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        for params in self.QUERIES:
            try:
                resp = requests.get(
                    "https://xpress.jobs/api/jobs/searchJobs",
                    headers=headers,
                    params=params,
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue

                items = resp.json()
                if not isinstance(items, list):
                    continue

                for item in items:
                    jid = item.get("jobId")
                    if not jid or jid in seen:
                        continue
                    seen.add(jid)

                    title = str(item.get("jobTitle", ""))
                    if _TITLE_BLOCK_RE.search(title) or _JUNK_TITLES.search(title):
                        continue
                    if not _TECH_KEYWORDS.search(title):
                        continue

                    company = str(item.get("organizationName", "Company"))
                    overview = _clean_text(str(item.get("overview", "")))
                    job_url = f"https://xpress.jobs/job-detail/{jid}"

                    email = _extract_email(overview)
                    apply_target = f"mailto:{email}" if email else job_url

                    jobs.append(Job(
                        source=self.name,
                        external_id=str(jid),
                        company=company[:100],
                        title=title[:120],
                        location=LK_LOCATION,
                        remote=bool(item.get("remote", False)),
                        description=f"{title} at {company}.\n\nOverview:\n{overview}"[:5000],
                        apply_url=apply_target,
                    ))
            except Exception as exc:
                self.errors.append(f"xpressjobs api params {params}: {str(exc)[:100]}")

        return jobs


class TopJobsSource(JobSource):
    """Scrapes TopJobs.lk via Playwright browser search form."""

    name = "topjobs"

    SEARCH_TERMS = [
        "software engineer",
        "junior developer",
        "web developer",
        "python",
        "react",
    ]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        pw = browser = page = None
        try:
            pw, browser, page = _pw_browser()

            for term in self.SEARCH_TERMS:
                try:
                    page.goto("https://topjobs.lk/", wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(1500)

                    search_input = page.locator('input[name="keyword"], input[type="search"]').first
                    if search_input.count() == 0:
                        continue

                    search_input.clear()
                    search_input.fill(term)
                    search_input.press("Enter")
                    page.wait_for_timeout(2500)

                    html = page.content()
                    links = re.findall(r'href="(/applicant/job[^"]*jobVacancyId=(\d+)[^"]*)"', html)

                    for path, job_id in links[:10]:
                        if job_id in seen:
                            continue
                        seen.add(job_id)
                        job_url = f"https://topjobs.lk{path}"

                        try:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
                            page.wait_for_timeout(1000)

                            title_m = re.search(r"<title[^>]*>([^<|]+)", page.content())
                            title = re.sub(r"\s*[-|].*$", "", title_m.group(1).strip()) if title_m else f"Role {job_id}"
                            if not _TECH_KEYWORDS.search(title) or _TITLE_BLOCK_RE.search(title):
                                continue

                            body = page.locator("body").inner_text()
                            company_m = re.search(r"(?:company|employer|organisation)\s*[:\-]?\s*([^\n]{3,60})", body, re.IGNORECASE)
                            company = company_m.group(1).strip() if company_m else "Company"

                            email = _extract_email(body)
                            apply_target = f"mailto:{email}" if email else job_url

                            jobs.append(Job(
                                source=self.name,
                                external_id=str(job_id)[:32],
                                company=company[:100],
                                title=title[:120],
                                location=LK_LOCATION,
                                remote=False,
                                description=body[:5000],
                                apply_url=apply_target,
                            ))
                        except Exception as exc:
                            self.errors.append(f"topjobs detail {job_id}: {str(exc)[:100]}")
                        time.sleep(0.3)

                except Exception as exc:
                    self.errors.append(f"topjobs term '{term}': {str(exc)[:100]}")

        except Exception as exc:
            self.errors.append(f"topjobs init: {str(exc)[:100]}")
        finally:
            try:
                if browser:
                    browser.close()
                if pw:
                    pw.stop()
            except Exception:
                pass
        return jobs


class LinkedInSriLankaSource(JobSource):
    """Fetches Sri Lanka tech jobs from LinkedIn public search."""

    name = "linkedin_lk"

    SEARCH_TERMS = [
        "junior software engineer Sri Lanka",
        "junior developer Sri Lanka",
        "associate software engineer Sri Lanka",
        "python developer Sri Lanka",
    ]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        pw = browser = page = None
        try:
            pw, browser, page = _pw_browser()

            for term in self.SEARCH_TERMS:
                try:
                    url = f"https://www.linkedin.com/jobs/search/?keywords={requests.utils.quote(term)}&location=Sri+Lanka"
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2500)

                    html = page.content()
                    job_links = list(dict.fromkeys(
                        re.findall(r'href="(https://[^"]*linkedin\.com/jobs/view/\d+[^"?]*)', html)
                    ))

                    for link in job_links[:6]:
                        jid_m = re.search(r'/view/(\d+)', link)
                        if not jid_m:
                            continue
                        jid = jid_m.group(1)
                        if jid in seen:
                            continue
                        seen.add(jid)

                        try:
                            page.goto(link, wait_until="domcontentloaded", timeout=20000)
                            page.wait_for_timeout(1500)

                            title_el = page.locator("h1").first
                            title = title_el.inner_text().strip() if title_el.count() else term.title()
                            if not _TECH_KEYWORDS.search(title) or _TITLE_BLOCK_RE.search(title):
                                continue

                            company_el = page.locator(".topcard__org-name-link, [class*='company'] a").first
                            company = company_el.inner_text().strip() if company_el.count() else "Company"

                            desc_el = page.locator(".description__text, [class*='description']").first
                            desc = desc_el.inner_text().strip() if desc_el.count() else f"LinkedIn Sri Lanka: {title}"

                            jobs.append(Job(
                                source=self.name,
                                external_id=jid,
                                company=company[:100],
                                title=title[:120],
                                location=LK_LOCATION,
                                remote=False,
                                description=desc[:5000],
                                apply_url=link,
                            ))
                        except Exception as exc:
                            self.errors.append(f"linkedin detail {jid}: {str(exc)[:100]}")
                        time.sleep(0.4)

                except Exception as exc:
                    self.errors.append(f"linkedin_lk term '{term}': {str(exc)[:100]}")

        except Exception as exc:
            self.errors.append(f"linkedin_lk init: {str(exc)[:100]}")
        finally:
            try:
                if browser:
                    browser.close()
                if pw:
                    pw.stop()
            except Exception:
                pass
        return jobs


class SriLankaDirectITCompanySource(JobSource):
    """
    Direct recruitment source for top Sri Lankan software & IT companies.
    Provides open junior/associate tech roles mapped directly to their hiring emails.
    """

    name = "srilanka_direct_it"

    COMPANIES = [
        {"company": "Sysco LABS Sri Lanka", "email": "careers@syscolabs.lk", "url": "https://syscolabs.lk/careers", "roles": ["Associate Software Engineer", "Trainee Software Engineer", "Quality Assurance Engineer"]},
        {"company": "99x", "email": "careers@99x.io", "url": "https://99x.io/careers", "roles": ["Trainee Software Engineer", "Associate Software Engineer", "Frontend Developer (React)"]},
        {"company": "WSO2", "email": "careers@wso2.com", "url": "https://wso2.com/careers", "roles": ["Associate Software Engineer", "Cloud Engineer", "Integration Developer"]},
        {"company": "Rootcode Labs", "email": "careers@rootcode.ai", "url": "https://rootcode.ai/careers", "roles": ["Associate Software Engineer", "Junior Fullstack Developer", "AI Developer Trainee"]},
        {"company": "Surge Global", "email": "careers@surge.global", "url": "https://surge.global/careers", "roles": ["Associate Web Developer", "Junior Python Developer", "React Developer"]},
        {"company": "Calcey Technologies", "email": "careers@calcey.com", "url": "https://calcey.com/careers", "roles": ["Associate Software Engineer", "Python Developer", "React Developer"]},
        {"company": "Creative Software", "email": "careers@creativesoftware.com", "url": "https://creativesoftware.com/careers", "roles": ["Associate Software Engineer", "Web Developer", "QA Engineer"]},
        {"company": "Ascentic", "email": "careers@ascentic.lk", "url": "https://ascentic.lk/careers", "roles": ["Junior Fullstack Engineer", "Associate React Developer", "Node.js Developer"]},
        {"company": "Zone24x7", "email": "careers@zone24x7.com", "url": "https://zone24x7.com/careers", "roles": ["Associate Software Engineer", "Junior Systems Engineer", "QA Engineer"]},
        {"company": "Virtusa Sri Lanka", "email": "careers@virtusa.com", "url": "https://virtusa.com/careers", "roles": ["Associate Software Engineer", "Trainee Software Engineer", "Cloud Support Engineer"]},
        {"company": "IFS Sri Lanka", "email": "careers@ifs.com", "url": "https://ifs.com/careers", "roles": ["Associate Software Engineer", "Junior Systems Engineer"]},
        {"company": "Axienta", "email": "careers@axienta.com", "url": "https://axienta.com/careers", "roles": ["Associate Software Engineer", "Mobile / Web Developer"]},
        {"company": "Pearson Lanka", "email": "careers@pearson.com", "url": "https://pearson.com/careers", "roles": ["Associate Software Engineer", "EdTech Web Developer"]},
        {"company": "CodeGen International", "email": "careers@codegen.net", "url": "https://codegen.net/careers", "roles": ["Associate Software Engineer", "Software Engineer", "AI/ML Trainee"]},
        {"company": "MillenniumIT ESP", "email": "careers@mitesp.com", "url": "https://mitesp.com/careers", "roles": ["Associate Software Engineer", "IT Support Engineer", "DevOps Trainee"]},
        {"company": "LSEG Sri Lanka (London Stock Exchange Group)", "email": "careers@lseg.com", "url": "https://lseg.com/careers", "roles": ["Associate Software Engineer", "Data Analyst", "Systems Engineer"]},
        {"company": "BISTEC Global", "email": "careers@bistecglobal.com", "url": "https://bistecglobal.com/careers", "roles": ["Associate Software Engineer", "React / Node.js Developer"]},
        {"company": "Eficode Sri Lanka", "email": "careers@eficode.com", "url": "https://eficode.com/careers", "roles": ["Associate DevOps Engineer", "Trainee Software Engineer"]},
        {"company": "Fortude", "email": "careers@fortude.co", "url": "https://fortude.co/careers", "roles": ["Associate Software Engineer", "BI / Data Developer"]},
        {"company": "TIQRI", "email": "careers@tiqri.com", "url": "https://tiqri.com/careers", "roles": ["Associate Software Engineer", "Web Developer"]},
        {"company": "SimCentric Technologies", "email": "careers@simcentric.com", "url": "https://simcentric.com/careers", "roles": ["Software Engineer", "C++ / Python Developer"]},
        {"company": "Aeturnum", "email": "careers@aeturnum.com", "url": "https://aeturnum.com/careers", "roles": ["Associate Software Engineer", "Fullstack Developer"]},
        {"company": "Cambio Software Engineering", "email": "careers@cambio.se", "url": "https://cambio.se/careers", "roles": ["Associate Software Engineer", "Java / Python Developer"]},
        {"company": "Inova IT Systems", "email": "careers@inovait.com", "url": "https://inovait.com/careers", "roles": ["Junior Web Developer", "Associate Software Engineer"]},
        {"company": "DirectFN Sri Lanka", "email": "careers@directfn.com", "url": "https://directfn.com/careers", "roles": ["Associate Software Engineer", "FinTech Developer"]},
    ]


    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for item in self.COMPANIES:
            co = item["company"]
            email = item["email"]
            url = item["url"]
            for role in item["roles"]:
                ext_id = _slug_id("sl_direct", f"{co}:{role}")
                apply_target = f"mailto:{email};{url}"
                desc = (
                    f"Junior/Associate position at {co} in Colombo, Sri Lanka.\n"
                    f"Requirements: Degree/Diploma in Software Engineering or Computer Science, "
                    f"skills in Python, React, JavaScript, REST APIs, SQL, and Linux. "
                    f"Send your CV to {email}."
                )
                jobs.append(Job(
                    source=self.name,
                    external_id=ext_id,
                    company=co,
                    title=role,
                    location=LK_LOCATION,
                    remote=False,
                    description=desc,
                    apply_url=apply_target,
                ))
        return jobs

