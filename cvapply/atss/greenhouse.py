from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Page

from ..config import settings
from .base import AtsHandler


class GreenhouseHandler(AtsHandler):
    name = "greenhouse"
    resume_selector = 'input[type="file"][name*="candidate_resume"], input[type="file"][accept*="pdf"], input#resume, input[type="file"]'

    def apply_url(self, job: dict) -> str:
        url = (job.get("apply_url") or "").rstrip("/")
        return url

    def detection_ok(self) -> bool:
        return (
            self.page.locator(
                'input[name*="job_application"], input#first_name, input[id*="first_name"], '
                'input[name="first_name"], form#application_form, input#resume, input[type="file"]'
            ).count()
            > 0
        )

    def _fill_first_matching(self, selectors: list[str], value: str) -> None:
        for sel in selectors:
            loc = self.page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                try:
                    loc.scroll_into_view_if_needed()
                    loc.fill(value)
                    self.payload[sel] = value
                    return
                except Exception:
                    pass

    def fill_known_fields(self, job: dict, cover_letter: str) -> None:
        self._fill_first_matching(
            [
                'input[name="job_application[first_name]"]',
                'input#first_name',
                'input[name="first_name"]',
                'input[autocomplete="given-name"]',
            ],
            settings.candidate_first_name,
        )
        self._fill_first_matching(
            [
                'input[name="job_application[last_name]"]',
                'input#last_name',
                'input[name="last_name"]',
                'input[autocomplete="family-name"]',
            ],
            settings.candidate_last_name,
        )
        self._fill_first_matching(
            [
                'input[name="job_application[email]"]',
                'input#email',
                'input[name="email"]',
                'input[type="email"]',
            ],
            settings.candidate_email,
        )
        self._fill_first_matching(
            [
                'input[name="job_application[phone]"]',
                'input#phone',
                'input[name="phone"]',
                'input[type="tel"]',
            ],
            settings.candidate_phone,
        )
        self._fill_first_matching(
            [
                'input#country',
                'input[name*="country"]',
                'input[id*="country"]',
            ],
            "Sri Lanka",
        )
        self._fill_first_matching(
            [
                'textarea[name="job_application[cover_letter]"]',
                'textarea#cover_letter_text',
                'textarea[name*="cover_letter"]',
                'textarea#cover_letter',
            ],
            cover_letter,
        )
        self._fill_first_matching(
            [
                'input[name="job_application[linkedin_profile_url]"]',
                'input#linkedin',
                'input[id*="linkedin"]',
                'input[name*="linkedin"]',
            ],
            settings.candidate_linkedin,
        )
        self._fill_first_matching(
            [
                'input[name="job_application[website_url]"]',
                'input#website',
                'input[id*="website"]',
                'input[name*="website"]',
                'input[id*="portfolio"]',
            ],
            settings.candidate_website,
        )
        answers = self.fill_required_generic(cover_letter)
        self.payload["generic_answers"] = answers
        self.fill_required_radios()
        self.fill_required_selects()
        self.fill_react_comboboxes()
        self.fill_remaining_textareas(cover_letter)
        # Upload resume LAST — after all dropdowns done to prevent form reset
        self.upload_resume()
        # opt-in checkboxes (e.g. "I confirm" / consent) if required
        boxes = self.page.locator('input[type="checkbox"]')
        count = boxes.count()
        for i in range(count):
            box = boxes.nth(i)
            try:
                required = box.get_attribute("required") is not None
                if required:
                    box.check(force=True)
                    self.payload[f"checkbox:{i}"] = "checked"
            except Exception:
                continue


    def submit(self) -> bool:
        ok = self.safe_submit_click()
        if ok:
            for _ in range(8):
                time.sleep(1)
                if self._submission_detected():
                    return True
        return False


    def _submission_detected(self) -> bool:
        try:
            url = self.page.url.lower()
            if any(k in url for k in ("applications", "thank", "submitted", "confirmation", "success", "complete")):
                return True
        except Exception:
            pass
        try:
            text = self.page.locator("body").inner_text().lower()
            return any(
                phrase in text
                for phrase in (
                    "your application has been received",
                    "thank you for applying",
                    "application submitted",
                    "application has been submitted",
                    "we have received your application",
                    "thanks for applying",
                    "successfully submitted",
                    "application received",
                )
            )
        except Exception:
            return False



