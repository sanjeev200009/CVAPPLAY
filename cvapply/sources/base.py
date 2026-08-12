from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Job:
    source: str
    external_id: str
    company: str
    title: str
    location: str
    remote: bool
    description: str
    apply_url: str
    posted_at: int | None = None


class JobSource:
    name: str = "base"

    def __init__(self) -> None:
        self.errors: list[str] = []

    def fetch(self) -> list[Job]:
        raise NotImplementedError
