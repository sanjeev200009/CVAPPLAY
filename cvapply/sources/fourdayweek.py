from __future__ import annotations

import hashlib
import time
import requests

from .base import Job, JobSource

class FourDayWeekSource(JobSource):
    """Fetches global tech & software engineering jobs from 4dayweek.io public REST API."""

    name = "4dayweek"
    API_URL = "https://4dayweek.io/api/jobs"

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
                self.errors.append(f"4DayWeek API HTTP {resp.status_code}")
                return jobs

            data = resp.json()
            items = data.get("jobs", []) if isinstance(data, dict) else data

            for item in items:
                title = item.get("title") or ""
                company_obj = item.get("company") or {}
                company = item.get("company_name") or company_obj.get("name") or "Tech Company"
                slug = item.get("slug") or ""
                url = f"https://4dayweek.io/remote-job/{slug}" if slug else "https://4dayweek.io/"

                arrangement = item.get("work_arrangement") or "remote"
                is_remote = arrangement.lower() in ("remote", "hybrid", "flexible")

                locations = item.get("locations") or []
                loc_name = locations[0].get("country") if locations and isinstance(locations[0], dict) else "Remote"

                stack = [s.get("name") for s in item.get("stack", []) if isinstance(s, dict) and s.get("name")]
                desc = f"Role: {title}\nCompany: {company}\nCategory: {item.get('category', 'Tech')}\nTech Stack: {', '.join(stack)}"

                if not title:
                    continue

                external_id = str(item.get("id") or hashlib.md5(slug.encode()).hexdigest()[:16])

                jobs.append(
                    Job(
                        external_id=external_id,
                        source=self.name,
                        title=title,
                        company=company,
                        location=loc_name,
                        apply_url=url,
                        description=desc,
                        remote=is_remote,
                        posted_at=int(time.time()),
                    )
                )
        except Exception as exc:
            self.errors.append(f"4DayWeek fetch error: {exc}")

        return jobs