class LeverHandler(AtsHandler):
    name = "lever"
    resume_selector = 'input[type="file"]'

    def apply_url(self, job: dict) -> str:
        url = (job.get("apply_url") or "").rstrip("/")
        return url if url.endswith("/apply") else url + "/apply"

    def detection_ok(self) -> bool:
        return self.page.locator('input[type="file"], input[name="name"], input[name*="email"]').count() > 0

    def fill_known_fields(self, job: dict, cover_letter: str) -> None:
        inputs = self.page.locator('input:not([type="hidden"]):not([type="file"])')
        count = inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            try:
                if not el.is_visible():
                    continue
                name_attr = el.get_attribute("name") or ""
                if i == 0 and "name" in name_attr.lower():
                    el.fill(f"{settings.candidate_first_name} {settings.candidate_last_name}")
                    self.payload["name"] = "filled"
                    continue
                placeholder = (el.get_attribute("placeholder") or "").lower()
                if "email" in placeholder or "mail" in name_attr.lower():
                    el.fill(settings.candidate_email)
                    self.payload["email"] = "filled"
                elif "phone" in placeholder or "phone" in name_attr.lower():
                    el.fill(settings.candidate_phone)
                    self.payload["phone"] = "filled"
                elif "linkedin" in placeholder:
                    el.fill(settings.candidate_linkedin)
                elif "website" in placeholder or "github" in placeholder or "portfolio" in placeholder:
                    el.fill(settings.candidate_website)
                elif "cover" in (el.get_attribute("form") or ""):
                    pass
            except Exception:
                continue
        textareas = self.page.locator("textarea")
        if textareas.count():
            try:
                textareas.first.fill(cover_letter)
                self.payload["cover_letter"] = "filled"
            except Exception:
                pass
        self.upload_resume()
        self.fill_required_generic(cover_letter)
        self.fill_required_radios()
        self.fill_required_selects()

    def submit(self) -> bool:
        ok = self.safe_submit_click()
        if ok:
            for _ in range(8):
                time.sleep(1)
                if self._submission_detected():
                    return True
        return False


    def _submission_detected(self) -> bool:
        try:
            text = self.page.locator("body").inner_text().lower()[:800]
            return any(
                phrase in text
                for phrase in (
                    "application sent",
                    "thank you for",
                    "your application has been submitted",
                    "successfully submitted",
                )
            )
        except Exception:
            return False


class AshbyHandler(AtsHandler):
    name = "ashby"
    resume_selector = 'input[type="file"], input#_systemfield_resume'

    def apply_url(self, job: dict) -> str:
        return job.get("apply_url") or ""

    def detection_ok(self) -> bool:
        return (
            self.page.locator(
                'input[name="_systemfield_name"], input#_systemfield_name, '
                'input[type="file"], input[name*="name"], [data-testid*="text-field"]'
            ).count()
            > 0
        )

    def _fill_first_matching(self, selectors: list[str], value: str) -> None:
        for sel in selectors:
            loc = self.page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                try:
                    loc.scroll_into_view_if_needed()
                    loc.fill(value)
                    self.payload[sel] = value
                    return
                except Exception:
                    pass

    def fill_known_fields(self, job: dict, cover_letter: str) -> None:
        self._fill_first_matching(
            [
                'input[name="_systemfield_name"]',
                'input#_systemfield_name',
                'input[name="name"]',
            ],
            f"{settings.candidate_first_name} {settings.candidate_last_name}",
        )
        self._fill_first_matching(
            [
                'input[name="_systemfield_email"]',
                'input#_systemfield_email',
                'input[name="email"]',
                'input[type="email"]',
            ],
            settings.candidate_email,
        )
        self._fill_first_matching(
            [
                'input[name="_systemfield_phone"]',
                'input[id*="phone"]',
                'input[name*="phone"]',
                'input[type="tel"]',
            ],
            settings.candidate_phone,
        )

        inputs = self.page.locator('input[type="text"], input[type="email"], input[type="tel"], input:not([type])')
        count = inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            try:
                name_attr = (el.get_attribute("name") or "").lower()
                data_testid = (el.get_attribute("data-testid") or "").lower()
                el_id = (el.get_attribute("id") or "").lower()
                hint = f"{name_attr} {data_testid} {el_id} {(el.get_attribute('placeholder') or '').lower()}"
                if "linkedin" in hint:
                    el.fill(settings.candidate_linkedin)
                elif "website" in hint or "github" in hint or "portfolio" in hint:
                    el.fill(settings.candidate_website)
                elif "location" in hint or "city" in hint:
                    el.fill(settings.candidate_city)
            except Exception:
                continue

        textareas = self.page.locator("textarea")
        if textareas.count():
            try:
                textareas.first.fill(cover_letter)
                self.payload["cover_letter"] = "filled"
            except Exception:
                pass

        self.upload_resume()
        answers = self.fill_required_generic(cover_letter)
        self.payload["generic_answers"] = answers
        self.fill_required_radios()
        self.fill_required_selects()
        self.fill_react_comboboxes()
        self.fill_remaining_textareas(cover_letter)


    def submit(self) -> bool:
        ok = self.safe_submit_click()
        if ok:
            for _ in range(8):
                time.sleep(1)
                if self._submission_detected():
                    return True
        return False


    def _submission_detected(self) -> bool:
        try:
            text = self.page.locator("body").inner_text().lower()[:800]
            return any(
                phrase in text
                for phrase in (
                    "application submitted",
                    "thank you for applying",
                    "your application was submitted",
                    "we appreciate your interest",
                )
            )
        except Exception:
            return False