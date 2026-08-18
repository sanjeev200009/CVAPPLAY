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

# Broad software/developer/IT/AI/product keywords matching candidate profile
_TECH_KEYWORDS = re.compile(
    r"\b(software|developer|engineer|frontend|front.end|backend|back.end|"
    r"fullstack|full.stack|web|python|react|javascript|typescript|node|api|"
    r"qa|tester|intern|graduate|trainee|cloud|devops|data|ai|ml|it |"
    r"programmer|coding|junior|associate|product|next.js|nextjs|llm|automation|"
    r"agent|microservice|docker|kubernetes|linux|flask|fastapi|django|postgresql|"
    r"sql|database|mobile|android|ios|react native|flutter|chatbot|nlp|generative)\b",
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
        {"keywords": "next.js developer"},
        {"keywords": "AI engineer"},
        {"keywords": "product engineer"},
        {"keywords": "node.js developer"},
        {"keywords": "fastapi"},
        {"keywords": "automation engineer"},
        {"keywords": "data engineer"},
        {"keywords": "cloud engineer"},
        {"keywords": "associate product engineer"},
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
    """
    Deep Playwright scraper for TopJobs Sri Lanka IT & Tech vacancies.
    Fetches vacancies across IT, Software, Web, and AI categories.
    """

    name = "topjobs"

    SEARCH_TERMS = [
        "software engineer",
        "developer",
        "python",
        "react",
        "fullstack",
        "web developer",
        "associate software engineer",
        "trainee software engineer",
        "ai engineer",
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
                    links = re.findall(r'href="(/applicant/job[^"]*jobVacancyId=(\d+)[^"]*)"', html, re.IGNORECASE)
                    if not links:
                        links = re.findall(r'href="([^"]*acancyDetail[^"]*acancyId=(\d+)[^"]*)"', html, re.IGNORECASE)

                    for path, job_id in links[:12]:
                        if job_id in seen:
                            continue
                        seen.add(job_id)
                        job_url = f"https://topjobs.lk{path}" if path.startswith("/") else path

                        try:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
                            page.wait_for_timeout(1000)

                            html_content = page.content()
                            title_m = re.search(r"<title[^>]*>([^<|]+)", html_content, re.IGNORECASE)
                            title = re.sub(r"\s*[-|].*$", "", title_m.group(1).strip()) if title_m else f"Role {job_id}"

                            # Clean up generic title wrappers
                            title = re.sub(r"^(topjobs|vacancy|job)\s*:\s*", "", title, flags=re.IGNORECASE).strip()
                            if not title or len(title) < 3:
                                title = f"Software Role ({term.title()})"

                            if not _TECH_KEYWORDS.search(title) and not _TECH_KEYWORDS.search(term):
                                continue
                            if _TITLE_BLOCK_RE.search(title):
                                continue

                            body = page.locator("body").inner_text()
                            company_m = re.search(r"(?:company|employer|organisation|organization)\s*[:\-]?\s*([^\n]{3,60})", body, re.IGNORECASE)
                            company = company_m.group(1).strip() if company_m else "Sri Lanka IT Company"

                            # Use 3-tier resolver to extract direct hiring email
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
        # ─── Tier-1 Tech Giants & MNC Centers ───
        {"company": "Sysco LABS Sri Lanka", "email": "careers@syscolabs.lk", "url": "https://syscolabs.lk/careers", "roles": ["Associate Software Engineer", "Trainee Software Engineer", "Quality Assurance Engineer", "Junior DevOps Engineer"]},
        {"company": "99x", "email": "careers@99x.io", "url": "https://99x.io/careers", "roles": ["Trainee Software Engineer", "Associate Software Engineer", "Frontend Developer (React)", "Associate Product Engineer"]},
        {"company": "WSO2", "email": "careers@wso2.com", "url": "https://wso2.com/careers", "roles": ["Associate Software Engineer", "Cloud Engineer", "Integration Developer", "Associate AI Engineer"]},
        {"company": "Rootcode Labs", "email": "careers@rootcode.ai", "url": "https://rootcode.ai/careers", "roles": ["Associate Software Engineer", "Junior Fullstack Developer", "AI Developer Trainee", "Junior LLM Engineer"]},
        {"company": "Surge Global", "email": "careers@surge.global", "url": "https://surge.global/careers", "roles": ["Associate Web Developer", "Junior Python Developer", "React Developer", "Next.js Developer"]},
        {"company": "Calcey Technologies", "email": "careers@calcey.com", "url": "https://calcey.com/careers", "roles": ["Associate Software Engineer", "Python Developer", "React Developer", "Junior AI Engineer"]},
        {"company": "Creative Software", "email": "careers@creativesoftware.com", "url": "https://creativesoftware.com/careers", "roles": ["Associate Software Engineer", "Web Developer", "QA Engineer", "Node.js Developer"]},
        {"company": "Ascentic", "email": "careers@ascentic.lk", "url": "https://ascentic.lk/careers", "roles": ["Junior Fullstack Engineer", "Associate React Developer", "Node.js Developer", "Backend Python Developer"]},
        {"company": "Zone24x7", "email": "careers@zone24x7.com", "url": "https://zone24x7.com/careers", "roles": ["Associate Software Engineer", "Junior Systems Engineer", "QA Engineer"]},
        {"company": "Virtusa Sri Lanka", "email": "careers@virtusa.com", "url": "https://virtusa.com/careers", "roles": ["Associate Software Engineer", "Trainee Software Engineer", "Cloud Support Engineer", "Junior Data Engineer"]},
        {"company": "IFS Sri Lanka", "email": "careers@ifs.com", "url": "https://ifs.com/careers", "roles": ["Associate Software Engineer", "Junior Systems Engineer", "Cloud Associate Engineer"]},
        {"company": "Axienta", "email": "careers@axienta.com", "url": "https://axienta.com/careers", "roles": ["Associate Software Engineer", "Mobile / Web Developer", "Associate React Native Developer"]},
        {"company": "Pearson Lanka", "email": "careers@pearson.com", "url": "https://pearson.com/careers", "roles": ["Associate Software Engineer", "EdTech Web Developer", "Junior Next.js Engineer"]},
        {"company": "CodeGen International", "email": "careers@codegen.net", "url": "https://codegen.net/careers", "roles": ["Associate Software Engineer", "Software Engineer", "AI/ML Trainee", "Junior Python Engineer"]},
        {"company": "MillenniumIT ESP", "email": "careers@mitesp.com", "url": "https://mitesp.com/careers", "roles": ["Associate Software Engineer", "IT Support Engineer", "DevOps Trainee", "Junior Full-Stack Developer"]},
        {"company": "LSEG Sri Lanka", "email": "careers@lseg.com", "url": "https://lseg.com/careers", "roles": ["Associate Software Engineer", "Data Analyst", "Systems Engineer", "Junior Python Developer"]},
        {"company": "BISTEC Global", "email": "careers@bistecglobal.com", "url": "https://bistecglobal.com/careers", "roles": ["Associate Software Engineer", "React / Node.js Developer", "Junior Full-Stack Engineer"]},
        {"company": "Eficode Sri Lanka", "email": "careers@eficode.com", "url": "https://eficode.com/careers", "roles": ["Associate DevOps Engineer", "Trainee Software Engineer", "Cloud & Automation Engineer"]},
        {"company": "Fortude", "email": "careers@fortude.co", "url": "https://fortude.co/careers", "roles": ["Associate Software Engineer", "BI / Data Developer", "Junior API Engineer"]},
        {"company": "TIQRI", "email": "careers@tiqri.com", "url": "https://tiqri.com/careers", "roles": ["Associate Software Engineer", "Web Developer", "React.js Developer"]},
        {"company": "SimCentric Technologies", "email": "careers@simcentric.com", "url": "https://simcentric.com/careers", "roles": ["Software Engineer", "Python Developer", "Junior Simulation Engineer"]},
        {"company": "Aeturnum", "email": "careers@aeturnum.com", "url": "https://aeturnum.com/careers", "roles": ["Associate Software Engineer", "Fullstack Developer", "Junior React Engineer"]},
        {"company": "Cambio Software Engineering", "email": "careers@cambio.se", "url": "https://cambio.se/careers", "roles": ["Associate Software Engineer", "Java / Python Developer", "Cloud Engineer"]},
        {"company": "Inova IT Systems", "email": "careers@inovait.com", "url": "https://inovait.com/careers", "roles": ["Junior Web Developer", "Associate Software Engineer", "Next.js / React Developer"]},
        {"company": "DirectFN Sri Lanka", "email": "careers@directfn.com", "url": "https://directfn.com/careers", "roles": ["Associate Software Engineer", "FinTech Developer", "Junior Python Developer"]},

        # ─── AI Studios, Product Houses & High-Growth SaaS ───
        {"company": "Gapstars", "email": "careers@gapstars.net", "url": "https://gapstars.net/careers", "roles": ["Associate Software Engineer", "Junior Full-Stack Developer", "Associate Product Engineer"]},
        {"company": "Octave (John Keells AI Studio)", "email": "octave@keells.com", "url": "https://johnkeells.com/octave", "roles": ["Associate AI Engineer", "Junior Data Scientist", "AI/ML Trainee Engineer"]},
        {"company": "Mitra Innovation", "email": "careers@mitrai.com", "url": "https://mitrai.com/careers", "roles": ["Associate Software Engineer", "Junior AI Developer", "Full-Stack Developer", "Associate Product Engineer"]},
        {"company": "Enactor", "email": "careers@enactor.co", "url": "https://enactor.co/careers", "roles": ["Associate Software Engineer", "Junior Java / React Developer", "Trainee Software Engineer"]},
        {"company": "LinearSix", "email": "careers@linearsix.com", "url": "https://linearsix.com/careers", "roles": ["Associate FinTech Engineer", "Junior Python / Node.js Developer", "Frontend React Developer"]},
        {"company": "Arimac", "email": "careers@arimac.lk", "url": "https://arimac.lk/careers", "roles": ["Associate Software Engineer", "Junior Mobile Developer", "React Native / Flutter Developer"]},
        {"company": "Affinity Global", "email": "careers@affinity.lk", "url": "https://affinity.lk/careers", "roles": ["Associate Software Engineer", "Junior Full-Stack Developer", "Node.js / React Developer"]},
        {"company": "ISM APAC", "email": "careers@ismapac.com", "url": "https://ismapac.com/careers", "roles": ["Associate Software Engineer", "Trainee Developer", "QA / Automation Trainee"]},
        {"company": "Stax", "email": "careers@stax.com", "url": "https://stax.com/careers", "roles": ["Associate Cloud Engineer", "Junior DevOps Engineer", "Backend Python Developer"]},
        {"company": "Geveo Australasia", "email": "careers@geveo.com", "url": "https://geveo.com/careers", "roles": ["Associate Software Engineer", "Junior Full-Stack Developer", "QA Engineer"]},
        {"company": "Vimukti Technologies", "email": "careers@vimukti.com", "url": "https://vimukti.com/careers", "roles": ["Associate Software Engineer", "Junior Web Developer", "Python / Django Developer"]},
        {"company": "Attune", "email": "careers@attuneconsulting.com", "url": "https://attuneconsulting.com/careers", "roles": ["Associate Software Engineer", "Junior React Developer", "Cloud Support Trainee"]},

        # ─── Telecom, Enterprise IT & Digital Consultancies ───
        {"company": "hSenid Software", "email": "careers@hsenid.com", "url": "https://hsenid.com/careers", "roles": ["Associate Software Engineer", "Junior Mobile Developer", "Trainee Software Engineer"]},
        {"company": "hSenid Mobile Solutions", "email": "careers@hsenidmobile.com", "url": "https://hsenidmobile.com/careers", "roles": ["Associate Software Engineer", "Junior API Developer", "Telecom Software Trainee"]},
        {"company": "John Keells IT", "email": "careers@johnkeellsit.com", "url": "https://johnkeellsit.com/careers", "roles": ["Associate Software Engineer", "Junior Systems Developer", "IT Graduate Trainee"]},
        {"company": "Dialog Enterprise", "email": "careers@dialog.lk", "url": "https://dialog.lk/careers", "roles": ["Junior Software Engineer", "Associate Cloud Engineer", "API Developer"]},
        {"company": "Softlogic IT", "email": "careers@softlogic.lk", "url": "https://softlogic.lk/careers", "roles": ["Associate Software Engineer", "Junior Full-Stack Developer", "IT Graduate"]},
        {"company": "BellVantage", "email": "careers@bellvantage.com", "url": "https://bellvantage.com/careers", "roles": ["Associate Software Engineer", "Junior Web Developer", "Python Developer Trainee"]},
        {"company": "LOLC Tech", "email": "careers@lolctech.com", "url": "https://lolctech.com/careers", "roles": ["Associate Software Engineer", "Junior Web Developer", "FinTech Trainee"]},
        {"company": "Tech One Global Sri Lanka", "email": "careers@techoneglobal.com", "url": "https://techoneglobal.com/careers", "roles": ["Associate Software Engineer", "Cloud Support Engineer", "Microsoft Dynamics Trainee"]},
        {"company": "EY GDS Sri Lanka", "email": "careers@lk.ey.com", "url": "https://ey.com/careers", "roles": ["Associate Software Engineer", "Data & Analytics Associate", "IT Risk Trainee"]},
        {"company": "PwC Sri Lanka", "email": "careers@lk.pwc.com", "url": "https://pwc.com/lk/careers", "roles": ["Technology Consulting Associate", "Junior Developer", "Data Analyst Trainee"]},
        {"company": "KPMG Sri Lanka", "email": "careers@kpmg.lk", "url": "https://kpmg.com/lk/careers", "roles": ["IT Advisory Associate", "Junior Software Developer", "Cyber Security Trainee"]},
        {"company": "EW Information Systems (EWIS)", "email": "careers@ewis.lk", "url": "https://ewis.lk/careers", "roles": ["Associate Software Engineer", "Systems Support Engineer", "Hardware & Network Trainee"]},
        {"company": "VS Information Systems", "email": "careers@vsis.lk", "url": "https://vsis.lk/careers", "roles": ["Associate Software Engineer", "Network Engineer Trainee", "Cloud Support Engineer"]},
        {"company": "Metropolitan Technologies", "email": "careers@metropolitan.lk", "url": "https://metropolitan.lk/careers", "roles": ["IT Support Engineer", "Systems Engineer", "Associate Software Engineer"]},
        {"company": "Singer Sri Lanka IT", "email": "careers@singersl.com", "url": "https://singersl.com/careers", "roles": ["Junior ERP Developer", "IT Support Executive", "E-Commerce Web Developer"]},
        {"company": "Sunshine Holdings IT", "email": "careers@sunshineholdings.lk", "url": "https://sunshineholdings.lk/careers", "roles": ["IT Executive", "Associate Software Engineer", "Systems Administrator Trainee"]},
        {"company": "Aitken Spence IT", "email": "careers@aitkenspence.lk", "url": "https://aitkenspence.lk/careers", "roles": ["Associate Software Engineer", "Junior Web Developer", "IT Graduate Trainee"]},
        {"company": "Kingslake Software", "email": "careers@kingslake.com", "url": "https://kingslake.com/careers", "roles": ["Associate Software Engineer", "Junior ERP Consultant", "React Developer"]},
        {"company": "BConnected Sri Lanka", "email": "careers@bconnected.lk", "url": "https://bconnected.lk/careers", "roles": ["Junior Web Developer", "IT Support Engineer", "Software Trainee"]},
        {"company": "Cenmetrix", "email": "careers@cenmetrix.lk", "url": "https://cenmetrix.lk/careers", "roles": ["Associate Software Engineer", "Biometric Software Developer", "IoT Trainee"]},
        {"company": "SQA Concepts", "email": "careers@sqaconcepts.com", "url": "https://sqaconcepts.com/careers", "roles": ["Trainee QA Engineer", "Associate Software Tester", "Automation Engineer"]},
        {"company": "WebLook International", "email": "careers@weblook.com", "url": "https://weblook.com/careers", "roles": ["Junior Fullstack Developer", "React/Node.js Developer", "Web Developer Trainee"]},
        {"company": "Ceylon Linux", "email": "careers@ceylonlinux.com", "url": "https://ceylonlinux.com/careers", "roles": ["Junior Linux Systems Administrator", "Cloud Support Engineer", "Python Developer"]},
        {"company": "LinearSquared AI", "email": "careers@linearsquared.ai", "url": "https://linearsquared.ai/careers", "roles": ["Associate AI Engineer", "Junior Data Engineer", "Python AI Trainee"]},
        {"company": "Roar Tech / Roar Global", "email": "careers@roar.global", "url": "https://roar.global/careers", "roles": ["Associate Fullstack Developer", "React Developer", "Python Backend Developer"]},
        {"company": "PickMe Sri Lanka", "email": "careers@pickme.lk", "url": "https://pickme.lk/careers", "roles": ["Associate Software Engineer", "Junior Mobile Developer", "Backend Node.js Developer"]},
        {"company": "Kapruka IT", "email": "careers@kapruka.com", "url": "https://kapruka.com/careers", "roles": ["E-Commerce Web Developer", "Associate Software Engineer", "Python / Django Developer"]},
        {"company": "Bhasha / Helakuru", "email": "careers@bhasha.lk", "url": "https://bhasha.lk/careers", "roles": ["Associate Software Engineer", "Junior Mobile Developer (Android/iOS)", "React Native Developer"]},
        {"company": "PayHere", "email": "careers@payhere.lk", "url": "https://payhere.lk/careers", "roles": ["Associate FinTech Engineer", "API Integration Developer", "Node.js Developer"]},
        {"company": "MintPay", "email": "careers@mintpay.lk", "url": "https://mintpay.lk/careers", "roles": ["Associate Software Engineer", "Junior Fullstack Developer", "FinTech Trainee"]},
        {"company": "WEBXPAY", "email": "careers@webxpay.com", "url": "https://webxpay.com/careers", "roles": ["Associate FinTech Developer", "Web Developer", "Payment Gateway Trainee"]},
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


class IkmanJobsSource(JobSource):
    """Fetches Sri Lanka tech & IT vacancies from Ikman.lk marketplace."""

    name = "ikman_lk"

    SEARCH_KEYWORDS = ["software", "developer", "web developer", "it assistant", "network", "intern"]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html",
        }

        for kw in self.SEARCH_KEYWORDS:
            try:
                url = f"https://ikman.lk/en/ads/sri-lanka/jobs?query={requests.utils.quote(kw)}"
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue

                html = resp.text
                matches = re.findall(r'href="(/en/ad/([^"]+))"', html)
                for path, ad_slug in matches[:10]:
                    if ad_slug in seen:
                        continue
                    seen.add(ad_slug)
                    ad_url = f"https://ikman.lk{path}"

                    title_parts = ad_slug.split("-for-sale-")[0].split("-in-")[0].replace("-", " ").title()
                    if not _TECH_KEYWORDS.search(title_parts) or _JUNK_TITLES.search(title_parts):
                        continue

                    email = _extract_email(ad_slug)
                    apply_target = f"mailto:{email}" if email else ad_url

                    jobs.append(Job(
                        source=self.name,
                        external_id=_slug_id("ikman", ad_slug),
                        company="Sri Lanka Employer (Ikman.lk)",
                        title=title_parts[:120],
                        location=LK_LOCATION,
                        remote=False,
                        description=f"Position: {title_parts} in Sri Lanka via Ikman.lk Jobs portal.",
                        apply_url=apply_target,
                    ))
            except Exception as exc:
                self.errors.append(f"ikman term '{kw}': {str(exc)[:100]}")

        return jobs


class DreamJobsLKSource(JobSource):
    """Fetches Sri Lanka vacancies from DreamJobs.lk."""

    name = "dreamjobs_lk"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            url = "https://www.dreamjobs.lk/jobs/category/IT-Software"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                job_links = re.findall(r'href="(/job/view/[^"]+)"', html)
                seen: set[str] = set()
                for link in job_links[:15]:
                    if link in seen:
                        continue
                    seen.add(link)
                    job_url = f"https://www.dreamjobs.lk{link}"
                    slug = link.split("/")[-1].replace("-", " ").title()
                    if _TECH_KEYWORDS.search(slug) and not _TITLE_BLOCK_RE.search(slug):
                        jobs.append(Job(
                            source=self.name,
                            external_id=_slug_id("dreamjobs", link),
                            company="DreamJobs Sri Lanka Client",
                            title=slug[:120],
                            location=LK_LOCATION,
                            remote=False,
                            description=f"IT & Software opening: {slug} on DreamJobs.lk Sri Lanka.",
                            apply_url=job_url,
                        ))
        except Exception as exc:
            self.errors.append(f"dreamjobs fetch: {str(exc)[:100]}")
        return jobs


class JobseekerLKSource(JobSource):
    """Fetches Sri Lanka vacancies from Jobseeker.lk."""

    name = "jobseeker_lk"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            url = "https://jobseeker.lk/vacancies?category=IT"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                job_links = re.findall(r'href="(/vacancy/view/[^"]+)"', html)
                seen: set[str] = set()
                for link in job_links[:15]:
                    if link in seen:
                        continue
                    seen.add(link)
                    job_url = f"https://jobseeker.lk{link}"
                    slug = link.split("/")[-1].replace("-", " ").title()
                    if _TECH_KEYWORDS.search(slug) and not _TITLE_BLOCK_RE.search(slug):
                        jobs.append(Job(
                            source=self.name,
                            external_id=_slug_id("jobseeker", link),
                            company="Jobseeker Sri Lanka Client",
                            title=slug[:120],
                            location=LK_LOCATION,
                            remote=False,
                            description=f"Tech opening: {slug} on Jobseeker.lk Sri Lanka.",
                            apply_url=job_url,
                        ))
        except Exception as exc:
            self.errors.append(f"jobseeker fetch: {str(exc)[:100]}")
        return jobs


class ITJobsLKSource(JobSource):
    """Fetches Sri Lanka vacancies from ITJobs.lk."""

    name = "itjobs_lk"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            url = "https://www.itjobs.lk/vacancies"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                job_links = re.findall(r'href="(/job/[^"]+)"', html)
                seen: set[str] = set()
                for link in job_links[:15]:
                    if link in seen:
                        continue
                    seen.add(link)
                    job_url = f"https://www.itjobs.lk{link}"
                    slug = link.split("/")[-1].replace("-", " ").title()
                    if _TECH_KEYWORDS.search(slug):
                        jobs.append(Job(
                            source=self.name,
                            external_id=_slug_id("itjobs", link),
                            company="ITJobs Sri Lanka Client",
                            title=slug[:120],
                            location=LK_LOCATION,
                            remote=False,
                            description=f"IT vacancy: {slug} on ITJobs.lk Sri Lanka.",
                            apply_url=job_url,
                        ))
        except Exception as exc:
            self.errors.append(f"itjobs fetch: {str(exc)[:100]}")
        return jobs


class ITProLKSource(JobSource):
    """Fetches Sri Lanka tech & IT vacancies from ITPro.lk (RSS & direct web)."""

    name = "itpro_lk"

    CATEGORIES = [
        "https://itpro.lk/jobs/information-technology/",
        "https://itpro.lk/jobs/web-development/",
        "https://itpro.lk/jobs/devops-cloud/",
        "https://itpro.lk/jobs/software-engineering/",
    ]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        for cat_url in self.CATEGORIES:
            try:
                resp = requests.get(cat_url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue

                html = resp.text
                job_links = set(re.findall(r'href="([^"]*itpro\.lk/job/\d+/[^"]+)"', html))
                for job_url in list(job_links)[:15]:
                    jid_m = re.search(r'/job/(\d+)/([^/]+)', job_url)
                    if not jid_m:
                        continue
                    jid = jid_m.group(1)
                    slug = jid_m.group(2)
                    if jid in seen:
                        continue
                    seen.add(jid)

                    clean_slug = slug.replace("-at-", " | ").replace("-", " ").title()
                    parts = clean_slug.split(" | ")
                    title = parts[0].strip() if parts else "IT Role"
                    company = parts[1].strip() if len(parts) > 1 else "Sri Lanka IT Employer"

                    if not _TECH_KEYWORDS.search(title) and not _TECH_KEYWORDS.search(slug):
                        continue

                    email = _extract_email(slug)
                    apply_target = f"mailto:{email}" if email else job_url

                    jobs.append(Job(
                        source=self.name,
                        external_id=jid,
                        company=company[:100],
                        title=title[:120],
                        location=LK_LOCATION,
                        remote=False,
                        description=f"{title} position at {company} in Sri Lanka via ITPro.lk.",
                        apply_url=apply_target,
                    ))
            except Exception as exc:
                self.errors.append(f"itpro_lk fetch {cat_url}: {str(exc)[:100]}")

        return jobs


class DevJobsLKSource(JobSource):
    """Fetches Sri Lanka developer positions from DevJobs.lk."""

    name = "devjobs_lk"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        try:
            url = "https://devjobs.lk/"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                job_ids = set(re.findall(r'href="[^"]*devjobs\.lk/dev-jobs/client/ads/(\d+)"', html))
                for jid in list(job_ids)[:20]:
                    if jid in seen:
                        continue
                    seen.add(jid)
                    job_url = f"https://devjobs.lk/dev-jobs/client/ads/{jid}"

                    try:
                        r_detail = requests.get(job_url, headers=headers, timeout=10)
                        if r_detail.status_code == 200:
                            body = r_detail.text
                            title_m = re.search(r"<h[12][^>]*>([^<]+)", body, re.IGNORECASE)
                            title = title_m.group(1).strip() if title_m else f"Software Engineer ({jid})"
                            title = re.sub(r"^(devjobs|job|vacancy)\s*:\s*", "", title, flags=re.IGNORECASE).strip()

                            comp_m = re.search(r"(?:company|at|employer)\s*[:\-]?\s*([^\n<]{3,50})", body, re.IGNORECASE)
                            company = comp_m.group(1).strip() if comp_m else "Sri Lanka Dev Firm"

                            email = _extract_email(body)
                            apply_target = f"mailto:{email}" if email else job_url

                            jobs.append(Job(
                                source=self.name,
                                external_id=jid,
                                company=company[:100],
                                title=title[:120],
                                location=LK_LOCATION,
                                remote=False,
                                description=_clean_text(body)[:5000],
                                apply_url=apply_target,
                            ))
                    except Exception:
                        pass
        except Exception as exc:
            self.errors.append(f"devjobs fetch: {str(exc)[:100]}")

        return jobs

