"""
Startup.jobs source — engineering RSS feed.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from .base import Job, JobSource
from .greenhouse import strip_html

_COMPANY_RE = re.compile(r'\bat\s+([A-Z][^\n(]{2,50})', re.IGNORECASE)


class StartupJobsSource(JobSource):
    name = "startup_jobs"
    RSS_URL = "https://startup.jobs/rss/engineering"

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

                raw_title = (title_el.text or "").strip() if title_el is not None else ""
                link = (link_el.text or "").strip() if link_el is not None else ""
                desc_html = (desc_el.text or "") if desc_el is not None else ""
                guid = (guid_el.text or link or raw_title).strip()

                if not raw_title or not link:
                    continue

                # "Software Engineer at CompanyName" pattern
                company = "Startup"
                cm = _COMPANY_RE.search(raw_title)
                if cm:
                    company = cm.group(1).strip()
                    title = raw_title[:cm.start()].strip().rstrip(" —-at").strip()
                else:
                    title = raw_title

                if not title:
                    title = raw_title

                desc = strip_html(desc_html)
                if not desc:
                    desc = f"{title} at {company} via Startup.jobs."

                location = "Remote"
                is_remote = True
                # Check for location hints in the description
                if re.search(r'\b(USA|US only|United States only|UK only|EU only|Europe only)\b', desc, re.IGNORECASE):
                    location = "Remote (restricted)"
                    is_remote = True

                jobs.append(Job(
                    source=self.name,
                    external_id=str(hash(guid) % (10**12))[:15],
                    company=company[:100],
                    title=title[:120],
                    location=location,
                    remote=is_remote,
                    description=desc[:5000],
                    apply_url=link,
                ))

        except requests.RequestException as exc:
            self.errors.append(f"startup_jobs: {exc}")
        except ET.ParseError as exc:
            self.errors.append(f"startup_jobs XML parse: {exc}")
        except Exception as exc:
            self.errors.append(f"startup_jobs: unexpected {exc}")
        return jobs
