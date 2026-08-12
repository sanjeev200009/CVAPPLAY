from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .base import Job, JobSource
from .greenhouse import parse_timestamp_ms


class AshbySource(JobSource):
    name = "ashby"
    api_base = "https://api.ashbyhq.com/posting-api/job-board/{company}"

    def __init__(self, companies: list[str], timeout: int = 20) -> None:
        super().__init__()
        self.companies = companies
        self.timeout = timeout

    def _fetch_company(self, company: str) -> list[Job]:
        url = self.api_base.format(company=company)
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs: list[Job] = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            loc = j.get("location") or ""
            is_remote = bool(j.get("isRemote"))
            secondaries = j.get("secondaryLocations") or []
            if secondaries:
                secondary_names = [
                    s.get("location") if isinstance(s, dict) else str(s)
                    for s in secondaries
                ]
                loc = f"{loc} ({', '.join(str(n) for n in secondary_names)})"
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(j.get("id", "")),
                    company=company,
                    title=j.get("title") or "",
                    location=loc,
                    remote=is_remote,
                    description=(j.get("descriptionPlain") or "").strip(),
                    apply_url=j.get("applyUrl") or j.get("jobUrl") or "",
                    posted_at=parse_timestamp_ms(j.get("publishedAt")),
                )
            )
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self._fetch_company, c): c for c in self.companies}
            for future in as_completed(futures):
                company = futures[future]
                try:
                    jobs.extend(future.result())
                except requests.RequestException as exc:
                    self.errors.append(f"ashby/{company}: {exc}")
                except Exception as exc:
                    self.errors.append(f"ashby/{company}: unexpected {exc}")
        return jobs