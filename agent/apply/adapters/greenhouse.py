"""Greenhouse ATS Portal Adapter (boards.greenhouse.io)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.apply.adapters.base import BasePortalAdapter, FormFillResult, SubmissionResult


class GreenhouseAdapter(BasePortalAdapter):
    """Specialized driver for Greenhouse applicant tracking systems."""

    name: str = "greenhouse"

    def can_handle(self, page: Any, url: str) -> bool:
        url_lower = (url or "").lower()
        if "greenhouse.io" in url_lower:
            return True
        try:
            curr_url = (page.url or "").lower()
            if "greenhouse.io" in curr_url:
                return True
            if page.locator("#application_form, #app_body, form[action*='greenhouse']").count() > 0:
                return True
        except Exception:
            pass
        return False

    def navigate_to_form(self, page: Any, url: str) -> bool:
        """If on a landing page, scroll or click Apply button to reveal #application_form."""
        try:
            # Check if form already exists
            if page.locator("#application_form, #app_body").count() > 0:
                return True

            apply_btn = page.get_by_role("link", name=re.compile(r"apply\s*(for this job|now)?", re.I))
            if not apply_btn.count():
                apply_btn = page.get_by_role("button", name=re.compile(r"apply\s*(for this job|now)?", re.I))

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
                file_input = page.locator("#resume_file, input[type=file][name*='resume'], input[type=file]")
                if file_input.count():
                    file_input.first.set_input_files(str(Path(resume_path).resolve()))
                    filled.append("Resume Upload")
                    page.wait_for_timeout(1500)

            # 2. Standard Greenhouse fields mapping
            field_mappings = [
                ("#first_name", profile.get("first_name", "Macha"), "First Name"),
                ("#last_name", profile.get("last_name", "Ruchith"), "Last Name"),
                ("#email", profile.get("email", "macharuchith1@gmail.com"), "Email"),
                ("#phone", profile.get("phone", "+916305239230"), "Phone"),
            ]

            for selector, value, label in field_mappings:
                inp = page.locator(selector)
                if inp.count() and value:
                    try:
                        inp.first.fill(str(value))
                        filled.append(label)
                    except Exception:
                        pass

            # 3. Location / Address if present
            loc_inp = page.locator("#job_application_location, input[id*='location']")
            if loc_inp.count() and not loc_inp.first.input_value():
                try:
                    loc_inp.first.fill(profile.get("city", "Hyderabad, Telangana, India"))
                    filled.append("Location")
                except Exception:
                    pass

            # 4. Social links (LinkedIn, GitHub, Website)
            url_mappings = [
                (re.compile(r"linkedin", re.I), profile.get("linkedin", "https://linkedin.com/in/ruchith-macha"), "LinkedIn"),
                (re.compile(r"github", re.I), profile.get("github", "https://github.com/Ruchith4560"), "GitHub"),
                (re.compile(r"website|portfolio", re.I), profile.get("portfolio", profile.get("github", "")), "Website"),
            ]

            custom_inputs = page.locator(".field input[type=text], .field input[type=url], input[id*='question']")
            count = custom_inputs.count()
            for i in range(count):
                inp = custom_inputs.nth(i)
                try:
                    inp_id = inp.get_attribute("id") or ""
                    inp_label = page.locator(f"label[for='{inp_id}']").inner_text() if inp_id else ""
                except Exception:
                    inp_label = ""

                for pattern, val, desc in url_mappings:
                    if pattern.search(inp_label) or pattern.search(inp_id):
                        if not inp.input_value() and val:
                            inp.fill(val)
                            filled.append(desc)

            # 5. Dropdown questions (select elements)
            selects = page.locator(".field select, select[id*='question']")
            sel_count = selects.count()
            for i in range(sel_count):
                sel = selects.nth(i)
                try:
                    sel_id = sel.get_attribute("id") or ""
                    lbl = page.locator(f"label[for='{sel_id}']").inner_text() if sel_id else sel_id
                except Exception:
                    lbl = ""

                # Work authorization / sponsorship checks
                lbl_lower = lbl.lower()
                if "authorized to work" in lbl_lower or "legally authorized" in lbl_lower:
                    try:
                        sel.select_option(label=re.compile(r"yes", re.I))
                        filled.append(lbl)
                    except Exception:
                        pass
                elif "require sponsorship" in lbl_lower or "visa sponsorship" in lbl_lower:
                    try:
                        sel.select_option(label=re.compile(r"no", re.I))
                        filled.append(lbl)
                    except Exception:
                        pass
                elif "gender" in lbl_lower or "race" in lbl_lower or "veteran" in lbl_lower or "disability" in lbl_lower:
                    try:
                        sel.select_option(label=re.compile(r"decline|prefer not", re.I))
                        filled.append(lbl)
                    except Exception:
                        pass

            # 6. Checkboxes (consent, GDPR)
            checkboxes = page.locator("input[type=checkbox][required], .field:has-text('consent') input[type=checkbox]")
            for i in range(checkboxes.count()):
                cb = checkboxes.nth(i)
                try:
                    if not cb.is_checked():
                        cb.check(force=True)
                        filled.append("Consent / Acknowledgment")
                except Exception:
                    pass

            return FormFillResult(unknown=unknown, filled=filled, status="READY")
        except Exception as e:
            return FormFillResult(unknown=unknown, filled=filled, status="ERROR", error=str(e))

    def submit(self, page: Any) -> SubmissionResult:
        try:
            submit_btn = page.locator("#submit_app, button#submit_app, button[type=submit]:has-text('Submit Application')")
            if not submit_btn.count():
                submit_btn = page.locator("button[type=submit], input[type=submit]")

            if not submit_btn.count():
                return SubmissionResult(
                    success=False,
                    status="FAILED",
                    error="Greenhouse submit button (#submit_app) not found",
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
                error="Submit clicked but Greenhouse confirmation screen was not confirmed",
            )
        except Exception as e:
            return SubmissionResult(success=False, status="FAILED", error=str(e))

    def verify_confirmation(self, page: Any, timeout: int = 25) -> Tuple[bool, Optional[str]]:
        end = time.time() + timeout
        while time.time() < end:
            try:
                curr_url = page.url.lower()
                if "/confirmation" in curr_url or "app_confirmation" in curr_url:
                    return True, "Redirected to Greenhouse confirmation URL"
                
                body_text = page.inner_text("body")
                if "thank you for applying" in body_text.lower() or "application submitted" in body_text.lower():
                    return True, "Application submitted confirmation header detected"
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False, None
