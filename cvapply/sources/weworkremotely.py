from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from .base import Job, JobSource
from .greenhouse import parse_timestamp_ms


class WeWorkRemotelySource(JobSource):
    name = "weworkremotely"
    rss_url = "https://weworkremotely.com/remote-jobs.rss"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        try:
            resp = requests.get(
                self.rss_url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            self.errors.append(f"weworkremotely: {exc}")
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            self.errors.append(f"weworkremotely: parse error {exc}")
            return []
        jobs: list[Job] = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            company = item.findtext("company") or ""
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""
            pubdate = item.findtext("pubDate") or ""
            jobs.append(
                Job(
                    source=self.name,
                    external_id=link.split("/")[-2] if "/" in link else link,
                    company=company,
                    title=title,
                    location="Remote",
                    remote=True,
                    description=desc,
                    apply_url=link,
                    posted_at=parse_timestamp_ms(pubdate),
                )
            )
        return jobs