"""
Indeed Sri Lanka source.
Tries the Indeed LK public search JSON endpoint first, then falls back to
Playwright HTML scraping. Gracefully skips on CAPTCHA / redirect blocks.
"""
from __future__ import annotations

import re
import time

import requests

from .base import Job, JobSource
from .greenhouse import strip_html
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

_LK_LOCATION = "Colombo, Sri Lanka"

# Per-term job limit when scraping
_PER_TERM_LIMIT = 6
_TOTAL_LIMIT = 35

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _is_blocked_html(html: str) -> bool:
    """Detect Indeed CAPTCHA, interstitial, or empty result pages."""
    lower = html.lower()
    captcha_signals = [
        "captcha", "are you a robot", "verify you are human",
        "access denied", "unusual traffic", "unusual activity",
    ]
    return any(s in lower for s in captcha_signals)


def _parse_indeed_json(data: dict) -> list[Job]:
    """Parse the JSON response from the Indeed internal search API."""
    jobs: list[Job] = []
    results = (
        data.get("results") or
        data.get("data", {}).get("results") or
        data.get("jobs") or
        []
    )
    for j in results:
        title = (j.get("title") or j.get("displayTitle") or "").strip()
        company = (j.get("company") or j.get("companyName") or "Indeed LK Company").strip()
        location = (j.get("formattedLocation") or j.get("location") or _LK_LOCATION)
        desc = strip_html(j.get("snippet") or j.get("description") or "")
        if not desc:
            desc = f"{title} at {company} in Sri Lanka."
        job_url = j.get("url") or j.get("jobUrl") or j.get("viewJobLink") or ""
        if job_url and not job_url.startswith("http"):
            job_url = f"https://lk.indeed.com{job_url}"
        external_id = str(j.get("jobKey") or j.get("id") or j.get("jk") or f"{company}:{title}")[:40]
        is_remote = "remote" in (location or "").lower()

        jobs.append(Job(
            source="indeed_lk",
            external_id=external_id,
            company=company[:100],
            title=title[:120],
            location=location,
            remote=is_remote,
            description=desc[:5000],
            apply_url=job_url or f"https://lk.indeed.com/jobs?q={requests.utils.quote(title)}",
        ))
    return jobs


class IndeedLKSource(JobSource):
    """
    Indeed Sri Lanka source.
    Attempts JSON API first, then Playwright HTML scraping.
    Returns Manual Action Required entries when access is blocked.
    """
    name = "indeed_lk"

    def __init__(self) -> None:
        super().__init__()
        self.search_terms = settings.search_titles[:8]

    def _try_json_api(self, keyword: str) -> list[Job]:
        """Try the undocumented Indeed internal JSON endpoint."""
        try:
            resp = requests.get(
                "https://lk.indeed.com/jobs",
                params={"q": keyword, "l": "Sri Lanka", "format": "json"},
                headers=HEADERS,
                timeout=15,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                return []
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return []
            data = resp.json()
            jobs = _parse_indeed_json(data)
            return [j for j in jobs if _TECH_KW_RE.search(j.title) and not _TITLE_BLOCK_RE.search(j.title)]
        except Exception:
            return []

    def _playwright_scrape(self, keyword: str) -> list[Job]:
        """Playwright fallback scraper for Indeed LK."""
        jobs: list[Job] = []
        seen: set[str] = set()
        pw = browser = page = None
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            try:
                browser = pw.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="en-US",
            )
            page = ctx.new_page()

            encoded_kw = requests.utils.quote(keyword)
            url = f"https://lk.indeed.com/jobs?q={encoded_kw}&l=Sri+Lanka"
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)

            current_url = page.url.lower()
            if "indeed.com/cmp" in current_url or "identify" in current_url:
                self.errors.append(f"indeed_lk: blocked on '{keyword}' (redirect)")
                return jobs

            html = page.content()
            if _is_blocked_html(html):
                self.errors.append(f"indeed_lk: CAPTCHA detected on '{keyword}' — Manual Action Required")
                return jobs

            # Extract job cards
            cards = page.locator("[class*='job_seen_beacon'], [class*='resultContent'], [data-jk]")
            count = cards.count()
            for i in range(min(count, _PER_TERM_LIMIT)):
                try:
                    card = cards.nth(i)
                    jk = card.get_attribute("data-jk") or ""
                    if not jk or jk in seen:
                        continue
                    seen.add(jk)

                    title_el = card.locator("h2 a span, [class*='jobTitle'] span").first
                    title = title_el.inner_text().strip() if title_el.count() else keyword.title()

                    if not _TECH_KW_RE.search(title) or _TITLE_BLOCK_RE.search(title):
                        continue

                    company_el = card.locator("[class*='companyName'], [data-testid='company-name']").first
                    company = company_el.inner_text().strip() if company_el.count() else "Indeed LK"

                    loc_el = card.locator("[class*='companyLocation'], [data-testid='text-location']").first
                    location = loc_el.inner_text().strip() if loc_el.count() else _LK_LOCATION
                    if "Sri Lanka" not in location and "Colombo" not in location:
                        location = f"{location}, Sri Lanka"

                    apply_url = f"https://lk.indeed.com/viewjob?jk={jk}"
                    jobs.append(Job(
                        source=self.name,
                        external_id=jk[:40],
                        company=company[:100],
                        title=title[:120],
                        location=location,
                        remote="remote" in location.lower(),
                        description=f"{title} at {company} in Sri Lanka via Indeed.",
                        apply_url=apply_url,
                    ))
                except Exception as exc:
                    self.errors.append(f"indeed_lk card: {str(exc)[:80]}")
                time.sleep(0.3)

        except Exception as exc:
            self.errors.append(f"indeed_lk playwright '{keyword}': {str(exc)[:100]}")
        finally:
            try:
                if browser:
                    browser.close()
                if pw:
                    pw.stop()
            except Exception:
                pass
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        for term in self.search_terms:
            if len(jobs) >= _TOTAL_LIMIT:
                break

            # Try JSON API first (fast, no browser)
            batch = self._try_json_api(term)
            if not batch:
                # Fall back to Playwright
                batch = self._playwright_scrape(term)

            for job in batch:
                if job.external_id not in seen:
                    seen.add(job.external_id)
                    jobs.append(job)

        return jobs
