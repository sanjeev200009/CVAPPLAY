"""
Y Combinator — Work at a Startup job board source.
Uses the public JSON feed from workatastartup.com.
"""
from __future__ import annotations

import requests

from .base import Job, JobSource
from .greenhouse import strip_html


class YCJobsSource(JobSource):
    name = "ycjobs"
    # Public JSON endpoint used by the workatastartup.com frontend
    api_url = "https://www.workatastartup.com/jobs.json"

    def __init__(self, timeout: int = 25) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        try:
            resp = requests.get(
                self.api_url,
                params={"role": "eng", "remote": "yes", "openToAdverse": "false"},
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.workatastartup.com/jobs",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Response may be {"jobs": [...]} or a list directly
            raw_jobs = data.get("jobs") if isinstance(data, dict) else data
            if not isinstance(raw_jobs, list):
                self.errors.append("ycjobs: unexpected response structure")
                return jobs

            for j in raw_jobs:
                title = (j.get("title") or "").strip()
                if not title:
                    continue

                company_name = (
                    j.get("company_name") or
                    (j.get("company") or {}).get("name") or
                    "YC Startup"
                ).strip()

                location = j.get("location") or "Remote"
                is_remote = "remote" in location.lower() or bool(j.get("remote"))

                desc = strip_html(j.get("description") or j.get("body") or "")
                if not desc:
                    desc = f"{title} at {company_name} — YC-backed startup."

                job_url = j.get("url") or j.get("apply_url") or ""
                if not job_url:
                    jid = j.get("id") or j.get("slug") or ""
                    job_url = f"https://www.workatastartup.com/jobs/{jid}" if jid else "https://www.workatastartup.com/jobs"

                external_id = str(j.get("id") or j.get("slug") or f"{company_name}:{title}")[:40]

                jobs.append(Job(
                    source=self.name,
                    external_id=external_id,
                    company=company_name[:100],
                    title=title[:120],
                    location=location,
                    remote=is_remote,
                    description=desc[:5000],
                    apply_url=job_url,
                ))

        except requests.RequestException as exc:
            self.errors.append(f"ycjobs: {exc}")
        except Exception as exc:
            self.errors.append(f"ycjobs: unexpected {exc}")
        return jobs
