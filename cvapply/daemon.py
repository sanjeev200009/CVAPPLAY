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
from .main import run_pipeline
from .telegram import TelegramClient


def run_daemon_cycle(submit: bool, app_batch_limit: int) -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    print(f"\n{'='*60}")
    print(f"🚀 Starting Auto-Apply Daemon Cycle: {now_str}")
    print(f"{'='*60}")

    telegram = TelegramClient()
    telegram.send_message(f"🔄 Starting CV Apply cycle ({now_str})...")

    # Step 1: Sourcing & LLM Scoring
    print("\n[Stage 1/2] Sourcing new jobs & scoring...")
    try:
        counts = run_pipeline(dry_run=False, score=True)
        print(f"Sourcing completed: {counts['fetched']} fetched, {counts['new']} new candidates.")
    except Exception as exc:
        print(f"Sourcing error: {exc}")
        telegram.send_message(f"⚠️ Sourcing pipeline warning: {exc}")

    # Step 2: Auto-Apply to top scoring candidates
    print(f"\n[Stage 2/2] Auto-applying to scored jobs (submit={submit}, batch_limit={app_batch_limit})...")
    try:
        run_apply(submit=submit, limit=app_batch_limit, job_id=None, headed=False)
        print("Application run completed.")
    except Exception as exc:
        print(f"Apply error: {exc}")
        telegram.send_message(f"⚠️ Application run error: {exc}")

    print(f"\n{'='*60}")
    print("✅ Cycle finished successfully.")
    print(f"{'='*60}\n")


def start_daemon(interval_hours: float, submit: bool, batch_limit: int) -> None:
    telegram = TelegramClient()
    interval_seconds = int(interval_hours * 3600)
    mode_text = "REAL SUBMISSIONS" if submit else "DRY-RUN (Fill & Test)"

    startup_msg = (
        f"🤖 CV Apply Continuous Engine STARTED\n\n"
        f"• Mode: {mode_text}\n"
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
        default=6,
        help="max applications to submit per cycle (default: 6)",
    )
    args = parser.parse_args()
    start_daemon(
        interval_hours=args.interval,
        submit=args.submit,
        batch_limit=args.batch_limit,
    )


if __name__ == "__main__":
    main()
