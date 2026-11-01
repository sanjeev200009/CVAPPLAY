from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .apply import run_apply
from .config import settings
from .convex_api import ConvexClient
from .main import run_pipeline
from .reporter import build_daily_report, format_telegram_report, store_daily_report
from .telegram import TelegramClient


def _online() -> bool:
    """True if DNS resolves. Everything here needs the network, so a cycle run
    offline just burns minutes producing hundreds of identical errors."""
    import socket
    for host in ("api.telegram.org", "www.google.com"):
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            continue
    return False


_cycle_count = 0


def run_daemon_cycle(submit: bool, app_batch_limit: int) -> None:
    global _cycle_count
    _cycle_count += 1
    now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    if not _online():
        print(f"[{now_str}] Offline (DNS unreachable) - skipping cycle.")
        return
    print(f"\n{'='*60}")
    print(f"🚀 Starting Auto-Apply Daemon Cycle: {now_str}")
    print(f"{'='*60}")

    convex = ConvexClient()
    telegram = TelegramClient()
    telegram.send_message(f"🔄 Starting CV Apply cycle ({now_str})...")

    pipeline_errors: list[str] = []
    pipeline_counts: dict = {}

    # Step 1: Sourcing & LLM Scoring
    print("\n[Stage 1/3] Sourcing new jobs & scoring...")
    try:
        # Global boards are saturated (8,800 fetched for ~2 new) and cost
        # ~450s before scoring starts. Sweep them occasionally; check the Sri
        # Lankan boards every cycle so a Colombo job is seen within minutes.
        global_sweep = _cycle_count % settings.global_sweep_every == 0
        if not global_sweep:
            print("  (Sri Lankan sources only - global sweep every "
                  f"{settings.global_sweep_every} cycles)")
        pipeline_counts = run_pipeline(
            dry_run=False, score=True, local_only=not global_sweep
        )
        print(
            f"Sourcing completed: {pipeline_counts.get('fetched', 0)} fetched, "
            f"{pipeline_counts.get('new', 0)} new candidates, "
            f"{pipeline_counts.get('invalid', 0)} invalid/scam dropped."
        )
    except Exception as exc:
        print(f"Sourcing error: {exc}")
        pipeline_errors.append(str(exc))
        telegram.send_message(f"⚠️ Sourcing pipeline warning: {exc}")

    # Step 2: Auto-Apply to top scoring candidates
    print(f"\n[Stage 2/3] Auto-applying to scored jobs (submit={submit}, batch_limit={app_batch_limit})...")
    apply_stats: dict = {
        "submitted": 0, "manual": 0, "failed": 0,
        "avg_score": 0.0, "best_opportunities": [], "new_companies": [], "errors": [],
    }
    try:
        apply_stats = run_apply(submit=submit, limit=app_batch_limit, job_id=None, headed=False)
        print(
            f"Application run completed: "
            f"submitted={apply_stats.get('submitted', 0)} "
            f"manual={apply_stats.get('manual', 0)} "
            f"failed={apply_stats.get('failed', 0)}"
        )
    except Exception as exc:
        print(f"Apply error: {exc}")
        apply_stats["errors"].append(str(exc))
        telegram.send_message(f"⚠️ Application run error: {exc}")

    # Step 3: Check Gmail Inbox for recruiter replies and ping Telegram
    print("\n[Stage 3/3] Checking Gmail Inbox for recruiter replies...")
    from .inbox_tracker import check_inbox
    try:
        replies_found = check_inbox()
        print(f"Inbox check completed: {replies_found} recruiter replies discovered.")
    except Exception as exc:
        print(f"Inbox check error: {exc}")

    # Learn from bounce notices so dead addresses are never retried.
    try:
        from .bounces import scan_bounces

        scan_bounces()
    except Exception as exc:
        print(f"Bounce scan error: {exc}")

    # Step 4: Build, store, and send daily report
    tier_counts: dict[str, int] = {
        "A": pipeline_counts.get("tier_a", 0),
        "B": pipeline_counts.get("tier_b", 0),
        "C": pipeline_counts.get("tier_c", 0),
    }
    # Score summary for best opportunities: merge pipeline top scores + apply best_opps
    score_summary: list[tuple[int, str]] = []

    report = build_daily_report(
        pipeline_counts=pipeline_counts,
        tier_counts=tier_counts,
        score_summary=score_summary,
        pipeline_errors=pipeline_errors,
        apply_stats=apply_stats,
    )
    store_daily_report(convex, report)
    daily_msg = format_telegram_report(report)
    try:
        telegram.send_message(daily_msg)
    except Exception as exc:
        print(f"[telegram] daily report failed: {exc}")
    print(daily_msg)

    print(f"\n{'='*60}")
    print("✅ Cycle finished successfully.")
    print(f"{'='*60}\n")


def start_daemon(interval_hours: float, submit: bool, batch_limit: int) -> None:
    telegram = TelegramClient()
    interval_seconds = int(interval_hours * 3600)
    mode_text = "REAL SUBMISSIONS" if submit else "DRY-RUN (Fill & Test)"

    # Start Real-Time Telegram Ingestion Bot listener thread
    from .telegram_listener import start_telegram_listener_thread
    start_telegram_listener_thread(submit=submit)
    print("🤖 Telegram Instant Job Ingest Listener: ACTIVE")

    startup_msg = (
        f"🤖 CV Apply Continuous Engine STARTED\n\n"
        f"• Mode: {mode_text}\n"
        f"• Telegram Ingest: Active (Forward JDs directly to apply!)\n"
        f"• Interval: Every {interval_hours:g} hours\n"
        f"• Batch Cap: {batch_limit} applications/cycle\n"
        f"• Daily Cap: {settings.daily_app_cap}/day\n"
        f"• Target: Junior, Associate, High-paid Internships"
    )
    print(startup_msg)
    telegram.send_message(startup_msg)

    cycle_num = 1
    while True:
        try:
            print(f"\n>>> Running Cycle #{cycle_num} <<<")
            run_daemon_cycle(submit=submit, app_batch_limit=batch_limit)
            cycle_num += 1

            next_run = datetime.now() + timedelta(seconds=interval_seconds)
            next_str = next_run.strftime("%I:%M %p")
            print(f"💤 Sleeping for {interval_hours:g}h... Next cycle at: {next_str}")
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n🛑 Daemon stopped by user.")
            telegram.send_message("🛑 CV Apply daemon stopped.")
            break
        except Exception as exc:
            print(f"Daemon loop unexpected error: {exc}")
            time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(description="CV Apply continuous automated background daemon")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="actually submit applications (default: dry-run mode)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="interval between runs in hours (default: 3.0)",
    )
    parser.add_argument(
        "--batch-limit",
        type=int,
        default=100,
        help="max applications to attempt per cycle (default: 100)",
    )
    args = parser.parse_args()
    start_daemon(
        interval_hours=args.interval,
        submit=args.submit,
        batch_limit=args.batch_limit,
    )


if __name__ == "__main__":
    main()
