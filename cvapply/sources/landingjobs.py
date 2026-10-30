from __future__ import annotations

import hashlib
import time
import requests

from .base import Job, JobSource

class LandingJobsSource(JobSource):
    """Fetches global tech jobs from Landing.jobs public API."""

    name = "landingjobs"
    API_URL = "https://landing.jobs/api/v1/jobs"

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
                self.errors.append(f"LandingJobs API HTTP {resp.status_code}")
                return jobs

            items = resp.json()
            if not isinstance(items, list):
                return jobs

            for item in items:
                title = item.get("title") or ""
                url = item.get("url") or ""
                desc = (item.get("role_description") or "") + "\n" + (item.get("main_requirements") or "")
                is_remote = bool(item.get("remote", False))
                locations = item.get("locations") or []
                loc_str = ", ".join(locations) if locations else ("Worldwide Remote" if is_remote else "Remote")

                # Derive company name from url or title if company_id is present
                company = f"Tech Partner ({locations[0] if locations else 'Remote'})"

                if not title or not url:
                    continue

                external_id = str(item.get("id") or hashlib.md5(url.encode()).hexdigest()[:16])

                jobs.append(
                    Job(
                        external_id=external_id,
                        source=self.name,
                        title=title,
                        company=company,
                        location=loc_str,
                        apply_url=url,
                        description=desc,
                        remote=is_remote,
                        posted_at=int(time.time()),
                    )
                )
        except Exception as exc:
            self.errors.append(f"LandingJobs fetch error: {exc}")

        return jobs
