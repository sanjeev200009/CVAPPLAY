from __future__ import annotations

import time
from typing import Any

from .convex_api import ConvexClient
from .sources.base import Job


def job_to_doc(job: Job, status: str, tier: str, now: int) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "source": job.source,
        "external_id": job.external_id,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "remote": job.remote,
        "location_tier": tier,
        "description": job.description,
        "apply_url": job.apply_url,
        "status": status,
        "created_at": now,
    }
    if job.posted_at is not None:
        doc["posted_at"] = job.posted_at
    return doc


def upsert_job(client: ConvexClient, job: Job, status: str, tier: str) -> bool:
    """Returns True if a new job was inserted (i.e. not seen before)."""
    result = client.mutation(
        "mutations:upsertJob",
        {"job": job_to_doc(job, status, tier, int(time.time() * 1000))},
    )
    return bool(result and result.get("created"))


def upsert_job_doc(client: ConvexClient, job: Job, status: str, tier: str) -> str | None:
    """Returns the Convex document ID (_id) of the inserted/existing job."""
    result = client.mutation(
        "mutations:upsertJob",
        {"job": job_to_doc(job, status, tier, int(time.time() * 1000))},
    )
    if result and isinstance(result, dict):
        return result.get("id")
    return None


def insert_log(client: ConvexClient, level: str, message: str, context: dict[str, Any] | None = None) -> None:
    args: dict[str, Any] = {
        "level": level,
        "message": message,
        "created_at": int(time.time() * 1000),
    }
    if context:
        args["context"] = context
    client.mutation("mutations:insertLog", args)