"""
Jobgether source — global remote-first job board.
Fetches from the public API / public search pages.
"""
from __future__ import annotations

import re
import requests

from .base import Job, JobSource
from .greenhouse import strip_html

_TAG_RE = re.compile(r"<[^>]+>")


class JobgetherSource(JobSource):
    name = "jobgether"
    # Jobgether public offers feed
    api_url = "https://jobgether.com/api/offers"

    def __init__(self, timeout: int = 20, pages: int = 3) -> None:
        super().__init__()
        self.timeout = timeout
        self.pages = pages

    def _fetch_page(self, page: int) -> list[Job]:
        resp = requests.get(
            self.api_url,
            params={"remote": "true", "page": page, "per_page": 50},
            timeout=self.timeout,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://jobgether.com/",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data if isinstance(data, list) else data.get("offers", data.get("jobs", data.get("data", [])))
        jobs: list[Job] = []
        for j in raw:
            title = (j.get("title") or j.get("name") or "").strip()
            if not title:
                continue

            company_obj = j.get("company") or j.get("employer") or {}
            if isinstance(company_obj, dict):
                company = (company_obj.get("name") or "").strip()
            else:
                company = str(company_obj).strip()
            company = company or "Jobgether Company"

            location = j.get("location") or j.get("country") or "Remote"
            is_remote = bool(j.get("remote")) or "remote" in str(location).lower()

            desc = strip_html(j.get("description") or j.get("content") or "")
            if not desc:
                desc = f"{title} at {company} — remote position on Jobgether."

            apply_url = j.get("url") or j.get("apply_url") or j.get("link") or "https://jobgether.com"
            external_id = str(j.get("id") or j.get("slug") or f"{company}:{title}")[:40]

            jobs.append(Job(
                source=self.name,
                external_id=external_id,
                company=company[:100],
                title=title[:120],
                location=str(location),
                remote=is_remote,
                description=desc[:5000],
                apply_url=apply_url,
            ))
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for page in range(1, self.pages + 1):
            try:
                batch = self._fetch_page(page)
                jobs.extend(batch)
                if len(batch) < 20:
                    break
            except requests.RequestException as exc:
                self.errors.append(f"jobgether page {page}: {exc}")
                break
            except Exception as exc:
                self.errors.append(f"jobgether page {page}: unexpected {exc}")
                break
        return jobs
