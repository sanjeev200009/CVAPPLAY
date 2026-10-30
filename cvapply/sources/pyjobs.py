"""
PyJobs (pyjobs.com) source — Python-specific job board.
Uses the public REST API.
"""
from __future__ import annotations

import requests

from .base import Job, JobSource
from .greenhouse import parse_timestamp_ms, strip_html


class PyJobsSource(JobSource):
    name = "pyjobs"
    api_url = "https://www.pyjobs.com/api/job/list/"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        try:
            resp = requests.get(
                self.api_url,
                params={"seniority": "junior"},
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            job_list = data if isinstance(data, list) else data.get("jobs", data.get("results", []))
            for j in job_list:
                title = (j.get("title") or j.get("job_title") or "").strip()
                if not title:
                    continue

                company = (j.get("company_name") or j.get("company") or "PyJobs Company").strip()
                location = j.get("location") or j.get("city") or "Remote"
                is_remote = bool(j.get("remote")) or "remote" in (location or "").lower()

                desc = strip_html(j.get("description") or j.get("requirements") or "")
                if not desc:
                    desc = f"{title} at {company} — Python role."

                apply_url = j.get("url") or j.get("apply_url") or j.get("link") or ""
                if not apply_url and j.get("pk"):
                    apply_url = f"https://www.pyjobs.com/job/{j['pk']}"

                posted_at = parse_timestamp_ms(j.get("posted_date") or j.get("created_at"))
                external_id = str(j.get("pk") or j.get("id") or f"{company}:{title}")[:40]

                jobs.append(Job(
                    source=self.name,
                    external_id=external_id,
                    company=company[:100],
                    title=title[:120],
                    location=location,
                    remote=is_remote,
                    description=desc[:5000],
                    apply_url=apply_url,
                    posted_at=posted_at,
                ))

        except requests.RequestException as exc:
            self.errors.append(f"pyjobs: {exc}")
        except Exception as exc:
            self.errors.append(f"pyjobs: unexpected {exc}")
        return jobs
