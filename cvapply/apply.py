from __future__ import annotations

import argparse
import random
import sys
import time
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .apply_email import derive_company_email, extract_apply_email, resolve_recruiter_email, send_application_email, verify_email_recipient_exists

from .atss.greenhouse import AshbyHandler, GreenhouseHandler, LeverHandler
from .atss.xpressjobs import XpressJobsHandler
from .config import settings
from .convex_api import ConvexClient
from .cv import load_cv
from .llm import OpenRouterClient
from .store import insert_log
from .telegram import TelegramClient

HANDLERS: dict[str, Any] = {
    "greenhouse": GreenhouseHandler,
    "lever": LeverHandler,
    "ashby": AshbyHandler,
    "xpressjobs": XpressJobsHandler,
}



def _daily_applied_count(convex: ConvexClient) -> int:
    since = int(time.time() * 1000) - 26 * 3600 * 1000
    docs = convex.query("queries:applicationsSince", {"since": since}) or []
    return sum(1 for d in docs if d.get("submission_status") == "success")


def _has_hard_gap(match_reason: str) -> bool:
    """Returns True if the match_reason signals a mandatory requirement gap."""
    lower = (match_reason or "").lower()
    return any(kw.lower() in lower for kw in settings.tier_b_hard_gap_keywords)


def _pick_candidates(convex: ConvexClient, limit: int) -> list[dict]:
    """
    Returns candidates sorted by A-tier → B-tier (no hard gap), then by:
    1. Sri Lanka location tier first
    2. Highest match score
    Tier C jobs and B-tier jobs with hard gaps are excluded.
    """
    jobs = convex.query("queries:scoredJobs", {"limit": 500}) or []

    tier_a: list[dict] = []
    tier_b: list[dict] = []

    for j in jobs:
        if j.get("status") != "scored":
            continue
        score = j.get("match_score") or 0
        tier = (j.get("match_tier") or "").upper()

        # Derive tier from score if not stored (backwards compat)
        if tier not in ("A", "B", "C"):
            if score >= 75:
                tier = "A"
            elif score >= 50:
                tier = "B"
            else:
                tier = "C"

        if tier == "A":
            tier_a.append(j)
        elif tier == "B":
            reason = j.get("match_reason", "")
            if not _has_hard_gap(reason):
                tier_b.append(j)
            # B with hard gap: will be sent to manual_review during apply loop
        # C: skip entirely

    # Sort each group: Sri Lanka first, then by descending score
    def sort_key(j: dict) -> tuple:
        return (0 if j.get("location_tier") == "sri_lanka" else 1, -(j.get("match_score") or 0))

    tier_a.sort(key=sort_key)
    tier_b.sort(key=sort_key)

    # Log tier distribution
    all_c = [j for j in jobs if j.get("status") == "scored" and (j.get("match_tier") or "C").upper() == "C"]
    hard_gap_b = [
        j for j in jobs
        if j.get("status") == "scored"
        and (j.get("match_tier") or "").upper() == "B"
        and _has_hard_gap(j.get("match_reason", ""))
    ]
    print(
        f"  Tier A (auto-apply): {len(tier_a)} | "
        f"Tier B (caution): {len(tier_b)} | "
        f"Tier B hard-gap (→ manual): {len(hard_gap_b)} | "
        f"Tier C (skipped): {len(all_c)}"
    )

    candidates = (tier_a + tier_b)[:limit]
    return candidates


def _mark_manual_review(
    convex: ConvexClient,
    telegram: TelegramClient,
    job: dict,
    reason: str,
) -> None:
    """Flag a job as requiring manual human action and alert via Telegram."""
    job_id = job.get("_id")
    if not job_id:
        return
    try:
        convex.mutation(
            "mutations:updateJob",
            {
                "job_id": job_id,
                "status": "manual_review",
                "manual_review_reason": reason[:500],
            },
        )
    except Exception as exc:
        print(f"  [manual_review] failed to update Convex: {exc}")

    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")
    score = job.get("match_score", 0)
    tier = (job.get("match_tier") or "?").upper()
    apply_url = job.get("apply_url", "")

    msg = (
        f"🔔 Manual Review Required\n\n"
        f"🏢 Company: {company}\n"
        f"💼 Role: {title}\n"
        f"🎯 Score: {score}/100 (Tier {tier})\n"
        f"⚠️ Reason: {reason[:200]}\n"
        f"🔗 URL: {apply_url}"
    )
    try:
        telegram.send_message(msg)
    except Exception:
        pass
    print(f"  🔔 Manual review flagged: {reason[:100]}")



