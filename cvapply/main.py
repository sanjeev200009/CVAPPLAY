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
from .validator import validate_job


def run_scoring(convex: ConvexClient) -> tuple[int, list[tuple[int, str]], list[str], dict[str, int]]:
    """Score jobs with status=new and no match_score yet.
    Returns (above_threshold, top_summary, errors, tier_counts).
    """
    jobs = convex.query("queries:pendingScoring", {"limit": 60}) or []
    if not jobs:
        return 0, [], [], {}
    cv_text = load_cv()
    llm = OpenRouterClient()
    lock = threading.Lock()
    results: list[tuple[int, str, str, str]] = []  # (score, tier, job_id, label)
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
                    "match_tier": data.get("match_tier", "C"),
                    "match_reason": data.get("reason", ""),
                    "salary": data.get("salary", "Not specified"),
                    "summary": data.get("summary", ""),
                },
            )

            with lock:
                results.append((
                    data["score"],
                    data.get("match_tier", "C"),
                    job["_id"],
                    f"{job.get('company', '')} — {job.get('title', '')}",
                ))
        except Exception as exc:
            with lock:
                errors.append(f"score {job.get('company')}/{job.get('title')}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_score, job) for job in jobs]
        for future in as_completed(futures):
            future.result()

    above = sum(1 for r in results if r[0] >= settings.match_threshold)
    top = sorted(results, key=lambda r: -r[0])[:3]
    summary = [(score, label) for score, _tier, _jid, label in top]

    tier_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for _, tier, _, _ in results:
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return above, summary, errors, tier_counts


def run_pipeline(
    dry_run: bool = False, score: bool = True, local_only: bool = False
) -> dict[str, int | dict]:
    started = time.time()
    convex = ConvexClient()
    telegram = TelegramClient()
    sources = build_sources(local_only=local_only)

    counts: dict[str, int | dict] = {
        "fetched": 0, "new": 0, "duplicates": 0,
        "filtered": 0, "invalid": 0, "errors": 0,
    }
    tier_counts: dict[str, int] = {}
    errors: list[str] = []
    kept_examples: list[str] = []
    example_lock = threading.Lock()
    kept_jobs: list[Job] = []
    source_breakdown: dict[str, int] = {}

    for source in sources:
        jobs = source.fetch()
        errors.extend(source.errors)
        counts["fetched"] = int(counts["fetched"]) + len(jobs)
        source_breakdown[source.name] = source_breakdown.get(source.name, 0) + len(jobs)

        for job in jobs:
            # ── Validation layer (scam / stale / suspicious) ──
            is_valid, invalid_reason = validate_job(job)
            if not is_valid:
                counts["invalid"] = int(counts["invalid"]) + 1
                continue

            # ── Location / title / experience filter ──
            keep, reason, tier = filter_job(job)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            if not keep:
                counts["filtered"] = int(counts["filtered"]) + 1
                continue
            kept_jobs.append(job)

    counts["source_breakdown"] = source_breakdown  # type: ignore[assignment]

    if dry_run:
        counts["new"] = len(kept_jobs)
        print(
            "dry run: fetched=%d invalid=%d filtered=%d kept=%d"
            % (counts["fetched"], counts["invalid"], counts["filtered"], counts["new"])
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
                counts["errors"] = int(counts["errors"]) + 1
                errors.append(result)
                continue
            if result:
                counts["new"] = int(counts["new"]) + 1
            else:
                counts["duplicates"] = int(counts["duplicates"]) + 1
            with example_lock:
                kept_examples.append(f"• {job.company} — {job.title} ({job.location})")

    elapsed = time.time() - started

    scored_above = 0
    score_summary: list[tuple[int, str]] = []
    score_tier_counts: dict[str, int] = {}
    if score and not dry_run:
        try:
            scored_above, score_summary, score_errors, score_tier_counts = run_scoring(convex)
            errors.extend(score_errors)
        except Exception as exc:
            print(f"[scoring] failed: {exc}")

    counts["tier_a"] = score_tier_counts.get("A", 0)
    counts["tier_b"] = score_tier_counts.get("B", 0)
    counts["tier_c"] = score_tier_counts.get("C", 0)

    try:
        for err in errors[:50]:
            insert_log(convex, "warn", err, {"stage": "sourcing"})
        if errors:
            insert_log(convex, "warn", f"{len(errors)} source errors total")
        insert_log(
            convex,
            "info",
            "pipeline_run",
            {"counts": {k: v for k, v in counts.items() if k != "source_breakdown"}},
        )
    except Exception as exc:
        print(f"[log] failed to write logs: {exc}")

    summary_lines = [
        "🤖 CV Apply — pipeline run (🇱🇰 Sri Lanka focus)",
        "",
        f"Fetched: {counts['fetched']}",
        f"Invalid/scam dropped: {counts['invalid']}",
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
        f"Match tiers (scored this run):",
        f"  • Tier A (≥75): {score_tier_counts.get('A', 0)}",
        f"  • Tier B (50-74): {score_tier_counts.get('B', 0)}",
        f"  • Tier C (<50): {score_tier_counts.get('C', 0)}",
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
    parser.add_argument("--telegram-listen", action="store_true", help="run Telegram instant job application listener")
    parser.add_argument("--submit", action="store_true", help="submit real emails when using telegram-listen")
    args = parser.parse_args()

    if args.telegram_listen:
        from .telegram_listener import TelegramListener
        listener = TelegramListener(submit=args.submit)
        listener.listen_loop()
    else:
        run_pipeline(dry_run=args.dry_run, score=not args.no_score)