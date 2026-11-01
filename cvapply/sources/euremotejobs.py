"""
EuroRemoteJobs source — European and global remote tech jobs.
Parses the public RSS feed.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from .base import Job, JobSource
from .greenhouse import strip_html

_COMPANY_RE = re.compile(r'\bat\s+([A-Z][^\n(–—]{2,60})', re.IGNORECASE)
_CDATA_RE = re.compile(r'<!\[CDATA\[(.*?)\]\]>', re.DOTALL)


def _unwrap_cdata(text: str) -> str:
    m = _CDATA_RE.search(text or "")
    return m.group(1) if m else (text or "")


class EuroRemoteJobsSource(JobSource):
    name = "euremotejobs"
    RSS_URLS = [
        "https://euremotejobs.com/feed",
        "https://euremotejobs.com/category/engineering/feed",
    ]

    def __init__(self, timeout: int = 20) -> None:
        super().__init__()
        self.timeout = timeout

    def _parse_feed(self, rss_url: str) -> list[Job]:
        jobs: list[Job] = []
        try:
            resp = requests.get(
                rss_url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,text/xml"},
            )
            resp.raise_for_status()

            # Strip namespaces for simpler parsing
            content = re.sub(r' xmlns[^=]*="[^"]*"', '', resp.text)
            root = ET.fromstring(content.encode("utf-8"))
            channel = root.find("channel")
            if channel is None:
                channel = root  # Some feeds have items at root level

            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                guid_el = item.find("guid")

                raw_title = _unwrap_cdata((title_el.text or "") if title_el is not None else "").strip()
                link = _unwrap_cdata((link_el.text or "") if link_el is not None else "").strip()
                guid = _unwrap_cdata((guid_el.text or link) if guid_el is not None else link).strip()
                desc_raw = _unwrap_cdata((desc_el.text or "") if desc_el is not None else "")

                if not raw_title or not link:
                    continue

                company = "EuroRemoteJobs Company"
                title = raw_title
                cm = _COMPANY_RE.search(raw_title)
                if cm:
                    company = cm.group(1).strip().rstrip(" -–—")
                    title = raw_title[:cm.start()].strip().rstrip(" -–—at")
                if not title:
                    title = raw_title

                desc = strip_html(desc_raw)
                if not desc:
                    desc = f"{title} at {company} — remote position on EuroRemoteJobs."

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
            self.errors.append(f"euremotejobs ({rss_url}): {exc}")
        except ET.ParseError as exc:
            self.errors.append(f"euremotejobs XML parse: {exc}")
        except Exception as exc:
            self.errors.append(f"euremotejobs: unexpected {exc}")
        return jobs

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        for url in self.RSS_URLS:
            for job in self._parse_feed(url):
                if job.external_id not in seen:
                    seen.add(job.external_id)
                    jobs.append(job)
        return jobs
