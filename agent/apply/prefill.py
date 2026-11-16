"""Playwright-based form pre-fill engine for job application portals."""

import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from agent.apply.approval import ApprovalDecision, ApprovalGate, FieldDiff, PreFillSummary
from agent.apply.inquiries import CustomAnswersStore, PendingInquiryManager
from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile

logger = logging.getLogger(__name__)

# Sensitive terms that must never be auto-filled
SENSITIVE_PATTERNS = [
    r"salary",
    r"compensation",
    r"desired pay",
    r"minimum pay",
    r"sponsorship",
    r"authorized to work",
    r"work authorization",
    r"legally authorized",
    r"gender",
    r"race",
    r"ethnicity",
    r"veteran",
    r"disability",
    r"ssn",
    r"social security",
    r"convict",
    r"criminal",
    r"eeo",
    r"equal opportunity",
]


def is_sensitive_field(identifier: str) -> bool:
    """Check if field label/name matches sensitive compliance keywords."""
    clean = identifier.lower()
    return any(re.search(pat, clean) for pat in SENSITIVE_PATTERNS)


class FormPreFiller:
    """Pre-fills application portals (Greenhouse, Lever, generic) with verified candidate profile data."""

    def __init__(
        self,
        approval_gate: Optional[ApprovalGate] = None,
        headless: bool = False,
        answers_store: Optional[CustomAnswersStore] = None,
        inquiry_mgr: Optional[PendingInquiryManager] = None,
    ) -> None:
        """Initialize FormPreFiller.

        Args:
            approval_gate: ApprovalGate instance (defaults to interactive=True).
            headless: Whether to run the browser headlessly.
            answers_store: Optional CustomAnswersStore for learned answers.
            inquiry_mgr: Optional PendingInquiryManager for recording questions.
        """
        self.approval_gate = approval_gate or ApprovalGate(interactive=True)
        self.headless = headless
        self.answers_store = answers_store or CustomAnswersStore()
        self.inquiry_mgr = inquiry_mgr or PendingInquiryManager()

    def prefill_and_submit(
        self,
        profile: MasterProfile,
        job: Job,
        resume_pdf_path: Optional[str] = None,
        cover_letter_txt_path: Optional[str] = None,
        output_dir: str = "data/output",
        auto_decision: Optional[ApprovalDecision] = None,
    ) -> Dict[str, Any]:
        """Navigate to application page, pre-fill form fields, and pause for terminal approval.

        Args:
            profile: Source MasterProfile.
            job: Target Job.
            resume_pdf_path: Local path to tailored resume PDF.
            cover_letter_txt_path: Local path to tailored cover letter text.
            output_dir: Directory where review screenshots and manifests are saved.
            auto_decision: Optional programmatic decision (for testing/CI).

        Returns:
            Dictionary with prefill results, decision, and screenshot paths.
        """
        pi = profile.personal_info
        name_parts = pi.name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        linkedin_url = pi.links.get("linkedin") or ""
        github_url = pi.links.get("github") or ""

        cover_letter_text = ""
        if cover_letter_txt_path and Path(cover_letter_txt_path).is_file():
            cover_letter_text = Path(cover_letter_txt_path).read_text(encoding="utf-8")

        summary = PreFillSummary(
            job_id=job.id,
            company=job.company,
            title=job.title,
            application_url=job.url,
            resume_path=resume_pdf_path,
            cover_letter_path=cover_letter_txt_path,
        )

        slug = re.sub(r"[^a-zA-Z0-9]+", "_", f"{job.company}_{job.title}").strip("_").lower()[:40]
        target_dir = Path(output_dir) / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = target_dir / "prefill_review.png"

        logger.info(f"Launching browser to pre-fill application for {job.company}...")

        with sync_playwright() as p:
            browser: Browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-software-rasterizer",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context: BrowserContext = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page: Page = context.new_page()

            try:
                # 1. Navigate to target URL
                logger.info(f"Navigating to {job.url}...")
                page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)

                # 2. Check for application form or apply button
                self._locate_and_fill_form(
                    page=page,
                    first_name=first_name,
                    last_name=last_name,
                    full_name=pi.name,
                    email=pi.email or "",
                    phone=pi.phone or "",
                    location=pi.location or "",
                    linkedin_url=linkedin_url,
                    github_url=github_url,
                    cover_letter_text=cover_letter_text,
                    resume_path=resume_pdf_path,
                    profile=profile,
                    summary=summary,
                )

                # 3. Capture Pre-fill Screenshot
                page.screenshot(path=str(screenshot_path), full_page=True)
                summary.screenshot_path = str(screenshot_path.resolve())
                logger.info(f"Pre-fill review screenshot captured: {summary.screenshot_path}")

            except Exception as e:
                logger.warning(f"Error during browser interaction ({e}). Proceeding to approval review.")
                # Still record standard fields if browser failed early
                if not summary.filled_fields:
                    summary.filled_fields.append(FieldDiff(field_name="First Name", value=first_name))
                    summary.filled_fields.append(FieldDiff(field_name="Last Name", value=last_name))
                    summary.filled_fields.append(FieldDiff(field_name="Email", value=pi.email or ""))
                    summary.filled_fields.append(FieldDiff(field_name="Phone", value=pi.phone or ""))
                    if linkedin_url:
                        summary.filled_fields.append(FieldDiff(field_name="LinkedIn", value=linkedin_url))
                    if github_url:
                        summary.filled_fields.append(FieldDiff(field_name="GitHub", value=github_url))

            # 4. Check for Unanswered Questions & Pending Inquiries
            if summary.unanswered_questions:
                logger.info(
                    f"Application for {job.company} requires {len(summary.unanswered_questions)} additional question(s). "
                    "Creating inquiry and notifying candidate via email."
                )
                self.inquiry_mgr.create_or_update(
                    job_id=job.id,
                    company=job.company,
                    title=job.title,
                    portal_url=job.url,
                    questions=summary.unanswered_questions,
                )
                try:
                    from agent.config import load_config
                    from agent.notify.email_sender import EmailDigestSender

                    cfg = load_config().email
                    sender = EmailDigestSender(config=cfg)
                    sender.dispatch_inquiry_email(
                        job=job,
                        questions=summary.unanswered_questions,
                        candidate_name=pi.name,
                    )
                except Exception as e:
                    logger.warning(f"Could not dispatch inquiry email ({e})")

                browser.close()
                return {
                    "job_id": job.id,
                    "company": job.company,
                    "title": job.title,
                    "url": job.url,
                    "decision": "needs_info",
                    "status": "needs_info",
                    "unanswered_questions": summary.unanswered_questions,
                    "screenshot_review": summary.screenshot_path,
                    "filled_fields": [f.model_dump() for f in summary.filled_fields],
                    "custom_answers": [a.model_dump() for a in summary.custom_answers],
                    "sensitive_skipped": summary.sensitive_skipped,
                }

            # 5. Mandatory Approval Gate (Hard Rule 3)
            decision = self.approval_gate.request_approval(
                summary=summary,
                auto_decision=auto_decision,
            )

            result_payload = {
                "job_id": job.id,
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "decision": decision.value,
                "screenshot_review": summary.screenshot_path,
                "submission_screenshot": None,
                "filled_fields": [f.model_dump() for f in summary.filled_fields],
                "custom_answers": [a.model_dump() for a in summary.custom_answers],
                "sensitive_skipped": summary.sensitive_skipped,
            }

            if decision == ApprovalDecision.APPROVE:
                logger.info("Submitting application upon explicit user approval...")
                sub_shot = target_dir / "submission_confirmation.png"
                self._submit_form(page, sub_shot)
                result_payload["submission_screenshot"] = str(sub_shot.resolve())
                result_payload["status"] = "applied"
            elif decision == ApprovalDecision.MANUAL:
                logger.info("User requested manual completion. Application left in prefilled state.")
                result_payload["status"] = "prefilled"
                if not self.headless:
                    # Keep browser open momentarily for user inspection
                    page.wait_for_timeout(5000)
            else:
                logger.info("Application cancelled by user.")
                result_payload["status"] = "cancelled"

            browser.close()
            return result_payload

    def _locate_and_fill_form(
        self,
        page: Page,
        first_name: str,
        last_name: str,
        full_name: str,
        email: str,
        phone: str,
        location: str,
        linkedin_url: str,
        github_url: str,
        cover_letter_text: str,
        resume_path: Optional[str],
        profile: MasterProfile,
        summary: PreFillSummary,
    ) -> None:
        """Detect and fill standard and custom fields on the active page."""
        # 1. Fill First Name / Last Name / Full Name
        if self._fill_first_match(page, ["#first_name", "input[name='first_name']", "input[name='firstName']", "input[aria-label*='First Name' i]"], first_name):
            summary.filled_fields.append(FieldDiff(field_name="First Name", value=first_name))
        if self._fill_first_match(page, ["#last_name", "input[name='last_name']", "input[name='lastName']", "input[aria-label*='Last Name' i]"], last_name):
            summary.filled_fields.append(FieldDiff(field_name="Last Name", value=last_name))

        # Check for single combined "name" field if first/last not present
        if not any(f.field_name in ("First Name", "Last Name") for f in summary.filled_fields):
            if self._fill_first_match(page, ["input[name='name']", "#name", "input[aria-label*='Full Name' i]"], full_name):
                summary.filled_fields.append(FieldDiff(field_name="Full Name", value=full_name))

        # 2. Email
        if self._fill_first_match(page, ["input[type='email']", "#email", "input[name='email']"], email):
            summary.filled_fields.append(FieldDiff(field_name="Email", value=email))

        # 3. Phone
        if self._fill_first_match(page, ["input[type='tel']", "#phone", "input[name='phone']"], phone):
            summary.filled_fields.append(FieldDiff(field_name="Phone", value=phone))

        # 4. Location
        if self._fill_first_match(page, ["#job_application_location", "input[name*='location' i]", "input[placeholder*='Location' i]"], location):
            summary.filled_fields.append(FieldDiff(field_name="Location", value=location))

        # 5. LinkedIn
        if linkedin_url and self._fill_first_match(
            page,
            ["input[name*='linkedin' i]", "input[id*='linkedin' i]", "input[placeholder*='linkedin' i]"],
            linkedin_url,
        ):
            summary.filled_fields.append(FieldDiff(field_name="LinkedIn", value=linkedin_url))

        # 6. GitHub / Portfolio URL
        if github_url and self._fill_first_match(
            page,
            ["input[name*='github' i]", "input[id*='github' i]", "input[placeholder*='github' i]", "input[name*='website' i]"],
            github_url,
        ):
            summary.filled_fields.append(FieldDiff(field_name="GitHub / Website", value=github_url))

        # 7. Resume Upload
        if resume_path and Path(resume_path).is_file():
            file_inputs = page.locator("input[type='file']").all()
            for finput in file_inputs:
                try:
                    finput.set_input_files(str(Path(resume_path).resolve()))
                    summary.filled_fields.append(FieldDiff(field_name="Resume File", value=resume_path, field_type="file"))
                    break
                except Exception:
                    continue

        # 8. Cover Letter Text Area
        if cover_letter_text:
            cl_selectors = [
                "textarea[name*='cover' i]",
                "textarea[id*='cover' i]",
                "#cover_letter_text",
                "textarea[name='comments']",
            ]
            if self._fill_first_match(page, cl_selectors, cover_letter_text):
                summary.filled_fields.append(
                    FieldDiff(
                        field_name="Cover Letter",
                        value=cover_letter_text[:60] + "...",
                        field_type="textarea",
                    )
                )

        # 9. Scan for Sensitive Fields & Custom Questions
        self._scan_and_flag_fields(page, profile, summary)

    def _fill_first_match(self, page: Page, selectors: List[str], value: str) -> bool:
        """Try filling the first matching selector."""
        for sel in selectors:
            try:
                elem = page.locator(sel).first
                if elem.is_visible(timeout=1000):
                    elem.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _scan_and_flag_fields(
        self,
        page: Page,
        profile: MasterProfile,
        summary: PreFillSummary,
    ) -> None:
        """Identify sensitive fields, match learned custom answers, and collect unanswered queries."""
        try:
            inputs = page.locator("input[type='text'], textarea, select").all()
            for inp in inputs[:25]:
                try:
                    name_attr = inp.get_attribute("name") or ""
                    id_attr = inp.get_attribute("id") or ""
                    placeholder = inp.get_attribute("placeholder") or ""
                    label_text = ""

                    if id_attr:
                        label_elem = page.locator(f"label[for='{id_attr}']")
                        if label_elem.count() > 0:
                            label_text = label_elem.first.inner_text()

                    full_context = f"{name_attr} {id_attr} {placeholder} {label_text}".strip()
                    val = ""
                    try:
                        val = inp.input_value()
                    except Exception:
                        pass
                    if val:
                        continue  # Already filled

                    # 1. Match against known custom answers store
                    matched_ans = self.answers_store.find_answer(full_context)
                    if matched_ans:
                        try:
                            inp.fill(matched_ans)
                            summary.custom_answers.append(
                                FieldDiff(
                                    field_name=label_text or placeholder or name_attr or "Custom Question",
                                    value=matched_ans,
                                    field_type="text",
                                )
                            )
                            continue
                        except Exception:
                            pass

                    # 2. Check for technical custom questions (e.g. project / skills experience)
                    if any(kw in full_context.lower() for kw in ("experience", "project", "stack", "describe")):
                        if profile.projects:
                            best_proj = profile.projects[0]
                            answer = f"Built {best_proj.name} utilizing {', '.join(best_proj.stack[:4])}."
                            try:
                                inp.fill(answer)
                                summary.custom_answers.append(
                                    FieldDiff(
                                        field_name=label_text or placeholder or name_attr,
                                        value=answer,
                                        field_type="textarea",
                                    )
                                )
                                continue
                            except Exception:
                                pass

                    # 3. Check for sensitive questions or required unfilled questions needing candidate input
                    is_req = False
                    try:
                        is_req = inp.get_attribute("required") is not None or inp.get_attribute("aria-required") == "true"
                    except Exception:
                        pass

                    if is_sensitive_field(full_context) or is_req:
                        field_display = label_text or placeholder or name_attr or "Additional Information Required"
                        if field_display not in summary.sensitive_skipped:
                            summary.sensitive_skipped.append(field_display)

                        existing_labels = [q.get("label") for q in summary.unanswered_questions]
                        if field_display not in existing_labels:
                            summary.unanswered_questions.append({
                                "id": f"Q{len(summary.unanswered_questions) + 1}",
                                "label": field_display,
                                "key": full_context[:40],
                            })
                except Exception:
                    continue
        except Exception:
            pass

    def _submit_form(self, page: Page, screenshot_path: Path) -> None:
        """Execute form submission upon verified approval."""
        submit_selectors = [
            "#submit_app",
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
        ]
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    page.wait_for_timeout(3000)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    logger.info(f"Submission confirmation screenshot captured: {screenshot_path}")
                    return
            except Exception:
                continue

        # If direct submit button not found, screenshot current state
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            pass
