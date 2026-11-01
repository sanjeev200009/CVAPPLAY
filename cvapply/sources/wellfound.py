"""
Wellfound (formerly AngelList Talent) job source.
Uses the public Next.js data blob embedded in the server-rendered HTML
to extract job listings without requiring authentication.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .base import Job, JobSource
from .greenhouse import strip_html

_SLUG_RE = re.compile(r'[^a-z0-9]+')
_NEXT_DATA_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL)

SEARCH_ROLES = [
    "software-engineer",
    "frontend-engineer",
    "backend-engineer",
    "full-stack-engineer",
    "ai-engineer",
]


def _slug_id(source: str, key: str) -> str:
    return hashlib.md5(f"{source}:{key}".encode()).hexdigest()[:20]


class WellfoundSource(JobSource):
    name = "wellfound"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, timeout: int = 25) -> None:
        super().__init__()
        self.timeout = timeout

    def _fetch_role(self, role: str) -> list[Job]:
        url = f"https://wellfound.com/role/r/{role}"
        jobs: list[Job] = []
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=self.timeout)
            if resp.status_code != 200:
                return jobs

            # Extract embedded Next.js JSON payload
            m = _NEXT_DATA_RE.search(resp.text)
            if not m:
                # Fallback: regex scrape job cards from HTML
                return self._scrape_html(resp.text, role)

            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                return jobs

            # Traverse the Next.js page props to find job listings
            job_listings = self._extract_listings(data)
            for item in job_listings[:20]:
                job = self._item_to_job(item)
                if job:
                    jobs.append(job)

        except requests.RequestException as exc:
            self.errors.append(f"wellfound/{role}: {exc}")
        except Exception as exc:
            self.errors.append(f"wellfound/{role}: unexpected {exc}")
        return jobs

    def _extract_listings(self, data: dict) -> list[dict]:
        """Recursively search for job listing arrays in the Next.js data blob."""
        candidates: list[dict] = []
        try:
            # Common path: props.pageProps.jobListings or .jobs
            page_props = (
                data.get("props", {}).get("pageProps", {})
            )
            for key in ("jobListings", "jobs", "startupRoles", "listings"):
                val = page_props.get(key)
                if isinstance(val, list) and val:
                    return val
            # Deeper search
            self._deep_find(data, candidates, depth=0)
        except Exception:
            pass
        return candidates

    def _deep_find(self, node: object, out: list, depth: int) -> None:
        if depth > 6 or len(out) >= 30:
            return
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and any(k in item for k in ("title", "jobTitle", "name")):
                    if any(k in item for k in ("startup", "company", "companyName", "id")):
                        out.append(item)
                        continue
                self._deep_find(item, out, depth + 1)
        elif isinstance(node, dict):
            for v in node.values():
                self._deep_find(v, out, depth + 1)

    def _item_to_job(self, item: dict) -> Job | None:
        try:
            title = (
                item.get("title") or item.get("jobTitle") or item.get("name") or ""
            ).strip()
            if not title:
                return None

            company_obj = item.get("startup") or item.get("company") or {}
            company = ""
            if isinstance(company_obj, dict):
                company = company_obj.get("name") or company_obj.get("companyName") or ""
            elif isinstance(company_obj, str):
                company = company_obj
            company = company.strip() or "Wellfound Startup"

            location_parts = []
            if item.get("remote"):
                location_parts.append("Remote")
            loc = item.get("locationNames") or item.get("location") or ""
            if isinstance(loc, list):
                location_parts.extend(loc)
            elif isinstance(loc, str) and loc:
                location_parts.append(loc)
            location = ", ".join(location_parts) or "Remote"
            is_remote = bool(item.get("remote")) or "remote" in location.lower()

            desc = strip_html(item.get("description") or item.get("jobDescription") or "")
            if not desc:
                desc = f"{title} at {company} — remote startup role."

            jid = str(item.get("id") or item.get("slug") or _slug_id("wellfound", f"{company}:{title}"))
            apply_url = (
                item.get("applyUrl") or item.get("url") or
                f"https://wellfound.com/jobs/{jid}"
            )

            return Job(
                source=self.name,
                external_id=jid[:40],
                company=company[:100],
                title=title[:120],
                location=location,
                remote=is_remote,
                description=desc[:5000],
                apply_url=apply_url,
            )
        except Exception:
            return None

    def _scrape_html(self, html: str, role: str) -> list[Job]:
        """Minimal HTML scrape fallback when Next.js blob is absent."""
        jobs: list[Job] = []
        # Extract job card text blocks
        cards = re.findall(r'<div[^>]*class="[^"]*job[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
        seen: set[str] = set()
        for card in cards[:15]:
            title_m = re.search(r'<h[123][^>]*>([^<]+)</h[123]>', card, re.IGNORECASE)
            if not title_m:
                continue
            title = title_m.group(1).strip()
            if not title or title in seen:
                continue
            seen.add(title)
            company_m = re.search(r'<a[^>]*>([^<]{3,60})</a>', card)
            company = company_m.group(1).strip() if company_m else "Wellfound Startup"
            jid = _slug_id("wellfound", f"{company}:{title}")
            jobs.append(Job(
                source=self.name,
                external_id=jid,
                company=company[:100],
                title=title[:120],
                location="Remote",
                remote=True,
                description=f"{title} at {company} on Wellfound. Remote startup role.",
                apply_url=f"https://wellfound.com/role/r/{role}",
            ))
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self._fetch_role, role): role for role in SEARCH_ROLES}
            for future in as_completed(futures):
                try:
                    for job in future.result():
                        if job.external_id not in seen:
                            seen.add(job.external_id)
                            jobs.append(job)
                except Exception as exc:
                    self.errors.append(f"wellfound thread: {exc}")
        return jobs
