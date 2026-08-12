from __future__ import annotations

import requests

from .base import Job, JobSource


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    api_url = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        try:
            resp = requests.get(self.api_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self.errors.append(f"arbeitnow: {exc}")
            return []
        jobs: list[Job] = []
        for j in resp.json().get("data", []):
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(j.get("slug", "")),
                    company=j.get("company_name") or "",
                    title=j.get("title") or "",
                    location=j.get("location") or "",
                    remote=bool(j.get("remote")),
                    description=j.get("description") or "",
                    apply_url=j.get("url") or "",
                    posted_at=j.get("created_at"),
                )
            )
        return jobs