def _cover_letter(llm: OpenRouterClient, job: dict, cv_text: str) -> str:
    return llm.generate_cover_letter(
        job.get("company", ""),
        job.get("title", ""),
        job.get("description", ""),
        cv_text,
    )


def _log_application(
    convex: ConvexClient,
    job_id: str,
    cover_letter: str,
    status: str,
    error: str | None,
    payload: dict[str, Any],
) -> None:
    args: dict[str, Any] = {
        "job_id": job_id,
        "cover_letter": cover_letter[:20000],
        "submitted_at": int(time.time() * 1000),
        "submission_status": status,
        "form_payload": payload,
    }
    if error:
        args["error_message"] = error[:2000]
    convex.mutation("mutations:insertApplication", args)
    convex.mutation(
        "mutations:updateJob",
        {"job_id": job_id, "status": "applied" if status == "success" else "error"},
    )


def run_apply(submit: bool, limit: int, job_id: str | None, headed: bool) -> dict[str, Any]:
    """
    Returns apply_stats dict with keys:
    submitted, manual, failed, avg_score, best_opportunities, new_companies, errors.
    """
    convex = ConvexClient()
    telegram = TelegramClient()
    llm = OpenRouterClient()
    cv_text = load_cv()

    candidates = _pick_candidates(convex, limit)
    if job_id:
        candidates = [j for j in candidates if j.get("_id") == job_id]

    apply_stats: dict[str, Any] = {
        "submitted": 0, "manual": 0, "failed": 0,
        "avg_score": 0.0, "best_opportunities": [], "new_companies": [], "errors": [],
    }

    if not candidates:
        print("no candidates above threshold")
        return apply_stats

    applied_today = _daily_applied_count(convex)
    remaining = settings.daily_app_cap - applied_today
    print(f"applied today: {applied_today} | cap: {settings.daily_app_cap} | run limit: {limit}")
    if remaining <= 0:
        print("daily cap reached - stopping")
        telegram.send_message("🚫 Daily application cap reached - stopping.")
        return apply_stats
    candidates = candidates[:remaining]

    if submit:
        print(f"⚠️  SUBMIT MODE: {len(candidates)} real applications will be sent")

    scores_this_run: list[float] = []
    seen_companies: set[str] = set()

    for idx, job in enumerate(candidates, start=1):
        title = job.get("title", "")
        company = job.get("company", "")
        score = job.get("match_score", 0)
        match_reason = job.get("match_reason", "")
        tier = (job.get("match_tier") or "B").upper()
        print(f"\n[{idx}/{len(candidates)}] [{tier}] {company} — {title} (score {score})")

        job_id_current = job.get("_id")
        scores_this_run.append(float(score))
        if company and company not in seen_companies:
            seen_companies.add(company)
            apply_stats["new_companies"].append(company)

        # ── Stage 1: EMAIL APPLICATION (PRIMARY CHANNEL — always attempted) ──
        email_target = resolve_recruiter_email(
            company,
            job.get("description", ""),
            job.get("apply_url", ""),
        )

        email_sent = False
        if email_target:
            print(f"  📧 Found recruiter email: {email_target} — generating custom email...")
            try:
                email_result = llm.generate_email_application(
                    company=company,
                    job_title=title,
                    job_desc=job.get("description", ""),
                    cv_text=cv_text,
                    match_reason=match_reason,
                )
                subject = email_result["subject"]
                body = email_result["body"]
                if submit:
                    send_application_email(email_target, subject, body, settings.cv_file_path)
                    _log_application(
                        convex, job_id_current, body, "success", None,
                        {"channel": "email", "to": email_target, "subject": subject},
                    )
                    msg = _format_telegram_msg("📧", f"EMAIL SENT → {email_target}", job, score)
                    telegram.send_message(msg)
                    print(f"  ✅ Email sent to {email_target}")
                    apply_stats["submitted"] += 1
                    apply_stats["best_opportunities"].append(f"{company} — {title} (score {score}, Tier {tier})")
                    email_sent = True
                else:
                    print(f"  [dry-run] Would email: {email_target}")
                    print(f"  Subject: {subject}")
                    print(f"  Body preview: {body[:200]}...")
                    email_sent = True
            except ValueError as exc:
                print(f"  ℹ️  Skipped unverified email ({email_target}) to prevent 550 bounce: {exc}")
            except Exception as exc:
                _log_application(convex, job_id_current, "", "failed", str(exc)[:300], {"channel": "email", "to": email_target})
                msg = _format_telegram_msg("❌", f"EMAIL FAILED ({email_target})", job, score, extra_error=str(exc))
                telegram.send_message(msg)
                print(f"  ❌ Email failed: {exc}")
                apply_stats["failed"] += 1
                apply_stats["errors"].append(f"{company}/{title}: email failed: {str(exc)[:100]}")
        else:
            print(f"  ℹ️  No recruiter email found — will apply via web portal only")

        # ── Stage 2: WEB PORTAL (SECONDARY CHANNEL — additional attempt) ──
        web_submitted = False
        handler_cls = HANDLERS.get(job.get("source"))
        if handler_cls is not None:
            try:
                letter = _cover_letter(llm, job, cv_text)
            except Exception as exc:
                print(f"  cover letter for web form failed: {exc}")
                letter = ""
            if letter:
                web_submitted = _apply_form(
                    convex, telegram, handler_cls, job, letter, submit, headed
                )
                if web_submitted and submit:
                    apply_stats["submitted"] += 1
                    if not email_sent:
                        apply_stats["best_opportunities"].append(
                            f"{company} — {title} (score {score}, Tier {tier})"
                        )
                elif not web_submitted and submit and handler_cls is not None:
                    apply_stats["failed"] += 1

        # ── Stage 3: EMAIL FALLBACK (IF WEB PORTAL FAILED & NO EMAIL SENT YET) ──
        if not email_sent and not web_submitted and settings.email_enabled:
            fallback_email = derive_company_email(company, job.get("apply_url", ""))
            if fallback_email and verify_email_recipient_exists(fallback_email):
                print(f"  📧 Web portal unavailable/failed. Sending fallback application email to {fallback_email}...")
                try:
                    email_result = llm.generate_email_application(
                        company=company,
                        job_title=title,
                        job_desc=job.get("description", ""),
                        cv_text=cv_text,
                        match_reason=match_reason,
                    )
                    subject = email_result["subject"]
                    body = email_result["body"]
                    if submit:
                        send_application_email(fallback_email, subject, body, settings.cv_file_path)
                        _log_application(
                            convex, job_id_current, body, "success", None,
                            {"channel": "email_fallback", "to": fallback_email, "subject": subject},
                        )
                        msg = _format_telegram_msg("📧", f"FALLBACK EMAIL SENT → {fallback_email}", job, score)
                        telegram.send_message(msg)
                        print(f"  ✅ Fallback application email sent to {fallback_email}")
                        apply_stats["submitted"] += 1
                        apply_stats["best_opportunities"].append(
                            f"{company} — {title} (score {score}, Tier {tier})"
                        )
                    else:
                        print(f"  [dry-run] Would send fallback email to: {fallback_email}")
                except Exception as exc:
                    print(f"  Fallback email error: {exc}")
                    apply_stats["failed"] += 1
            else:
                # All 3 channels exhausted — flag for manual review
                if submit:
                    _mark_manual_review(
                        convex, telegram, job,
                        "all_channels_failed: no email found, no ATS handler, no fallback domain"
                    )
                    apply_stats["manual"] += 1

        if idx < len(candidates):
            delay = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)
            print(f"  waiting {delay:.0f}s...")
            time.sleep(delay)

    # Finalise stats
    if scores_this_run:
        apply_stats["avg_score"] = round(sum(scores_this_run) / len(scores_this_run), 1)
    # Deduplicate best_opportunities
    seen_bests: set[str] = set()
    unique_bests: list[str] = []
    for b in apply_stats["best_opportunities"]:
        if b not in seen_bests:
            seen_bests.add(b)
            unique_bests.append(b)
    apply_stats["best_opportunities"] = unique_bests[:10]

    return apply_stats



