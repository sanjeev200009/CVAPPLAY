from __future__ import annotations

import requests

from .base import Job, JobSource
from .greenhouse import parse_timestamp_ms


class HimalayasSource(JobSource):
    name = "himalayas"
    api_url = "https://himalayas.app/jobs/api"

    def __init__(self, timeout: int = 20, pages: int = 8) -> None:
        super().__init__()
        self.timeout = timeout
        self.pages = pages

    def _fetch_page(self, offset: int) -> list[Job]:
        resp = requests.get(
            self.api_url,
            params={"limit": 100, "offset": offset},
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        jobs: list[Job] = []
        for j in resp.json().get("jobs", []):
            restrictions = j.get("locationRestrictions") or ""
            if isinstance(restrictions, list):
                restrictions = ", ".join(str(x) for x in restrictions)
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(j.get("guid", "")),
                    company=j.get("companyName") or "",
                    title=j.get("title") or "",
                    location=restrictions or "Remote",
                    remote=True,
                    description=j.get("description") or "",
                    apply_url=j.get("applicationLink") or "",
                    posted_at=parse_timestamp_ms(j.get("pubDate")),
                )
            )
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for page in range(self.pages):
            try:
                jobs.extend(self._fetch_page(page * 100))
            except requests.RequestException as exc:
                self.errors.append(f"himalayas page {page}: {exc}")
                break
        return jobs