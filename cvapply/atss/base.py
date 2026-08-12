from __future__ import annotations

import os
import re
import time
from typing import Any

from playwright.sync_api import Locator, Page

from ..config import settings


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _label_text(input_el: Locator) -> str:
    """Best-effort label discovery for an input (label[for], wrapping label)."""
    try:
        el_id = input_el.get_attribute("id")
        if el_id:
            label = input_el.page.locator(f'label[for="{el_id}"]')
            if label.count() and label.first.is_visible():
                return _clean(label.first.inner_text())
        parent = input_el.locator("xpath=..")
        if parent.locator("label").count():
            return _clean(parent.locator("label").first.inner_text())
        if parent.evaluate("(el) => el.tagName") == "LABEL":
            return _clean(parent.inner_text())
    except Exception:
        pass
    return ""


class AtsHandler:
    """Base handler for an ATS application form. Subclasses define selectors."""

    name = "base"

    def __init__(self, page: Page) -> None:
        self.page = page
        self.payload: dict[str, Any] = {}

    # --- overridable -----------------------------------------------------
    def apply_url(self, job: dict) -> str:
        raise NotImplementedError

    def fill_known_fields(self, job: dict, cover_letter: str) -> None:
        raise NotImplementedError

    def submit(self) -> bool:
        raise NotImplementedError

    def detection_ok(self) -> bool:
        raise NotImplementedError

    def prepare_page(self) -> None:
        """Handles cookie banners, dynamic apply buttons, and waits for form elements."""
        # 1. Dismiss cookie banners if present
        for cookie_sel in [
            'button:has-text("Accept All")',
            'button:has-text("Accept Cookies")',
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
            'button:has-text("Allow all")',
            'button:has-text("I agree")',
            'button:has-text("Dismiss")',
            'button:has-text("Got it")',
            '#onetrust-accept-btn-handler',
        ]:
            try:
                btn = self.page.locator(cookie_sel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=2000)
                    time.sleep(0.5)
                    break
            except Exception:
                pass

        # 2. If form is not yet visible, check for "Apply" buttons/links to expand form
        if not self.detection_ok():
            for apply_btn_sel in [
                'a:has-text("Apply for this job")',
                'button:has-text("Apply for this job")',
                'a:has-text("Apply for this role")',
                'button:has-text("Apply for this role")',
                'a:has-text("Apply Now")',
                'button:has-text("Apply Now")',
                'a:has-text("Apply")',
                'button:has-text("Apply")',
                '[data-testid*="apply-button"]',
                '[data-testid*="applyButton"]',
            ]:
                try:
                    btn = self.page.locator(apply_btn_sel).first
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=3000)
                        time.sleep(2)
                        break
                except Exception:
                    pass

        # 3. Wait for dynamic form elements (e.g. React/SPA) to mount
        for _ in range(8):
            if self.detection_ok():
                break
            time.sleep(1)

    # --- shared helpers ---------------------------------------------------
    def fill(self, selector: str, value: str, required: bool = True) -> None:
        loc = self.page.locator(selector).first
        if loc.count() == 0:
            if required:
                self.payload[f"missing:{selector}"] = "not found"
            return
        try:
            loc.scroll_into_view_if_needed()
            loc.fill(value)
            self.payload[selector] = value
        except Exception as exc:
            self.payload[f"error:{selector}"] = str(exc)[:120]

    def fill_password_like(self, _job: dict, _cover: str) -> None:
        pass

    def upload_resume(self) -> None:
        """Upload CV to any file input — handles visible, hidden, and drag-drop inputs."""
        import time as _time
        cv_path = settings.cv_file_path

        # Ordered selectors: specific first, generic fallback last
        selectors = [
            getattr(self, "resume_selector", None),
            'input[type="file"][id="resume"]',
            'input[type="file"][name="resume"]',
            'input[type="file"][id*="resume"]',
            'input[type="file"][name*="resume"]',
            'input[type="file"][accept*="pdf"]',
            'input#_systemfield_resume',
            'input[type="file"]',
        ]
        selectors = [s for s in selectors if s]

        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.count() == 0:
                    continue
                # Use set_input_files even on hidden inputs (Playwright supports it natively)
                loc.set_input_files(cv_path)
                _time.sleep(0.5)
                self.payload["resume_upload"] = settings.cv_file_name
                return
            except Exception as exc:
                self.payload[f"resume_upload_error_{sel[:30]}"] = str(exc)[:80]
                continue

        # Last resort: try JS dispatchEvent on every file input found
        try:
            file_inputs = self.page.locator('input[type="file"]')
            for i in range(file_inputs.count()):
                try:
                    file_inputs.nth(i).set_input_files(cv_path)
                    _time.sleep(0.3)
                    self.payload["resume_upload"] = settings.cv_file_name
                    return
                except Exception:
                    continue
        except Exception:
            pass

        self.payload["resume_upload"] = "UPLOAD_FAILED"



    def fill_required_generic(self, cover_letter: str) -> dict[str, str]:
        """Fills text-ish fields by label heuristics. Returns answers."""
        answers: dict[str, str] = {}
        candidates = self.page.locator(
            "input[type=text], input[type=email], input[type=tel], input[type=number], input:not([type]), textarea"
        )
        count = candidates.count()
        for i in range(count):
            el = candidates.nth(i)
            try:
                required = (
                    el.get_attribute("required") is not None
                    or el.get_attribute("aria-required") == "true"
                )
                label = _label_text(el)
                if not label:
                    label = el.get_attribute("placeholder") or el.get_attribute("name") or ""
                if not label:
                    continue
                lower = label.lower()
                el_type = el.get_attribute("type") or "text"
                value = None

                if "name" in lower and ("full" in lower or "first" in lower or "last" in lower):
                    value = (
                        f"{settings.candidate_first_name} {settings.candidate_last_name}"
                        if "full" in lower or "first" in lower
                        else settings.candidate_last_name
                    )
                elif "email" in lower:
                    value = settings.candidate_email
                elif "phone" in lower or "mobile" in lower:
                    value = settings.candidate_phone
                elif "linkedin" in lower:
                    value = settings.candidate_linkedin
                elif "website" in lower or "github" in lower or "portfolio" in lower:
                    value = settings.candidate_website
                elif "cover" in lower:
                    value = cover_letter
                elif any(w in lower for w in ("how did you hear", "where did you hear", "referral", "candidate source")) and "open source" not in lower:
                    value = "LinkedIn"
                elif "experience with" in lower or "describe your" in lower:
                    value = f"I have hands-on practical experience in modern software development with Python, React, JavaScript, REST APIs, and Linux systems from my engineering projects and recent developer role."

                elif "address" in lower:
                    value = settings.candidate_city
                elif any(w in lower for w in ("notice", "availability", "when can you start", "start date", "earliest start")):
                    value = settings.candidate_notice_period
                elif any(w in lower for w in ("current salary", "present salary", "current compensation", "current ctc", "current pay")):
                    value = "55000" if el_type == "number" else settings.candidate_current_salary
                elif any(w in lower for w in ("expected salary", "salary expectation", "desired salary", "expected compensation", "expected ctc", "expected pay", "desired pay", "compensation expectation")):
                    if el_type == "number":
                        value = settings.candidate_expected_salary_num
                    elif "usd" in lower or "$" in lower:
                        value = settings.candidate_expected_salary_usd
                    else:
                        value = settings.candidate_expected_salary
                elif "salary" in lower or "compensation" in lower or "ctc" in lower:
                    value = settings.candidate_expected_salary_num if el_type == "number" else settings.candidate_expected_salary
                elif any(w in lower for w in ("authorized to work", "legally authorized", "eligible to work", "work permit")):
                    value = "Yes"
                elif any(w in lower for w in ("require sponsorship", "need sponsorship", "visa sponsorship")):
                    value = "No"

                if value is None:
                    continue
                if not required and not self._label_known(lower):
                    continue
                el.scroll_into_view_if_needed()
                el.fill(value)
                answers[label] = value
            except Exception:
                continue
        return answers

    @staticmethod
    def _label_known(lower: str) -> bool:
        return any(
            w in lower
            for w in (
                "name", "email", "phone", "mobile", "linkedin", "website",
                "github", "portfolio", "cover", "hear", "referral", "source", "address",
                "notice", "availability", "start", "salary", "compensation", "ctc",
                "authorized", "sponsorship", "permit",
            )
        )

    def fill_required_radios(self) -> int:
        filled = 0
        radios = self.page.locator('input[type="radio"]')
        count = radios.count()
        seen: set[str] = set()
        for i in range(count):
            el = radios.nth(i)
            try:
                group = el.get_attribute("name")
                if not group or group in seen:
                    continue
                seen.add(group)
                required = el.get_attribute("required") is not None
                if not required:
                    continue
                label = _label_text(el)
                # pick the option matching our location, else the first
                first = radios.locator(f'input[name="{group}"]').first
                opts = radios.locator(f'input[name="{group}"]')
                value = None
                for k in range(opts.count()):
                    opt_label = _label_text(opts.nth(k)).lower()
                    if "sri lanka" in opt_label or ("remote" in opt_label and "not" not in opt_label) or "yes" in opt_label:
                        value = opts.nth(k)
                        break
                if value is None:
                    value = first
                value.check(force=True)
                self.payload[f"radio:{group}"] = label
                filled += 1
            except Exception:
                continue
        return filled

    def fill_required_selects(self) -> int:
        filled = 0
        selects = self.page.locator("select:not([multiple])")
        count = selects.count()
        for i in range(count):
            el = selects.nth(i)
            try:
                required = el.get_attribute("required") is not None
                if not required:
                    continue
                options = el.locator("option")
                n_opts = options.count()
                if n_opts == 0:
                    continue
                label = _label_text(el)
                value = None
                lower_label = label.lower()
                if "country" in lower_label or "citizenship" in lower_label or "location" in lower_label:
                    value = self._pick_option(el, "Sri Lanka")
                elif "hear" in lower_label or "source" in lower_label or "referral" in lower_label:
                    value = self._pick_option(el, "LinkedIn")
                elif "notice" in lower_label or "availability" in lower_label:
                    value = self._pick_option(el, "2 weeks") or self._pick_option(el, "Immediate") or self._pick_option(el, "1 month")
                elif "authorized" in lower_label or "eligible" in lower_label:
                    value = self._pick_option(el, "Yes")
                elif "sponsorship" in lower_label:
                    value = self._pick_option(el, "No")

                if value is None:
                    value = options.nth(0).get_attribute("value")
                if value:
                    el.select_option(value)
                    filled += 1
            except Exception:
                continue
        return filled

    def fill_react_comboboxes(self) -> int:
        filled = 0
        combos = self.page.locator('input.select__input, input[role="combobox"]:not(.iti__search-input)')
        count = combos.count()
        for i in range(count):
            el = combos.nth(i)
            try:
                if not el.is_visible():
                    continue
                parent = el.locator('xpath=ancestor::div[contains(@class, "select") or contains(@class, "field")]').first
                label = _clean(parent.inner_text()).lower() if parent.count() else ""

                if "country" in label or "location" in label or "citizenship" in label or "nationality" in label:
                    target_val = "Sri Lanka"
                elif any(w in label for w in ("agree", "own words", "plagiarism", "authorized", "eligible", "privacy", "policy", "confirm", "read and agree")):
                    target_val = "Yes"
                elif "sponsorship" in label:
                    target_val = "No"
                elif any(w in label for w in ("math", "language", "performance", "grade")):
                    target_val = "Top 5%"
                elif "notice" in label or "availability" in label:
                    target_val = "2 weeks"
                elif any(w in label for w in ("disability", "disabled", "differently abled")):
                    target_val = "I don't wish to answer"
                elif any(w in label for w in ("gender", "sex")):
                    target_val = "I don't wish to answer"
                elif any(w in label for w in ("veteran", "military", "service member")):
                    target_val = "I don't wish to answer"
                elif any(w in label for w in ("hispanic", "latino", "race", "ethnicity", "racial")):
                    target_val = "I don't wish to answer"
                elif "school" in label or "university" in label:
                    target_val = "University of Greenwich"
                elif "degree" in label:
                    target_val = "Bachelor"
                elif "discipline" in label or "field of study" in label or "major" in label:
                    target_val = "Computer"
                else:
                    target_val = ""


                el.scroll_into_view_if_needed()
                el.click(timeout=2000)
                time.sleep(0.4)
                if target_val and len(target_val) > 2:
                    try:
                        el.fill(target_val)
                        time.sleep(0.3)
                    except Exception:
                        pass

                # Scope to the currently OPEN react-select menu only (avoids ITI phone dropdown)
                open_menu = self.page.locator('.select__menu')
                if open_menu.count() > 0:
                    menu = open_menu.first
                    opts = menu.locator('[class*="option"], .select__option')
                    if opts.count() > 0:
                        matched = False
                        if target_val:
                            for k in range(opts.count()):
                                try:
                                    opt_text = opts.nth(k).inner_text().strip()
                                    if target_val.lower() in opt_text.lower():
                                        opts.nth(k).click(timeout=3000)
                                        matched = True
                                        filled += 1
                                        break
                                except Exception:
                                    continue
                        if not matched:
                            try:
                                opts.first.click(timeout=3000)
                                filled += 1
                            except Exception:
                                pass
                    else:
                        # Dismiss the open menu by pressing Escape
                        try:
                            el.press("Escape")
                        except Exception:
                            pass
                else:
                    # No open menu appeared — press Escape to dismiss
                    try:
                        el.press("Escape")
                    except Exception:
                        pass
                time.sleep(0.2)
            except Exception:
                continue
        return filled


    def fill_remaining_textareas(self, cover_letter: str) -> int:
        filled = 0
        textareas = self.page.locator("textarea")
        count = textareas.count()
        for i in range(count):
            ta = textareas.nth(i)
            try:
                # Skip hidden / invisible textareas (e.g. recaptcha hidden textarea)
                if not ta.is_visible():
                    continue
                # Skip if already has a value
                try:
                    val = ta.input_value(timeout=1000).strip()
                    if val:
                        continue
                except Exception:
                    continue
                # Skip recaptcha
                el_id = (ta.get_attribute("id") or "").lower()
                el_name = (ta.get_attribute("name") or "").lower()
                if "recaptcha" in el_id or "recaptcha" in el_name or "g-recaptcha" in el_id:
                    continue

                parent = ta.locator('xpath=ancestor::div[contains(@class, "field") or contains(@class, "form")]').first
                label = _clean(parent.inner_text()).lower() if parent.count() else ""

                if "cover" in label:
                    answer = cover_letter
                elif any(w in label for w in ("degree", "bachelor", "university", "education", "gpa")):
                    answer = "BSc (Hons) in Computing, University of Greenwich. Strong focus on software engineering, distributed systems, and databases. GPA equivalent: First Class."
                elif any(w in label for w in ("high school", "rationale", "evidence", "a level", "a-level")):
                    answer = "Completed GCE Advanced Level examinations in Physical Science and Mathematics streams with top grades, demonstrating strong analytical and quantitative ability."
                elif any(w in label for w in ("linux", "open source", "ubuntu", "kernel")):
                    answer = "I use Ubuntu Linux daily for software development — running Python/FastAPI backend services, Docker containers, bash scripting, and managing open-source Git repositories. I have also contributed to public GitHub projects."
                elif any(w in label for w in ("programming language", "familiar", "language most")):
                    answer = "Python, JavaScript, TypeScript, React.js, Node.js, SQL (PostgreSQL), Bash"
                elif any(w in label for w in ("openstack", "kubernetes", "cloud", "container")):
                    answer = "I have practical experience deploying applications using Docker containers and basic Kubernetes manifests, and have explored cloud deployment on platforms such as Vercel and DigitalOcean for full-stack applications."
                elif any(w in label for w in ("experience", "project", "about you", "describe")):
                    answer = "I am a junior software engineer with hands-on experience building full-stack web applications using Python, React.js, Next.js, Node.js, FastAPI, and PostgreSQL. I am passionate about open-source software and eager to contribute to impactful global products."
                else:
                    answer = "I am an enthusiastic junior developer eager to contribute my skills in Python, React, and modern full-stack development to the team."

                ta.fill(answer, timeout=5000)
                filled += 1
            except Exception:
                continue
        return filled



    @staticmethod
    def _pick_option(el: Locator, text: str) -> str | None:
        options = el.locator("option")
        count = options.count()
        for i in range(count):
            opt = options.nth(i)
            if text.lower() in (opt.inner_text() or "").lower():
                return opt.get_attribute("value")
        return None

    def screenshot(self, job: dict, stage: str) -> str | None:
        try:
            os.makedirs(settings.screenshots_dir, exist_ok=True)
            job_id = str(job.get("_id") or "unknown")[:8].replace(":", "")
            path = os.path.join(
                settings.screenshots_dir, f"{job.get('source')}_{job_id}_{stage}.png"
            )
            self.page.screenshot(path=path, full_page=False)
            return path
        except Exception:
            return None

    def safe_submit_click(self) -> bool:
        """Clicks the first visible submit control, checking for errors after."""
        selectors = [
            'input[type="submit"]',
            'button[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'button:has-text("Continue")',
        ]
        for selector in selectors:
            loc = self.page.locator(selector).first
            if loc.count() and loc.is_visible():
                self.submit_selector = selector
                loc.click()
                self._wait_for_response()
                return True
        self.payload["submit_error"] = "no submit control found"
        return False

    def _wait_for_response(self) -> None:
        """Give the form a moment; capture visible validation errors if any."""
        time.sleep(3)
        try:
            errors = self.page.locator(
                '[class*="error-message"], [class*="errorMessage"], [class*="field__error"], [role="alert"]'
            )
            count = errors.count()
            seen_errs: set[str] = set()
            for i in range(count):
                el = errors.nth(i)
                if el.is_visible():
                    txt = _clean(el.inner_text()).strip()
                    if txt and txt not in seen_errs and len(txt) > 3:
                        seen_errs.add(txt)
                        self.payload.setdefault("validation_errors", []).append(txt[:200])
        except Exception:
            pass


    def fill_error_indicators(self) -> None:
        pass