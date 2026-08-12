from __future__ import annotations

from datetime import datetime

import requests

from .base import Job, JobSource
from .greenhouse import strip_html


class RemoteOKSource(JobSource):
    name = "remoteok"
    api_url = "https://remoteok.com/api"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        try:
            resp = requests.get(
                self.api_url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            self.errors.append(f"remoteok: {exc}")
            return []
        jobs: list[Job] = []
        for entry in data:
            if not isinstance(entry, dict) or entry.get("id") is None:
                continue
            date = entry.get("date") or ""
            posted_at = None
            try:
                posted_at = int(datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp() * 1000)
            except (ValueError, TypeError):
                pass
            jobs.append(
                Job(
                    source=self.name,
                    external_id=str(entry.get("id", "")),
                    company=entry.get("company") or "",
                    title=entry.get("position") or "",
                    location="Remote",
                    remote=True,
                    description=strip_html(entry.get("description") or ""),
                    apply_url=entry.get("url") or "",
                    posted_at=posted_at,
                )
            )
        return jobs