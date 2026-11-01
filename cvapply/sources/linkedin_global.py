"""
LinkedIn Global Remote Jobs source.
Uses Playwright to scrape LinkedIn public job search (no login required for listings).
Fully block-aware — returns empty list gracefully when blocked or login-walled.
"""
from __future__ import annotations

import re
import time

import requests

from .base import Job, JobSource
from ..config import settings

_TITLE_BLOCK_RE = re.compile(
    r"\b(senior|sr\.|sr\b|lead|leader|staff|principal|manager|head of|director|"
    r"vice president|vp|architect|expert|intermediate|mid-level|mid level)\b",
    re.IGNORECASE,
)

_TECH_KW_RE = re.compile(
    r"\b(software|developer|engineer|frontend|backend|fullstack|web|python|"
    r"react|javascript|typescript|ai|ml|data|node|api|qa|intern|graduate|"
    r"associate|trainee|product|next\.?js|llm|automation|devops|cloud)\b",
    re.IGNORECASE,
)

# How many jobs to collect per search term
_PER_TERM_LIMIT = 5
# Maximum total jobs from this source per run
_TOTAL_LIMIT = 40


def _pw_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(channel="msedge", headless=True)
    except Exception:
        browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()
    return pw, browser, page


def _is_blocked(page) -> bool:
    """Detect LinkedIn login walls and CAPTCHA pages."""
    url = page.url.lower()
    if "linkedin.com/checkpoint" in url:
        return True
    if "linkedin.com/authwall" in url:
        return True
    if "linkedin.com/signup" in url:
        return True
    try:
        # Check for login prompt overlay
        if page.locator('button:has-text("Sign in"), a:has-text("Sign in to view more")').count() > 0:
            # Only block if job listings are absent
            if page.locator('[class*="job-search-card"], [class*="base-card"]').count() == 0:
                return True
    except Exception:
        pass
    return False


class LinkedInGlobalSource(JobSource):
    """
    Scrapes LinkedIn public job search for remote roles matching 14 title variants.
    Gracefully returns [] when blocked — never attempts login or CAPTCHA bypass.
    """
    name = "linkedin_global"

    def __init__(self) -> None:
        super().__init__()
        # Use the centralised title list from settings
        self.search_terms = [f"{t} remote" for t in settings.search_titles[:10]]

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        pw = browser = page = None

        try:
            pw, browser, page = _pw_browser()
        except Exception as exc:
            self.errors.append(f"linkedin_global browser init: {exc}")
            return jobs

        try:
            for term in self.search_terms:
                if len(jobs) >= _TOTAL_LIMIT:
                    break
                try:
                    encoded = requests.utils.quote(term)
                    # f_WT=2 = Remote only filter
                    url = f"https://www.linkedin.com/jobs/search/?keywords={encoded}&f_WT=2&sortBy=DD"
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2500)

                    if _is_blocked(page):
                        self.errors.append(f"linkedin_global: blocked/login_wall on '{term}' — skipping remaining terms")
                        break

                    html = page.content()
                    # Extract job card links
                    job_links = list(dict.fromkeys(
                        re.findall(r'href="(https://[^"]*linkedin\.com/jobs/view/\d+[^"?]*)', html)
                    ))

                    count_this_term = 0
                    for link in job_links:
                        if count_this_term >= _PER_TERM_LIMIT or len(jobs) >= _TOTAL_LIMIT:
                            break

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

                            if _is_blocked(page):
                                self.errors.append("linkedin_global: blocked while fetching job detail")
                                break

                            title_el = page.locator("h1.top-card-layout__title, h1[class*='title']").first
                            if title_el.count() == 0:
                                title_el = page.locator("h1").first
                            title = title_el.inner_text().strip() if title_el.count() else term.title()

                            if not _TECH_KW_RE.search(title) or _TITLE_BLOCK_RE.search(title):
                                continue

                            company_el = page.locator(
                                ".topcard__org-name-link, [class*='company'] a, "
                                "[class*='topcard__flavor--black-link']"
                            ).first
                            company = company_el.inner_text().strip() if company_el.count() else "LinkedIn Company"

                            desc_el = page.locator(
                                ".description__text, [class*='description__text'], "
                                "[class*='show-more-less-html__markup']"
                            ).first
                            desc = desc_el.inner_text().strip() if desc_el.count() else f"LinkedIn remote role: {title}"

                            jobs.append(Job(
                                source=self.name,
                                external_id=jid,
                                company=company[:100],
                                title=title[:120],
                                location="Remote",
                                remote=True,
                                description=desc[:5000],
                                apply_url=link,
                            ))
                            count_this_term += 1
                            time.sleep(0.5)

                        except Exception as exc:
                            self.errors.append(f"linkedin_global detail {jid}: {str(exc)[:100]}")

                    time.sleep(0.8)

                except Exception as exc:
                    self.errors.append(f"linkedin_global term '{term}': {str(exc)[:100]}")

        finally:
            try:
                if browser:
                    browser.close()
                if pw:
                    pw.stop()
            except Exception:
                pass

        return jobs
