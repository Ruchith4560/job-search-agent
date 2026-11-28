"""Lever ATS Portal Adapter (jobs.lever.co)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.apply.adapters.base import BasePortalAdapter, FormFillResult, SubmissionResult


class LeverAdapter(BasePortalAdapter):
    """Specialized driver for Lever applicant tracking systems."""

    name: str = "lever"

    def can_handle(self, page: Any, url: str) -> bool:
        url_lower = (url or "").lower()
        if "lever.co" in url_lower:
            return True
        try:
            curr_url = (page.url or "").lower()
            if "lever.co" in curr_url:
                return True
            if page.locator("form#application-form, .lever-form, .postings-btn-wrapper").count() > 0:
                return True
        except Exception:
            pass
        return False

    def navigate_to_form(self, page: Any, url: str) -> bool:
        """If on a Lever posting landing page, click 'Apply for this job'."""
        try:
            if page.locator("form#application-form").count() > 0:
                return True
            apply_btn = page.get_by_role("link", name=re.compile(r"apply for this job|apply now", re.I))
            if apply_btn.count():
                apply_btn.first.click()
                page.wait_for_timeout(2000)
            return True
        except Exception:
            return False

    def fill(
        self,
        page: Any,
        job: Dict[str, Any],
        profile: Dict[str, Any],
        answers: Dict[str, Any],
    ) -> FormFillResult:
        filled: List[str] = []
        unknown: List[Dict[str, Any]] = []

        try:
            # 1. Resume upload
            resume_path = job.get("resume")
            if resume_path and Path(resume_path).exists():
                file_input = page.locator("#resume-upload-input, input[type=file][name='resume'], input[type=file]")
                if file_input.count():
                    file_input.first.set_input_files(str(Path(resume_path).resolve()))
                    filled.append("Resume Upload")
                    page.wait_for_timeout(2000)

            # 2. Basic fields
            basic_fields = [
                ("input[name='name']", profile.get("full_name", "Macha Ruchith"), "Full Name"),
                ("input[name='email']", profile.get("email", "macharuchith1@gmail.com"), "Email"),
                ("input[name='phone']", profile.get("phone", "+916305239230"), "Phone"),
                ("input[name='org']", profile.get("college", "Anurag University"), "Current Organization / University"),
            ]

            for selector, value, label in basic_fields:
                inp = page.locator(selector)
                if inp.count() and value:
                    try:
                        inp.first.fill(str(value))
                        filled.append(label)
                    except Exception:
                        pass

            # 3. Social and URL inputs
            url_fields = [
                ("input[name*='urls[LinkedIn]']", profile.get("linkedin", "https://linkedin.com/in/ruchith-macha"), "LinkedIn"),
                ("input[name*='urls[GitHub]']", profile.get("github", "https://github.com/Ruchith4560"), "GitHub"),
                ("input[name*='urls[Portfolio]']", profile.get("portfolio", profile.get("github", "")), "Portfolio"),
            ]

            for selector, value, label in url_fields:
                inp = page.locator(selector)
                if inp.count() and value:
                    try:
                        inp.first.fill(str(value))
                        filled.append(label)
                    except Exception:
                        pass

            # 4. Custom question radios (e.g. Work authorization, Relocation)
            questions = page.locator(".application-question")
            q_count = questions.count()
            for i in range(q_count):
                q = questions.nth(i)
                text = q.inner_text().lower()

                # Work Auth / Sponsorship
                if "authorized to work" in text or "legal right to work" in text:
                    yes_radio = q.locator("input[type=radio][value*='Yes'], input[type=radio][value='true']")
                    if yes_radio.count():
                        yes_radio.first.check(force=True)
                        filled.append("Work Authorization (Yes)")
                elif "require sponsorship" in text or "visa sponsorship" in text:
                    no_radio = q.locator("input[type=radio][value*='No'], input[type=radio][value='false']")
                    if no_radio.count():
                        no_radio.first.check(force=True)
                        filled.append("Visa Sponsorship (No)")
                elif "relocate" in text:
                    yes_radio = q.locator("input[type=radio][value*='Yes'], input[type=radio][value='true']")
                    if yes_radio.count():
                        yes_radio.first.check(force=True)
                        filled.append("Willing to Relocate (Yes)")

            # 5. EEOC / Voluntary demographic dropdowns
            eeoc_selects = page.locator("select[name*='eeo']")
            for i in range(eeoc_selects.count()):
                sel = eeoc_selects.nth(i)
                try:
                    sel.select_option(label=re.compile(r"decline|prefer not", re.I))
                    filled.append("EEOC Voluntary Self-ID")
                except Exception:
                    pass

            # 6. Consent checkboxes
            cbs = page.locator(".application-question input[type=checkbox][required], input[name*='consent']")
            for i in range(cbs.count()):
                cb = cbs.nth(i)
                try:
                    if not cb.is_checked():
                        cb.check(force=True)
                        filled.append("Consent Checkbox")
                except Exception:
                    pass

            return FormFillResult(unknown=unknown, filled=filled, status="READY")
        except Exception as e:
            return FormFillResult(unknown=unknown, filled=filled, status="ERROR", error=str(e))

    def submit(self, page: Any) -> SubmissionResult:
        try:
            submit_btn = page.locator("#btn-submit, button[type=submit].postings-btn, button:has-text('Submit application')")
            if not submit_btn.count():
                submit_btn = page.locator("button[type=submit], input[type=submit]")

            if not submit_btn.count():
                return SubmissionResult(
                    success=False,
                    status="FAILED",
                    error="Lever submit button not found",
                )

            submit_btn.first.click(force=True)
            ok, conf_text = self.verify_confirmation(page, timeout=25)
            if ok:
                return SubmissionResult(
                    success=True,
                    status="SUBMITTED",
                    confirmation_text=conf_text,
                )
            return SubmissionResult(
                success=False,
                status="SUBMISSION_UNKNOWN",
                error="Submit clicked but Lever /thanks confirmation was not confirmed",
            )
        except Exception as e:
            return SubmissionResult(success=False, status="FAILED", error=str(e))

    def verify_confirmation(self, page: Any, timeout: int = 25) -> Tuple[bool, Optional[str]]:
        end = time.time() + timeout
        while time.time() < end:
            try:
                curr_url = page.url.lower()
                if "/thanks" in curr_url or "confirmation" in curr_url:
                    return True, "Redirected to Lever /thanks confirmation page"
                body_text = page.inner_text("body").lower()
                if "thank you for applying" in body_text or "application has been submitted" in body_text:
                    return True, "Lever application submission confirmation text found"
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False, None
