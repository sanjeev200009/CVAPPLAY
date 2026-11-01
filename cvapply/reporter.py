"""
Daily report builder.
Assembles the 10-field daily run report from pipeline + apply stage data,
stores it in Convex daily_reports table, and formats the Telegram message.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .convex_api import ConvexClient


def build_daily_report(
    pipeline_counts: dict[str, int],
    tier_counts: dict[str, int],
    score_summary: list[tuple[int, str]],
    pipeline_errors: list[str],
    apply_stats: dict[str, Any],
) -> dict[str, Any]:
    """
    Assembles a complete daily_report document.

    Parameters
    ----------
    pipeline_counts : fetched/new/duplicates/filtered/invalid/errors keys
    tier_counts     : A/B/C counts from scoring pass
    score_summary   : list of (score, "Company — Title") for top jobs
    pipeline_errors : error strings from sourcing/scoring
    apply_stats     : keys: submitted, manual, failed, avg_score,
                      best_opportunities (list[str]), new_companies (list[str])
    """
    now_ms = int(time.time() * 1000)

    jobs_found = pipeline_counts.get("fetched", 0)
    jobs_filtered = pipeline_counts.get("filtered", 0)
    jobs_invalid = pipeline_counts.get("invalid", 0)
    jobs_relevant = pipeline_counts.get("new", 0)

    tier_a = tier_counts.get("A", 0)
    tier_b = tier_counts.get("B", 0)
    tier_c = tier_counts.get("C", 0)

    submitted = apply_stats.get("submitted", 0)
    manual = apply_stats.get("manual", 0)
    failed = apply_stats.get("failed", 0)
    avg_score = apply_stats.get("avg_score", 0.0)
    best_opps = apply_stats.get("best_opportunities", [])[:10]
    new_companies = apply_stats.get("new_companies", [])[:20]

    # Merge pipeline errors (sourcing) + apply errors
    all_problems = list(pipeline_errors[:20]) + apply_stats.get("errors", [])[:10]
    all_problems = [str(p)[:200] for p in all_problems[:25]]

    report: dict[str, Any] = {
        "run_at": now_ms,
        "jobs_found": jobs_found,
        "jobs_filtered": jobs_filtered,
        "jobs_invalid": jobs_invalid,
        "jobs_relevant": jobs_relevant,
        "tier_a_count": tier_a,
        "tier_b_count": tier_b,
        "tier_c_count": tier_c,
        "applications_submitted": submitted,
        "applications_manual": manual,
        "applications_failed": failed,
        "avg_match_score": round(float(avg_score), 1),
        "new_companies": new_companies,
        "best_opportunities": best_opps,
        "source_breakdown": pipeline_counts.get("source_breakdown", {}),
        "problems": all_problems,
    }
    return report


def store_daily_report(convex: ConvexClient, report: dict[str, Any]) -> None:
    """Persist the daily report to Convex."""
    try:
        convex.mutation("mutations:insertDailyReport", report)
    except Exception as exc:
        print(f"[reporter] failed to store daily report: {exc}")


def format_telegram_report(report: dict[str, Any]) -> str:
    """Format the 10-field daily report as a Telegram message."""
    run_dt = datetime.fromtimestamp(report["run_at"] / 1000).strftime("%Y-%m-%d %I:%M %p")

    lines: list[str] = [
        f"📊 Daily CV Apply Report — {run_dt}",
        "",
        f"📥 Jobs Found:              {report['jobs_found']}",
        f"✅ Relevant Jobs:           {report['jobs_relevant']}",
        f"🚫 Filtered Out:            {report['jobs_filtered']}",
        f"⚠️  Invalid / Scam:          {report['jobs_invalid']}",
        "",
        f"🏆 Tier A (auto-apply):     {report['tier_a_count']}",
        f"📋 Tier B (caution):        {report['tier_b_count']}",
        f"❌ Tier C (skipped):        {report['tier_c_count']}",
        "",
        f"📤 Applications Submitted: {report['applications_submitted']}",
        f"🔔 Manual Review Required: {report['applications_manual']}",
        f"❌ Applications Failed:    {report['applications_failed']}",
        f"🎯 Average Match Score:    {report['avg_match_score']}/100",
        "",
        f"🏢 New Companies Found: {len(report['new_companies'])}",
    ]

    if report["best_opportunities"]:
        lines.append("")
        lines.append("🌟 Best Opportunities:")
        for opp in report["best_opportunities"][:5]:
            lines.append(f"  • {opp}")

    if report["problems"]:
        lines.append("")
        lines.append("⚠️ Problems Encountered:")
        for prob in report["problems"][:5]:
            lines.append(f"  • {str(prob)[:120]}")

    return "\n".join(lines)
