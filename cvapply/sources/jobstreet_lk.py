"""
JobStreet Sri Lanka source.
Uses the same undocumented chalice-search API that JobStreet's frontend uses.
"""
from __future__ import annotations

import requests

from .base import Job, JobSource
from .greenhouse import strip_html, parse_timestamp_ms


class JobStreetLKSource(JobSource):
    name = "jobstreet_lk"
    api_url = "https://www.jobstreet.lk/api/chalice-search/v4/search"

    SEARCH_KEYWORDS = [
        "software engineer",
        "web developer",
        "python developer",
        "react developer",
        "junior developer",
    ]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, */*",
        "Referer": "https://www.jobstreet.lk/",
        "Origin": "https://www.jobstreet.lk",
    }

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def _fetch_keyword(self, keyword: str) -> list[Job]:
        jobs: list[Job] = []
        try:
            resp = requests.get(
                self.api_url,
                params={
                    "siteKey": "LK-Main",
                    "sourcesystem": "houston",
                    "keywords": keyword,
                    "pageSize": 30,
                    "pageNum": 1,
                },
                headers=self.HEADERS,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                # Silently skip — JobStreet may block non-browser requests
                return jobs
            data = resp.json()

            job_list = data.get("data", {}).get("jobs", {}).get("jobs", [])
            if not job_list:
                job_list = data.get("jobs", [])

            for j in job_list:
                title = (j.get("jobTitle") or j.get("title") or "").strip()
                company_obj = j.get("advertiser") or j.get("company") or {}
                company = ""
                if isinstance(company_obj, dict):
                    company = (company_obj.get("description") or company_obj.get("name") or "").strip()
                company = company or "JobStreet Sri Lanka"

                location_parts = []
                for loc_field in ("suburb", "location", "area", "locationLabel"):
                    v = j.get(loc_field) or ""
                    if isinstance(v, dict):
                        v = v.get("label") or ""
                    if v:
                        location_parts.append(str(v).strip())
                location = ", ".join(location_parts) or "Sri Lanka"
                if "Sri Lanka" not in location:
                    location = f"{location}, Sri Lanka"

                is_remote = "remote" in location.lower() or bool(j.get("workType") == "Remote")
                desc = strip_html(j.get("teaser") or j.get("abstract") or j.get("description") or "")
                if not desc:
                    desc = f"{title} at {company} in Sri Lanka."

                job_url = j.get("jobUrl") or j.get("url") or ""
                if not job_url:
                    job_id = j.get("id") or j.get("jobId") or ""
                    job_url = f"https://www.jobstreet.lk/job/{job_id}" if job_id else "https://www.jobstreet.lk"

                posted_at = parse_timestamp_ms(j.get("listingDate") or j.get("postedDate"))
                external_id = str(j.get("id") or j.get("jobId") or f"{company}:{title}")[:40]

                jobs.append(Job(
                    source=self.name,
                    external_id=external_id,
                    company=company[:100],
                    title=title[:120],
                    location=location,
                    remote=is_remote,
                    description=desc[:5000],
                    apply_url=job_url,
                    posted_at=posted_at,
                ))
        except requests.RequestException as exc:
            self.errors.append(f"jobstreet_lk/{keyword}: {exc}")
        except Exception as exc:
            self.errors.append(f"jobstreet_lk/{keyword}: unexpected {exc}")
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        for kw in self.SEARCH_KEYWORDS:
            for job in self._fetch_keyword(kw):
                if job.external_id not in seen:
                    seen.add(job.external_id)
                    jobs.append(job)
        return jobs
