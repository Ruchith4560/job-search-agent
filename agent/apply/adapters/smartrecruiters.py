"""SmartRecruiters ATS Portal Adapter (jobs.smartrecruiters.com)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.apply.adapters.base import BasePortalAdapter, FormFillResult, SubmissionResult


class SmartRecruitersAdapter(BasePortalAdapter):
    """Specialized driver for SmartRecruiters applicant tracking systems."""

    name: str = "smartrecruiters"

    def can_handle(self, page: Any, url: str) -> bool:
        url_lower = (url or "").lower()
        if "smartrecruiters.com" in url_lower:
            return True
        try:
            curr_url = (page.url or "").lower()
            if "smartrecruiters.com" in curr_url:
                return True
            if page.locator("form[name='st-apply-form'], .st-apply, [data-test='st-apply-container']").count() > 0:
                return True
        except Exception:
            pass
        return False

    def navigate_to_form(self, page: Any, url: str) -> bool:
        """If on a SmartRecruiters job ad page, click 'I'm interested' or 'Apply'."""
        try:
            if page.locator("form[name='st-apply-form'], #first-name-input").count() > 0:
                return True
            apply_btn = page.get_by_role("link", name=re.compile(r"i'm interested|apply|apply now", re.I))
            if not apply_btn.count():
                apply_btn = page.get_by_role("button", name=re.compile(r"i'm interested|apply|apply now", re.I))
            if apply_btn.count():
                apply_btn.first.click()
                page.wait_for_timeout(3000)
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
                file_input = page.locator("input[type=file]")
                if file_input.count():
                    file_input.first.set_input_files(str(Path(resume_path).resolve()))
                    filled.append("Resume Upload")
                    page.wait_for_timeout(2500)

            # 2. Candidate core information
            inputs = [
                ("#first-name-input, input[name='firstName']", profile.get("first_name", "Macha"), "First Name"),
                ("#last-name-input, input[name='lastName']", profile.get("last_name", "Ruchith"), "Last Name"),
                ("#email-input, input[name='email']", profile.get("email", "macharuchith1@gmail.com"), "Email"),
                ("#phone-number-input, input[name='phoneNumber']", profile.get("phone", "+916305239230"), "Phone"),
            ]

            for selector, val, label in inputs:
                loc = page.locator(selector)
                if loc.count() and val:
                    try:
                        loc.first.fill(str(val))
                        filled.append(label)
                    except Exception:
                        pass

            # 3. Location / City
            loc_inp = page.locator("#location-input, input[name='location']")
            if loc_inp.count() and not loc_inp.first.input_value():
                try:
                    loc_inp.first.fill(profile.get("city", "Hyderabad, Telangana, India"))
                    filled.append("Location")
                except Exception:
                    pass

            # 4. Social profiles (LinkedIn)
            li_inp = page.locator("input[name*='linkedin'], input[placeholder*='LinkedIn']")
            if li_inp.count() and not li_inp.first.input_value():
                try:
                    li_inp.first.fill(profile.get("linkedin", "https://linkedin.com/in/ruchith-macha"))
                    filled.append("LinkedIn")
                except Exception:
                    pass

            # 5. Multi-step progression (if 'Next' button exists)
            next_btn = page.locator("button[data-test='footer-next-button'], button:has-text('Next')")
            if next_btn.count() and next_btn.is_visible():
                next_btn.first.click()
                page.wait_for_timeout(2000)

            return FormFillResult(unknown=unknown, filled=filled, status="READY")
        except Exception as e:
            return FormFillResult(unknown=unknown, filled=filled, status="ERROR", error=str(e))

    def submit(self, page: Any) -> SubmissionResult:
        try:
            submit_btn = page.locator(
                "button[data-test='footer-submit-button'], button:has-text('Submit'), button[type=submit]:has-text('Submit application')"
            )
            if not submit_btn.count():
                submit_btn = page.locator("button[type=submit]")

            if not submit_btn.count():
                return SubmissionResult(
                    success=False,
                    status="FAILED",
                    error="SmartRecruiters submit button not found",
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
                error="Submit clicked but SmartRecruiters confirmation was not detected",
            )
        except Exception as e:
            return SubmissionResult(success=False, status="FAILED", error=str(e))

    def verify_confirmation(self, page: Any, timeout: int = 25) -> Tuple[bool, Optional[str]]:
        end = time.time() + timeout
        while time.time() < end:
            try:
                curr_url = page.url.lower()
                if "/thank-you" in curr_url or "confirmation" in curr_url:
                    return True, "Redirected to SmartRecruiters thank-you URL"
                body_text = page.inner_text("body").lower()
                if "thank you for applying" in body_text or "application was sent" in body_text:
                    return True, "SmartRecruiters application success message detected"
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False, None
