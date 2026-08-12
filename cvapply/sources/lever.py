from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .base import Job, JobSource


class LeverSource(JobSource):
    name = "lever"
    api_base = "https://api.lever.co/v0/postings/{company}"

    def __init__(self, companies: list[str], timeout: int = 20) -> None:
        super().__init__()
        self.companies = companies
        self.timeout = timeout

    def _fetch_company(self, company: str) -> list[Job]:
        url = self.api_base.format(company=company)
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        jobs: list[Job] = []
        for p in data:
            categories = p.get("categories") or {}
            loc = (categories.get("location") or "").strip()
            is_remote = "remote" in loc.lower() or "anywhere" in loc.lower()
            desc_parts = [
                (p.get("descriptionPlain") or "").strip(),
                (p.get("additionalPlain") or "").strip(),
            ]
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(p.get("id", "")),
                    company=company,
                    title=p.get("text") or "",
                    location=loc,
                    remote=is_remote,
                    description="\n\n".join(part for part in desc_parts if part),
                    apply_url=p.get("hostedUrl") or "",
                    posted_at=p.get("createdAt"),
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
                    self.errors.append(f"lever/{company}: {exc}")
                except Exception as exc:
                    self.errors.append(f"lever/{company}: unexpected {exc}")
        return jobs
