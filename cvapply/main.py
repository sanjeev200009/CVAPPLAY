from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .config import settings
from .convex_api import ConvexClient
from .cv import load_cv
from .filters import filter_job, location_tier
from .llm import OpenRouterClient
from .sources.base import Job
from .sources.registry import build_sources
from .store import insert_log, upsert_job
from .telegram import TelegramClient


def run_scoring(convex: ConvexClient) -> tuple[int, list[tuple[int, str]], list[str]]:
    """Score jobs with status=new and no match_score yet."""
    jobs = convex.query("queries:pendingScoring", {"limit": 60}) or []
    if not jobs:
        return 0, [], []
    cv_text = load_cv()
    llm = OpenRouterClient()
    lock = threading.Lock()
    results: list[tuple[int, int, str]] = []
    errors: list[str] = []

    def _score(job: dict) -> None:
        try:
            time.sleep(random.uniform(0.2, 0.8))
            data = llm.score_job(
                job.get("title", ""), job.get("description", ""), cv_text
            )
            convex.mutation(
                "mutations:updateJob",
                {
                    "job_id": job["_id"],
                    "status": "scored",
                    "match_score": data["score"],
                    "match_reason": data.get("reason", ""),
                    "salary": data.get("salary", "Not specified"),
                    "summary": data.get("summary", ""),
                },
            )

            with lock:
                results.append((data["score"], job["_id"], job.get("company", ""), job.get("title", "")))
        except Exception as exc:
            with lock:
                errors.append(f"score {job.get('company')}/{job.get('title')}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_score, job) for job in jobs]
        for future in as_completed(futures):
            future.result()

    above = sum(1 for r in results if r[0] >= settings.match_threshold)
    top = sorted(results, key=lambda r: -r[0])[:3]
    summary = [
        (score, f"{company} — {title}")
        for score, _job_id, company, title in top
    ]
    return above, summary, errors


def run_pipeline(dry_run: bool = False, score: bool = True) -> dict[str, int]:
    started = time.time()
    convex = ConvexClient()
    telegram = TelegramClient()
    sources = build_sources()

    counts = {"fetched": 0, "new": 0, "duplicates": 0, "filtered": 0, "errors": 0}
    tier_counts: dict[str, int] = {}
    errors: list[str] = []
    kept_examples: list[str] = []
    example_lock = threading.Lock()
    kept_jobs: list[Job] = []

    for source in sources:
        jobs = source.fetch()
        errors.extend(source.errors)
        counts["fetched"] += len(jobs)
        for job in jobs:
            keep, reason, tier = filter_job(job)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            if not keep:
                counts["filtered"] += 1
                continue
            kept_jobs.append(job)

    if dry_run:
        counts["new"] = len(kept_jobs)
        print(
            "dry run: fetched=%d filtered=%d kept=%d"
            % (counts["fetched"], counts["filtered"], counts["new"])
        )
        for job in kept_jobs[:20]:
            print(f"  • {job.company} — {job.title} ({job.location})")
        if errors:
            print("source errors:")
            for err in errors[:20]:
                print(f"  {err}")
        return counts

    def _upsert(job: Job) -> tuple[Job, bool | None]:
        try:
            created = upsert_job(convex, job, status="new", tier=location_tier(job.location, job.remote))
            return job, created
        except Exception as exc:
            return job, f"upsert {job.source}/{job.external_id}: {exc}"

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(_upsert, job) for job in kept_jobs]
        for future in as_completed(futures):
            job, result = future.result()
            if isinstance(result, str):
                counts["errors"] += 1
                errors.append(result)
                continue
            if result:
                counts["new"] += 1
            else:
                counts["duplicates"] += 1
            with example_lock:
                kept_examples.append(f"• {job.company} — {job.title} ({job.location})")

    elapsed = time.time() - started

    scored_above = 0
    score_summary: list[tuple[int, str]] = []
    if score and not dry_run:
        try:
            scored_above, score_summary, score_errors = run_scoring(convex)
            errors.extend(score_errors)
        except Exception as exc:
            print(f"[scoring] failed: {exc}")

    try:
        for err in errors[:50]:
            insert_log(convex, "warn", err, {"stage": "sourcing"})
        if errors:
            insert_log(convex, "warn", f"{len(errors)} source errors total")
        insert_log(
            convex,
            "info",
            "pipeline_run",
            {"counts": counts},
        )
    except Exception as exc:
        print(f"[log] failed to write logs: {exc}")

    summary_lines = [
        "🤖 CV Apply — pipeline run (🇱🇰 Sri Lanka focus)",
        "",
        f"Fetched: {counts['fetched']}",
        f"Filtered out: {counts['filtered']}",
        f"New candidates: {counts['new']}",
        f"Already known: {counts['duplicates']}",
        f"Source errors: {len(errors)}",
        f"Elapsed: {elapsed:.0f}s",
        "",
        "Location tiers:",
        f"  • Sri Lanka: {tier_counts.get('sri_lanka', 0)}",
        f"  • Worldwide remote: {tier_counts.get('worldwide', 0)}",
        f"  • Region-restricted (dropped): {tier_counts.get('restricted_remote', 0)}",
        f"  • Onsite (dropped): {tier_counts.get('onsite', 0)}",
        "",
        f"LLM scoring: {scored_above} above threshold {settings.match_threshold}",
    ]
    for score_val, label in score_summary[:3]:
        summary_lines.append(f"  ⭐ {score_val} — {label}")
    summary_lines.append("")
    summary_lines.append("Sample matches:")
    summary_lines.extend(kept_examples[:15])
    if not kept_examples:
        summary_lines.append("(none)")
    summary = "\n".join(summary_lines)
    try:
        telegram.send_message(summary)
    except Exception as exc:
        print(f"[telegram] failed: {exc}")
    print(summary)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CV Apply pipeline")
    parser.add_argument("--dry-run", action="store_true", help="fetch + filter but skip Convex/Telegram")
    parser.add_argument("--no-score", action="store_true", help="skip LLM scoring step")
    args = parser.parse_args()
    run_pipeline(dry_run=args.dry_run, score=not args.no_score)