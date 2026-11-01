"""
NoDesk source — remote-only tech job board.
Parses the public RSS feed.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from .base import Job, JobSource
from .greenhouse import strip_html

_COMPANY_RE = re.compile(r'\bat\s+([A-Z][^\n(–—]{2,60})', re.IGNORECASE)
_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class NoDeskSource(JobSource):
    name = "nodesk"
    RSS_URL = "https://nodesk.co/remote-jobs/rss.xml"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        try:
            resp = requests.get(
                self.RSS_URL,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,text/xml"},
            )
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is None:
                return jobs

            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                guid_el = item.find("guid")
                content_el = item.find("content:encoded", _NS)

                raw_title = (title_el.text or "").strip() if title_el is not None else ""
                link = (link_el.text or "").strip() if link_el is not None else ""
                guid = (guid_el.text or link).strip() if guid_el is not None else link

                desc_raw = ""
                if content_el is not None and content_el.text:
                    desc_raw = content_el.text
                elif desc_el is not None and desc_el.text:
                    desc_raw = desc_el.text

                if not raw_title or not link:
                    continue

                company = "NoDesk Company"
                title = raw_title
                cm = _COMPANY_RE.search(raw_title)
                if cm:
                    company = cm.group(1).strip().rstrip(" -–—")
                    title = raw_title[:cm.start()].strip().rstrip(" -–—at")

                if not title:
                    title = raw_title

                desc = strip_html(desc_raw)
                if not desc:
                    desc = f"{title} at {company} — remote role on NoDesk."

                jobs.append(Job(
                    source=self.name,
                    external_id=str(hash(guid) % (10**12))[:15],
                    company=company[:100],
                    title=title[:120],
                    location="Remote",
                    remote=True,
                    description=desc[:5000],
                    apply_url=link,
                ))

        except requests.RequestException as exc:
            self.errors.append(f"nodesk: {exc}")
        except ET.ParseError as exc:
            self.errors.append(f"nodesk XML parse: {exc}")
        except Exception as exc:
            self.errors.append(f"nodesk: unexpected {exc}")
        return jobs
