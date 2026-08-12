from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

from .base import Job, JobSource

_TAG_RE = re.compile(r"<[^>]+>")
_MULTISPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_TAG_RE = re.compile(r"<br\s*/?>|</(p|li|h[1-6]|div|tr)>", re.IGNORECASE)


def parse_timestamp_ms(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = _NEWLINE_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text)
    return text.strip()


class GreenhouseSource(JobSource):
    name = "greenhouse"
    api_base = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"

    def __init__(self, companies: list[str], timeout: int = 20) -> None:
        super().__init__()
        self.companies = companies
        self.timeout = timeout

    def _fetch_company(self, company: str) -> list[Job]:
        url = self.api_base.format(company=company)
        resp = requests.get(url, params={"content": "true"}, timeout=self.timeout)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        jobs: list[Job] = []
        for j in data.get("jobs", []):
            if j.get("internal"):
                continue
            loc = j.get("location") or {}
            loc_name = loc.get("name") or ""
            is_remote = bool(loc.get("remote")) or "remote" in loc_name.lower()
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(j.get("id", "")),
                    company=company,
                    title=j.get("title") or "",
                    location=loc_name,
                    remote=is_remote,
                    description=strip_html(j.get("content") or ""),
                    apply_url=j.get("absolute_url") or "",
                    posted_at=parse_timestamp_ms(j.get("updated_at")),
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
                    self.errors.append(f"greenhouse/{company}: {exc}")
                except Exception as exc:
                    self.errors.append(f"greenhouse/{company}: unexpected {exc}")
        return jobs
