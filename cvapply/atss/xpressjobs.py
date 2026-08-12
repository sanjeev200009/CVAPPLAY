"""
Playwright web form automation handler for XpressJobs (xpress.jobs) listings.
Fills name, email, phone, city/location, NIC number, attaches CV PDF, checks agreements, and submits.
"""
from __future__ import annotations

import time

from ..config import settings
from .base import AtsHandler


class XpressJobsHandler(AtsHandler):
    name = "xpressjobs"

    def apply_url(self, job: dict) -> str:
        url = str(job.get("apply_url") or "")
        if url.startswith("mailto:"):
            url = url.split(";")[-1]
        return url

    def fill_known_fields(self, job: dict | str, cover_letter: str = "") -> None:
        # Set short default timeout on page so operations fail fast if element missing
        self.page.set_default_timeout(4000)

        # Step 1: Click "APPLY NOW" button to open application modal
        try:
            # Try multiple text variations for Apply button
            apply_loc = self.page.locator(
                'button:has-text("APPLY"), a:has-text("APPLY"), [class*="apply" i]'
            ).first
            if apply_loc.count() > 0 and apply_loc.is_visible():
                apply_loc.click(timeout=3000)
                time.sleep(1.0)
            else:
                # Try role fallback
                btn = self.page.get_by_role("button", name="APPLY NOW").or_(
                    self.page.get_by_role("link", name="APPLY NOW")
                ).first
                if btn.count() > 0:
                    btn.click(timeout=3000)
                    time.sleep(1.0)
        except Exception as exc:
            self.payload["apply_button_error"] = str(exc)[:100]


        # Step 2: Fill text fields by placeholder heuristics
        field_map = {
            "name": f"{settings.candidate_first_name} {settings.candidate_last_name}",
            "email": settings.candidate_email,
            "phone": settings.candidate_phone,
            "location": "Colombo",
            "nic": "200025701890",
        }

        inputs = self.page.locator('input[type="text"], input[type="email"], input[type="tel"]')
        count = inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            try:
                if not el.is_visible():
                    continue
                ph = (el.get_attribute("placeholder") or "").lower()

                if "name" in ph:
                    el.fill(field_map["name"])
                    self.payload["name"] = field_map["name"]
                elif "email" in ph:
                    el.fill(field_map["email"])
                    self.payload["email"] = field_map["email"]
                elif "phone" in ph or "mobile" in ph or "contact" in ph:
                    el.fill(field_map["phone"])
                    self.payload["phone"] = field_map["phone"]
                elif "location" in ph or "city" in ph or "address" in ph:
                    el.fill(field_map["location"])
                    self.payload["location"] = field_map["location"]
                elif "nic" in ph or "identity" in ph or "id number" in ph:
                    el.fill(field_map["nic"])
                    self.payload["nic"] = field_map["nic"]
            except Exception:
                continue

        # Step 3: Attach CV PDF
        self.upload_resume()

        # Step 4: Check required consent checkboxes
        boxes = self.page.locator('input[type="checkbox"]')
        for i in range(boxes.count()):
            box = boxes.nth(i)
            try:
                if box.is_visible():
                    box.check(force=True)
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
            body = self.page.locator("body").inner_text().lower()
            return any(
                p in body
                for p in (
                    "success",
                    "application submitted",
                    "thank you for applying",
                    "applied successfully",
                    "your application has been sent",
                )
            )
        except Exception:
            return False
