from __future__ import annotations

import hashlib
import time
import requests

from .base import Job, JobSource

class JobicySource(JobSource):
    """Fetches remote software engineering & developer jobs from Jobicy public API."""

    name = "jobicy"
    API_URL = "https://jobicy.com/api/v2/remote-jobs?count=50"

    def fetch(self) -> list[Job]:
        self.errors.clear()
        jobs: list[Job] = []
        try:
            resp = requests.get(
                self.API_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=20,
            )
            if resp.status_code != 200:
                self.errors.append(f"Jobicy API HTTP {resp.status_code}")
                return jobs

            data = resp.json()
            items = data.get("jobs", [])
            for item in items:
                title = item.get("jobTitle") or ""
                company = item.get("companyName") or ""
                url = item.get("url") or ""
                desc = item.get("jobDescription") or item.get("jobExcerpt") or ""
                geo = item.get("jobGeo") or "Worldwide Remote"

                if not title or not url:
                    continue

                external_id = str(item.get("id") or hashlib.md5(url.encode()).hexdigest()[:16])

                jobs.append(
                    Job(
                        external_id=external_id,
                        source=self.name,
                        title=title,
                        company=company,
                        location=geo,
                        apply_url=url,
                        description=desc,
                        remote=True,
                        posted_at=int(time.time()),
                    )
                )
        except Exception as exc:
            self.errors.append(f"Jobicy fetch error: {exc}")

        return jobs
