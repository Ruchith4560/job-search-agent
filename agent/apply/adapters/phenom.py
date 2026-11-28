"""Phenom People ATS Portal Adapter (e.g. Mastercard Launch Program)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.apply.adapters.base import BasePortalAdapter, FormFillResult, SubmissionResult


class PhenomAdapter(BasePortalAdapter):
    """Specialized multi-step driver for Phenom People ATS portals."""

    name: str = "phenom"

    def can_handle(self, page: Any, url: str) -> bool:
        url_lower = (url or "").lower()
        if "phenompeople.com" in url_lower or "careers.mastercard.com" in url_lower:
            return True
        try:
            curr_url = (page.url or "").lower()
            if "phenompeople.com" in curr_url or "careers.mastercard.com" in curr_url:
                return True
            if page.locator("#phoneWidget, #previousworker, input[name*='cntryFields']").count() > 0:
                return True
        except Exception:
            pass
        return False

    def _poll_step(self, page: Any, step_str: str, timeout: int = 30) -> bool:
        for _ in range(timeout):
            page.wait_for_timeout(1000)
            if step_str.lower() in page.url.lower():
                return True
        return False

    def _remove_overlays(self, page: Any) -> None:
        try:
            page.evaluate(
                "() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }"
            )
            page.evaluate(
                "() => { const o = document.querySelector('.tw-opacity-75, [class*=\"backdrop\"], [class*=\"overlay\"]'); if (o) o.remove(); }"
            )
        except Exception:
            pass

    def navigate_to_form(self, page: Any, url: str) -> bool:
        try:
            if "/job/" in page.url.lower():
                apply_btn = page.get_by_role("link", name=re.compile(r"apply(\s*now)?", re.I))
                if apply_btn.count():
                    apply_btn.first.click()
                    page.wait_for_load_state("domcontentloaded")
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
            # 1. Wait for form controls or file upload input
            try:
                page.wait_for_selector("input[type=file]", state="attached", timeout=25000)
            except Exception:
                page.wait_for_selector("select#country", timeout=15000)
            page.wait_for_timeout(2000)
            self._remove_overlays(page)

            # Step 1: Upload resume
            resume_path = job.get("resume")
            file_inp = page.locator("input[type=file]")
            if file_inp.count() and resume_path and Path(resume_path).exists():
                file_inp.first.set_input_files(str(Path(resume_path).resolve()))
                filled.append("Resume Upload")
                page.wait_for_timeout(7000)
            self._remove_overlays(page)

            # Step 1: Personal info
            page.select_option("#country", label="India")
            page.locator("#country").dispatch_event("change")
            page.wait_for_timeout(2500)
            filled.append("Country (India)")

            phone_code = page.locator("#phoneWidget\\.countryPhoneCode, select[id*='countryPhoneCode']")
            if phone_code.count():
                try:
                    phone_code.first.select_option(value="IND_91")
                except Exception:
                    phone_code.first.select_option(label="India (+91)")
                phone_code.first.dispatch_event("change")
                filled.append("Phone Code (+91)")

            dt_sel = page.locator("#deviceType")
            if dt_sel.count():
                dt_sel.select_option(value="Mobile")
                dt_sel.dispatch_event("change")

            src_sel = page.locator("#sourceType")
            if src_sel.count():
                src_sel.select_option(value="Job Board")
                src_sel.dispatch_event("change")
                page.wait_for_timeout(1000)

            app_src = page.locator("#applicantSource, select[name='applicantSource']")
            if app_src.count():
                app_src.first.select_option(label="LinkedIn")
                app_src.first.dispatch_event("change")

            pw_no = page.locator("#previousworker-No-label")
            if pw_no.count():
                pw_no.click(force=True)
                page.wait_for_timeout(500)
                filled.append("Previous Worker (No)")

            cb = page.locator("label:has(#emailAgreement), #emailAgreement")
            if cb.count():
                cb.first.click(force=True)
                filled.append("Email Agreement")

            phone_inp = page.locator("input[id='phoneWidget.phoneNumber'], input[name='phoneWidget.phoneNumber']")
            if phone_inp.count() and not phone_inp.first.input_value():
                phone_inp.first.fill(profile.get("phone", "6305239230"))
                phone_inp.first.dispatch_event("input")
                phone_inp.first.dispatch_event("change")
                filled.append("Phone Number")

            # Address fields
            addr_inp = page.locator("input[id='addressWidget.addressLine1'], input[name='addressWidget.addressLine1']")
            if addr_inp.count() and not addr_inp.first.input_value():
                addr_inp.first.fill("Anurag University, Venkatapur, Ghatkesar")
                addr_inp.first.dispatch_event("input")
                addr_inp.first.dispatch_event("change")

            city_inp = page.locator("input[id='addressWidget.city'], input[name='addressWidget.city']")
            if city_inp.count() and not city_inp.first.input_value():
                city_inp.first.fill("Hyderabad")
                city_inp.first.dispatch_event("input")
                city_inp.first.dispatch_event("change")

            pc_inp = page.locator("input[id='addressWidget.postalCode'], input[name='addressWidget.postalCode']")
            if pc_inp.count() and not pc_inp.first.input_value():
                pc_inp.first.fill("500068")
                pc_inp.first.dispatch_event("input")
                pc_inp.first.dispatch_event("change")

            page.wait_for_timeout(1500)

            # Advance: Step 1 -> Step 2
            page.locator("button#next").click(force=True)
            self._poll_step(page, "step=2", timeout=30)
            page.wait_for_timeout(2000)
            self._remove_overlays(page)

            # Step 2: Education
            edu_btn = page.locator("button#education-button")
            if edu_btn.count():
                edu_btn.click(force=True)
                page.wait_for_timeout(1000)

            sch_inp = page.locator("input[id='educationData[0].school']")
            if sch_inp.count() and not sch_inp.input_value():
                sch_inp.fill(profile.get("college", "Anurag University"))
                sch_inp.dispatch_event("input")
                sch_inp.dispatch_event("change")

            deg_inp = page.locator("input[id='educationData[0].degree']")
            if deg_inp.count() and not deg_inp.input_value():
                deg_inp.fill(profile.get("degree", "B.Tech in Computer Science and Engineering"))
                deg_inp.dispatch_event("input")
                deg_inp.dispatch_event("change")

            mjr_inp = page.locator("input[id='educationData[0].major']")
            if mjr_inp.count() and not mjr_inp.input_value():
                mjr_inp.fill("Computer Science and Engineering")
                mjr_inp.dispatch_event("input")
                mjr_inp.dispatch_event("change")

            start_date = page.locator("input[id='educationData[0].fromTo.startDate']")
            if start_date.count() and not start_date.input_value():
                start_date.fill("08/2024")
                start_date.dispatch_event("input")
                start_date.dispatch_event("change")

            end_date = page.locator("input[id='educationData[0].fromTo.endDate']")
            if end_date.count() and not end_date.input_value():
                end_date.fill("06/2028")
                end_date.dispatch_event("input")
                end_date.dispatch_event("change")

            page.wait_for_timeout(1500)
            filled.append("Education Details (Anurag University, 2024-2028)")

            # Advance: Step 2 -> Step 3
            page.locator("button#next").click(force=True)
            self._poll_step(page, "step=3", timeout=30)
            page.wait_for_timeout(2000)
            self._remove_overlays(page)

            # Step 3: Questionnaires
            for q_id, q_val in [
                ("jsqData.QUESTIONNAIRE-3-308.a", "Yes"),
                ("jsqData.QUESTIONNAIRE-3-308.b", "No"),
                ("jsqData.QUESTIONNAIRE-3-308.c", "No"),
                ("jsqData.QUESTIONNAIRE-3-308.d", "Prefer Not To Self-Identify"),
                ("jsqData.QUESTIONNAIRE-3-308.e", "No"),
            ]:
                sel = page.locator(f"select[id='{q_id}']")
                if sel.count():
                    sel.select_option(label=q_val)
                    sel.dispatch_event("change")
            filled.append("Step 3 Questionnaire")

            page.wait_for_timeout(1500)

            # Advance: Step 3 -> Step 4
            page.locator("button#next").click(force=True)
            self._poll_step(page, "step=4", timeout=30)
            page.wait_for_timeout(2000)
            self._remove_overlays(page)

            # Step 4: Conflict questionnaire
            for q_id in [
                "secondaryJsqData.QUESTIONNAIRE-3-321.a",
                "secondaryJsqData.QUESTIONNAIRE-3-321.b",
                "secondaryJsqData.QUESTIONNAIRE-3-321.c",
                "secondaryJsqData.QUESTIONNAIRE-3-321.d",
                "secondaryJsqData.QUESTIONNAIRE-3-321.e",
                "secondaryJsqData.QUESTIONNAIRE-3-321.f",
            ]:
                sel = page.locator(f"select[id='{q_id}']")
                if sel.count():
                    sel.select_option(label="No")
                    sel.dispatch_event("change")
            filled.append("Step 4 Conflicts (No)")

            page.wait_for_timeout(1500)

            # Advance: Step 4 -> Step 5
            page.locator("button#next").click(force=True)
            self._poll_step(page, "step=5", timeout=30)
            page.wait_for_timeout(2000)
            self._remove_overlays(page)

            # Step 5: Applicant acknowledgment
            ack_cb = page.locator("label:has(#termConditions_non_us\\.agreementCheck), #termConditions_non_us\\.agreementCheck")
            if ack_cb.count():
                ack_cb.first.click(force=True)
            page.wait_for_timeout(1500)
            filled.append("Step 5 Acknowledgment")

            # Advance: Step 5 -> Step 6 (Review)
            page.locator("button#next").click(force=True)
            self._poll_step(page, "step=6", timeout=30)
            page.wait_for_timeout(3000)
            self._remove_overlays(page)

            return FormFillResult(unknown=unknown, filled=filled, status="READY")
        except Exception as e:
            return FormFillResult(unknown=unknown, filled=filled, status="ERROR", error=str(e))

    def submit(self, page: Any) -> SubmissionResult:
        try:
            self._remove_overlays(page)
            submit_btn = page.locator(
                "button[atm-id='submit-button'], button.btn-submit:not(#ph-search-backdrop), button:has-text('Submit'):not(#ph-search-backdrop)"
            )
            if not submit_btn.count():
                submit_btn = page.locator("button#next")

            if not submit_btn.count():
                return SubmissionResult(
                    success=False,
                    status="FAILED",
                    error="Phenom submit button not found on Step 6",
                )

            submit_btn.first.click(force=True)
            ok, conf_text = self.verify_confirmation(page, timeout=30)
            if ok:
                return SubmissionResult(
                    success=True,
                    status="SUBMITTED",
                    confirmation_text=conf_text,
                )
            return SubmissionResult(
                success=False,
                status="SUBMISSION_UNKNOWN",
                error="Phenom submit clicked but confirmation screen not detected",
            )
        except Exception as e:
            return SubmissionResult(success=False, status="FAILED", error=str(e))

    def verify_confirmation(self, page: Any, timeout: int = 30) -> Tuple[bool, Optional[str]]:
        end = time.time() + timeout
        while time.time() < end:
            try:
                curr_url = page.url.lower()
                if "thank" in curr_url or "applythankyou" in curr_url or "confirmed" in curr_url:
                    return True, "Phenom thank-you URL reached"
                body_text = page.inner_text("body").lower()
                if "thank you for applying" in body_text or "application has been received" in body_text:
                    return True, "Phenom application receipt message confirmed"
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False, None
