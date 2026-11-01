"""Apply form handler for itpro.lk listings.

itpro.lk carries the best-matching jobs in the database -- the 100 and 98
scoring junior/intern software roles are nearly all here -- and had no handler,
so all 51 of them went to manual review with "no email found, no ATS handler".
The page publishes no address either, so email was never an option.

Unlike xpress.jobs there is no login, and the form is small and explicitly
named, so this fills fields by name rather than guessing from placeholders:

    apply_name, apply_email, apply_cv (file), copy_applicant (checkbox),
    submit_button, job_id (hidden), recaptcha_response (hidden)

The reCAPTCHA field is populated by the site's own script. Real Chromium runs
that script, so an invisible v3 token is generated normally; a v2 challenge
would render a visible widget, which the shared CAPTCHA check in apply.py
already detects and routes to manual review rather than guessing at it.
"""

from __future__ import annotations

import time

from ..config import settings
from .base import AtsHandler


class ITProLKHandler(AtsHandler):
    name = "itpro_lk"

    def apply_url(self, job: dict) -> str:
        return str(job.get("apply_url") or "")

    def detection_ok(self) -> bool:
        """Visible, not merely present.

        The form ships in the page collapsed behind an "Apply now" button, so
        a presence-only check reports ready while every field is hidden -- fill
        then times out and the application is silently lost. prepare_page in
        the base class clicks Apply only while this returns False.
        """
        try:
            el = self.page.locator(
                'input[name="apply_name"], input[name="apply_email"]'
            ).first
            return bool(el.count()) and el.is_visible()
        except Exception:
            return False

    def _reveal_form(self) -> None:
        if self.detection_ok():
            return
        for sel in ('button:has-text("Apply now")', 'a:has-text("Apply now")',
                    'button:has-text("Apply")', 'a:has-text("Apply")'):
            try:
                btn = self.page.locator(sel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=5000)
                    for _ in range(10):
                        time.sleep(0.5)
                        if self.detection_ok():
                            self.payload["revealed_with"] = sel
                            return
            except Exception:
                continue

    def prepare_page(self) -> None:
        """apply.py checks detection_ok() before it fills anything, so the form
        has to be open by the end of this method or the job is rejected as
        ats_form_not_detected before a single field is touched."""
        super().prepare_page()
        self._reveal_form()

    def fill_known_fields(self, job: dict, cover_letter: str = "") -> None:
        self.page.set_default_timeout(8000)
        self._reveal_form()

        name = f"{settings.candidate_first_name} {settings.candidate_last_name}".strip()
        for selector, value in (
            ('input[name="apply_name"]', name),
            ('input[name="apply_email"]', settings.candidate_email or settings.email_user),
        ):
            try:
                el = self.page.locator(selector).first
                if el.count():
                    el.fill(value)
                    self.payload[selector] = value
            except Exception as exc:
                self.payload[f"{selector}_error"] = str(exc)[:120]

        # The CV is the whole point of the application; a submit without it is
        # worse than no submit, so record the failure loudly.
        try:
            cv = self.page.locator('input[name="apply_cv"]').first
            if cv.count():
                cv.set_input_files(settings.cv_file_path)
                self.payload["cv_attached"] = settings.cv_file_path
            else:
                self.payload["cv_attached"] = None
        except Exception as exc:
            self.payload["cv_error"] = str(exc)[:160]

        # Ask the board to copy us on the application: that copy is the only
        # delivery receipt this channel gives, and it lands in the same mailbox
        # the reply reader already watches.
        try:
            box = self.page.locator('input[name="copy_applicant"]').first
            if box.count() and not box.is_checked():
                box.check()
                self.payload["copy_applicant"] = True
        except Exception:
            pass

        # A cover letter field is not always present on these listings.
        if cover_letter:
            try:
                ta = self.page.locator("textarea").first
                if ta.count() and ta.is_visible():
                    ta.fill(cover_letter[:4000])
                    self.payload["cover_letter"] = True
            except Exception:
                pass

    def submit(self) -> bool:
        if not self.payload.get("cv_attached"):
            self.payload["submit_skipped"] = "CV was not attached"
            return False

        try:
            btn = self.page.locator(
                'input[name="submit_button"], input[type="submit"], button[type="submit"]'
            ).first
            if not btn.count():
                self.payload["submit_skipped"] = "no submit control found"
                return False
            btn.click(timeout=8000)
        except Exception as exc:
            self.payload["submit_error"] = str(exc)[:160]
            return False

        for _ in range(10):
            time.sleep(1)
            if self._submission_detected():
                return True
        self.payload["submit_unconfirmed"] = True
        return False

    def _form_is_gone(self) -> bool:
        """The form closing is itself a confirmation.

        A real application to FocalDive was logged as "submit button not
        confirmed" because that page shows no success phrase -- the board's
        receipt email proved it had gone through. A false negative is not
        harmless: the job stays unapplied, so the next cycle applies again and
        the employer gets a duplicate.
        """
        try:
            return not self.detection_ok()
        except Exception:
            return False

    def _submission_detected(self) -> bool:
        """A stated confirmation, or the form closing behind us."""
        if self._form_is_gone():
            self.payload["confirmation"] = "form closed after submit"
            return True

        try:
            body = (self.page.inner_text("body") or "").lower()
        except Exception:
            return False
        for phrase in (
            "application sent",
            "application submitted",
            "successfully applied",
            "thank you for applying",
            "your application has been",
            "we have received your application",
        ):
            if phrase in body:
                self.payload["confirmation"] = phrase
                return True
        return False
