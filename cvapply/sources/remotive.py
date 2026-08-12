from __future__ import annotations

import requests

from .base import Job, JobSource


class RemotiveSource(JobSource):
    name = "remotive"
    api_url = "https://remotive.com/api/remote-jobs"

    def __init__(self, categories: list[str], timeout: int = 20) -> None:
        super().__init__()
        self.categories = [c.lower() for c in categories]
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        try:
            resp = requests.get(self.api_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self.errors.append(f"remotive: {exc}")
            return []
        jobs: list[Job] = []
        for j in resp.json().get("jobs", []):
            category = (j.get("category") or "").lower()
            if self.categories and category not in self.categories:
                continue
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(j.get("id", "")),
                    company=j.get("company_name") or "",
                    title=j.get("title") or "",
                    location=j.get("candidate_required_location") or "",
                    remote=True,
                    description=j.get("description") or "",
                    apply_url=j.get("url") or "",
                    posted_at=None,
                )
            )
        return jobs