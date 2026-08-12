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

from .apply_email import derive_company_email, extract_apply_email, send_application_email

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
    return len(docs)


def _pick_candidates(convex: ConvexClient, limit: int) -> list[dict]:
    jobs = convex.query("queries:scoredJobs", {"limit": 500}) or []
    candidates = [
        j
        for j in jobs
        if j.get("status") == "scored"
        and (j.get("match_score") or 0) >= settings.match_threshold
    ]
    # Prioritize Sri Lanka location tier first, then highest match score
    candidates.sort(key=lambda j: (0 if j.get("location_tier") == "sri_lanka" else 1, -(j.get("match_score") or 0)))
    return candidates[:limit]



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


def run_apply(submit: bool, limit: int, job_id: str | None, headed: bool) -> None:
    convex = ConvexClient()
    telegram = TelegramClient()
    llm = OpenRouterClient()
    cv_text = load_cv()

    candidates = _pick_candidates(convex, limit)
    if job_id:
        candidates = [j for j in candidates if j.get("_id") == job_id]

    if not candidates:
        print("no candidates above threshold")
        return

    applied_today = _daily_applied_count(convex)
    remaining = settings.daily_app_cap - applied_today
    print(f"applied today: {applied_today} | cap: {settings.daily_app_cap} | run limit: {limit}")
    if remaining <= 0:
        print("daily cap reached - stopping")
        telegram.send_message("🚫 Daily application cap reached - stopping.")
        return
    candidates = candidates[:remaining]

    if submit:
        print(f"⚠️  SUBMIT MODE: {len(candidates)} real applications will be sent")

    for idx, job in enumerate(candidates, start=1):
        title = job.get("title", "")
        company = job.get("company", "")
        score = job.get("match_score", 0)
        match_reason = job.get("match_reason", "")
        print(f"\n[{idx}/{len(candidates)}] {company} — {title} (score {score})")

        job_id = job.get("_id")

        # ── Stage 1: EMAIL APPLICATION (PRIMARY CHANNEL — always attempted) ──
        # Check verified directory first for 100% bounce protection, then extract from description
        email_target = derive_company_email(company, job.get("apply_url", ""))
        if not email_target and settings.email_enabled:
            email_target = extract_apply_email(job.get("description", ""), job.get("apply_url", ""))

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
                        convex, job_id, body, "success", None,
                        {"channel": "email", "to": email_target, "subject": subject},
                    )
                    msg = _format_telegram_msg("📧", f"EMAIL SENT → {email_target}", job, score)
                    telegram.send_message(msg)
                    print(f"  ✅ Email sent to {email_target}")
                else:
                    print(f"  [dry-run] Would email: {email_target}")
                    print(f"  Subject: {subject}")
                    print(f"  Body preview: {body[:200]}...")
            except ValueError as exc:
                print(f"  ℹ️  Skipped unverified email ({email_target}) to prevent 550 bounce: {exc}")
            except Exception as exc:
                _log_application(convex, job_id, "", "failed", str(exc)[:300], {"channel": "email", "to": email_target})
                msg = _format_telegram_msg("❌", f"EMAIL FAILED ({email_target})", job, score, extra_error=str(exc))
                telegram.send_message(msg)
                print(f"  ❌ Email failed: {exc}")

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
                web_submitted = _apply_form(convex, telegram, handler_cls, job, letter, submit, headed)

        # ── Stage 3: EMAIL FALLBACK (IF WEB PORTAL FAILED & NO EMAIL SENT YET) ──
        if not email_target and not web_submitted and settings.email_enabled:
            fallback_email = derive_company_email(company, job.get("apply_url", ""))
            if fallback_email:

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
                            convex, job_id, body, "success", None,
                            {"channel": "email_fallback", "to": fallback_email, "subject": subject},
                        )
                        msg = _format_telegram_msg("📧", f"FALLBACK EMAIL SENT → {fallback_email}", job, score)
                        telegram.send_message(msg)
                        print(f"  ✅ Fallback application email sent to {fallback_email}")
                    else:
                        print(f"  [dry-run] Would send fallback email to: {fallback_email}")
                except Exception as exc:
                    print(f"  Fallback email error: {exc}")

        if idx < len(candidates):
            delay = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)

            print(f"  waiting {delay:.0f}s...")
            time.sleep(delay)



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
    from playwright.sync_api import sync_playwright

    job_id = job.get("_id")
    title = job.get("title", "")
    company = job.get("company", "")
    score = job.get("match_score", 0)
    submitted = False
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not headed)
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
            if not handler.detection_ok():
                raise RuntimeError("ATS form not detected on page")
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
            if submitted:
                _log_application(convex, job_id, letter, "success", None, payload)
                msg = _format_telegram_msg("✅", "APPLICATION SUBMITTED VIA PORTAL", job, score)
                telegram.send_message(msg)
                print("  SUBMITTED VIA PORTAL")
            else:
                err = payload.get("validation_errors") or [payload.get("submit_error", "submission not confirmed")]
                _log_application(convex, job_id, letter, "failed", str(err)[:300], payload)
                print(f"  portal submit failed: {err}")
        except Exception as exc:
            handler.screenshot(job, "error")
            _log_application(convex, job_id, letter, "failed", str(exc)[:300], handler.payload)
            print(f"  portal error: {exc}")
        finally:
            browser.close()

    return submitted




def main() -> None:
    parser = argparse.ArgumentParser(description="CV Apply auto-submit engine")
    parser.add_argument("--submit", action="store_true", help="actually submit applications (default: dry-run fill)")
    parser.add_argument("--limit", type=int, default=settings.daily_app_cap, help="max applications in this run")
    parser.add_argument("--job", type=str, default=None, help="apply only this Convex job id")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    args = parser.parse_args()
    run_apply(submit=args.submit, limit=args.limit, job_id=args.job, headed=args.headed)


if __name__ == "__main__":
    main()