def _format_telegram_msg(
    status_icon: str,
    status_text: str,
    job: dict,
    score: float | int,
    extra_error: str | None = None,
) -> str:
    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")
    salary = job.get("salary") or "Not specified"
    summary = job.get("summary") or (job.get("description", "")[:250] + "...")
    reason = job.get("match_reason") or "Strong match"
    apply_url = job.get("apply_url", "")

    lines = [
        f"{status_icon} {status_text}",
        "",
        f"🏢 Company: {company}",
        f"💼 Role: {title}",
        f"💰 Salary: {salary}",
        f"🎯 Fit Score: {score}/100 ({reason})",
        "",
        "📝 Role Summary:",
        summary,
        "",
        f"🔗 Job Link: {apply_url}",
    ]
    if extra_error:
        lines.append(f"\n⚠️ Note: {extra_error[:150]}")
    return "\n".join(lines)


def _apply_form(
    convex: ConvexClient,
    telegram: TelegramClient,
    handler_cls: Any,
    job: dict,
    letter: str,
    submit: bool,
    headed: bool,
) -> bool:
    company = job.get("company", "")
    try:
        from playwright.sync_api import sync_playwright

        job_id = job.get("_id")
        title = job.get("title", "")
        score = job.get("match_score", 0)
        submitted = False
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            context = browser.new_context(
                locale="en-US", viewport={"width": 1280, "height": 900}
            )
            page = context.new_page()
            handler = handler_cls(page)
            url = handler.apply_url(job)
            print(f"  opening {url}")
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                handler.prepare_page()

                # ── CAPTCHA / OTP / block detection ──
                if page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], div.g-recaptcha').count() > 0:
                    browser.close()
                    _mark_manual_review(convex, telegram, job, "captcha_detected on ATS form")
                    return False

                if "verify" in page.url.lower() or "challenge" in page.url.lower():
                    browser.close()
                    _mark_manual_review(convex, telegram, job, f"verification_redirect: {page.url[:120]}")
                    return False

                if not handler.detection_ok():
                    browser.close()
                    _mark_manual_review(convex, telegram, job, "ats_form_not_detected")
                    return False

                handler.fill_known_fields(job, letter)
                handler.screenshot(job, "filled")
                if not submit:
                    payload = handler.payload
                    payload["mode"] = "dry_run_no_submit"
                    insert_log(
                        convex,
                        "info",
                        f"dry-run fill {company} — {title} (score {score})",
                        {"details": payload, "job_id": job_id},
                    )
                    print("  dry-run fill complete (no submit) - see screenshot")
                    browser.close()
                    return False
                submitted = handler.submit()
                handler.screenshot(job, "submitted" if submitted else "failed")
                payload = handler.payload
                _log_application(
                    convex,
                    job_id,
                    letter,
                    "success" if submitted else "failed",
                    None if submitted else "submit button not confirmed",
                    payload,
                )
                status_str = "SUCCESS" if submitted else "UNCONFIRMED"
                msg = _format_telegram_msg("🤖", f"WEB FORM {status_str}", job, score)
                telegram.send_message(msg)
                print(f"  submitted: {submitted}")
                browser.close()
                return submitted
            except Exception as exc:
                handler.screenshot(job, "error")
                _log_application(convex, job_id, letter, "failed", str(exc), handler.payload)
                print(f"  failed: {exc}")
                browser.close()
                return False
    except Exception as exc:
        print(f"  ℹ️ Web portal auto-fill unavailable for {company}: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="CV Apply auto-submit engine")
    parser.add_argument("--submit", action="store_true", help="actually submit applications (default: dry-run fill)")
    parser.add_argument("--limit", type=int, default=settings.daily_app_cap, help="max applications in this run")
    parser.add_argument("--job", type=str, default=None, help="apply only this Convex job id")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    args = parser.parse_args()
    stats = run_apply(submit=args.submit, limit=args.limit, job_id=args.job, headed=args.headed)
    print(f"\nApply run complete: submitted={stats['submitted']} manual={stats['manual']} failed={stats['failed']}")


if __name__ == "__main__":
    main()