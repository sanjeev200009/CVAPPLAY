"""
GetOnBoard (getonbrd.com) job source.
Uses the public REST API — no authentication required.
"""
from __future__ import annotations

import requests

from .base import Job, JobSource
from .greenhouse import parse_timestamp_ms, strip_html


class GetOnBoardSource(JobSource):
    name = "getonboard"
    api_url = "https://www.getonbrd.com/api/v0/jobs"

    def __init__(self, timeout: int = 20, pages: int = 4) -> None:
        super().__init__()
        self.timeout = timeout
        self.pages = pages

    def _fetch_page(self, page: int) -> list[Job]:
        resp = requests.get(
            self.api_url,
            params={"per_page": 100, "page": page, "remote": "true"},
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        resp.raise_for_status()
        jobs: list[Job] = []
        for j in resp.json().get("data", []):
            attrs = j.get("attributes", {})
            title = (attrs.get("title") or "").strip()
            company_data = attrs.get("company") or {}
            company = ""
            if isinstance(company_data, dict):
                company = company_data.get("name") or ""
            company = company.strip() or "GetOnBoard Company"

            location = attrs.get("country") or attrs.get("location") or "Remote"
            is_remote = bool(attrs.get("remote_modality")) or "remote" in location.lower()

            desc = strip_html(attrs.get("description") or attrs.get("functions") or "")
            if not desc:
                desc = f"{title} at {company}."

            apply_url = attrs.get("url") or attrs.get("apply_url") or f"https://www.getonbrd.com/jobs/{j.get('id', '')}"
            posted_at = parse_timestamp_ms(attrs.get("published_at"))

            jobs.append(Job(
                source=self.name,
                external_id=str(j.get("id", ""))[:40],
                company=company[:100],
                title=title[:120],
                location=location,
                remote=is_remote,
                description=desc[:5000],
                apply_url=apply_url,
                posted_at=posted_at,
            ))
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for page in range(1, self.pages + 1):
            try:
                batch = self._fetch_page(page)
                jobs.extend(batch)
                if len(batch) < 50:
                    break  # No more pages
            except requests.RequestException as exc:
                self.errors.append(f"getonboard page {page}: {exc}")
                break
            except Exception as exc:
                self.errors.append(f"getonboard page {page}: unexpected {exc}")
                break
        return jobs
