"""Generic fallback ATS portal adapter for custom employer application pages."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.apply.adapters.base import BasePortalAdapter, FormFillResult, SubmissionResult


EXTRACT_JS = r"""() => {
    const fields = [];
    let idx = 0;

    const findLabel = (el) => {
        let label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
        if (el.id) {
            const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (l && l.innerText) label = l.innerText + ' ' + label;
        }
        if (!label) {
            const p = el.closest('label, .form-group, .field, [class*="form-item"], [class*="field-wrapper"]');
            if (p) label = (p.innerText || '').slice(0, 150);
        }
        return label.replace(/\s+/g, ' ').trim();
    };

    const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).display !== 'none';
    };

    // Text inputs & textareas
    for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea')) {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        if (['checkbox', 'radio', 'file'].includes(type)) continue;
        if (!isVisible(el)) continue;

        const label = findLabel(el);
        // Exclude generic search boxes if they don't look like applicant forms
        if (type === 'search' || el.name === 'q' || el.id === 'search' || label.toLowerCase().includes('search jobs')) continue;

        const req = el.required || el.getAttribute('aria-required') === 'true' || /[\*]|required/i.test(label);
        el.setAttribute('data-aa', `aa-${idx}`);
        fields.push({
            aa: `aa-${idx++}`,
            kind: el.tagName.toLowerCase() === 'textarea' ? 'textarea' : 'text',
            type: type,
            label: label,
            required: req,
            options: []
        });
    }

    // Dropdowns (select elements)
    for (const el of document.querySelectorAll('select')) {
        if (!isVisible(el)) continue;
        const label = findLabel(el);
        const req = el.required || el.getAttribute('aria-required') === 'true' || /[\*]|required/i.test(label);
        const opts = Array.from(el.options).map(o => (o.text || '').trim()).filter(Boolean);
        el.setAttribute('data-aa', `aa-${idx}`);
        fields.push({
            aa: `aa-${idx++}`,
            kind: 'select',
            label: label,
            required: req,
            options: opts
        });
    }

    // File uploads
    for (const el of document.querySelectorAll('input[type=file]')) {
        const label = findLabel(el) || 'Resume / CV';
        const req = el.required || el.getAttribute('aria-required') === 'true' || /[\*]|required/i.test(label);
        el.setAttribute('data-aa', `aa-${idx}`);
        fields.push({
            aa: `aa-${idx++}`,
            kind: 'file',
            label: label,
            required: req,
            options: []
        });
    }

    return fields;
}"""


RULES = [
    (r"first\s*name|given name", "first_name"),
    (r"last\s*name|surname|family name", "last_name"),
    (r"^(full |legal )?name\b|your (full )?name|full name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|contact number|whatsapp", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"portfolio|personal (site|website)|website", "portfolio"),
    (r"authoriz\w* to work|legally (authorized|eligible|permitted)|work authorization", "work_auth"),
    (r"sponsor\w*|require (visa|sponsorship)|need sponsorship", "visa_sponsorship"),
    (r"notice period|how soon|earliest (start|available)", "notice_period"),
    (r"relocat\w*|willing to relocate", "relocate"),
    (r"how did you hear|hear about (us|this)|source", "hear_about"),
    (r"cgpa|gpa|grade point", "cgpa"),
    (r"graduat\w*\s*(year|date)|year of (graduation|passing)|passing year", "grad_year"),
    (r"university|college|institution|school name", "college"),
    (r"degree|qualification", "degree"),
    (r"branch|major|field of study", "branch"),
    (r"postal|zip|pin\s*code", "postal_code"),
    (r"\bstate\b|province|region", "state"),
    (r"\bcity\b|current location|where are you located", "location"),
    (r"gender", "gender"),
]


class GenericAdapter(BasePortalAdapter):
    """Fallback adapter applying heuristic DOM filling across standard job forms."""

    name: str = "generic"

    def can_handle(self, page: Any, url: str) -> bool:
        # Generic adapter handles any URL as the terminal fallback
        return True

    def navigate_to_form(self, page: Any, url: str) -> bool:
        """If on a landing page, attempt to click Apply button."""
        try:
            fields = page.evaluate(EXTRACT_JS)
            if len([f for f in fields if f["kind"] != "file"]) < 2:
                for role in ("link", "button"):
                    btn = page.get_by_role(role, name=re.compile(r"^\s*(apply|apply now|submit application)", re.I))
                    if btn.count():
                        btn.first.click(force=True, timeout=5000)
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                        page.wait_for_timeout(2000)
                        break
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
            fields = page.evaluate(EXTRACT_JS)
        except Exception as e:
            return FormFillResult(unknown=[], filled=[], status="ERROR", error=str(e))

        for f in fields:
            label = f["label"]
            kind = f["kind"]

            # File upload
            if kind == "file":
                is_cover = bool(re.search(r"cover", label, re.I))
                if is_cover:
                    path = job.get("cover")
                    if path and Path(path).exists():
                        try:
                            page.locator(f'[data-aa="{f["aa"]}"]').set_input_files(str(Path(path).resolve()))
                            filled.append(label)
                        except Exception:
                            pass
                else:
                    resume_path = job.get("resume")
                    if resume_path and Path(resume_path).exists():
                        try:
                            page.locator(f'[data-aa="{f["aa"]}"]').set_input_files(str(Path(resume_path).resolve()))
                            filled.append(label)
                        except Exception:
                            pass
                    elif f["required"]:
                        unknown.append({"label": label, "options": []})
                continue

            # Text / Select resolution
            val = self._resolve_value(f, profile, answers)
            if val is not None:
                ok = self._fill_field(page, f, val)
                if ok:
                    filled.append(label)
            elif f["required"]:
                unknown.append(f)

        return FormFillResult(unknown=unknown, filled=filled, status="READY")

    def _resolve_value(self, f: Dict[str, Any], profile: Dict[str, Any], answers: Dict[str, Any]) -> Optional[str]:
        lbl = f["label"].strip().lower()

        # Check previously approved answers
        for k, v in answers.items():
            if k.strip().lower() in lbl:
                return v

        # Check regex rules
        for pat, key in RULES:
            if re.search(pat, lbl, re.I):
                return str(profile.get(key, ""))
        return None

    def _fill_field(self, page: Any, f: Dict[str, Any], value: str) -> bool:
        try:
            sel = f'[data-aa="{f["aa"]}"]'
            loc = page.locator(sel)
            if not loc.count():
                return False

            kind = f["kind"]
            if kind == "select":
                try:
                    loc.select_option(label=re.compile(re.escape(str(value)), re.I))
                    loc.dispatch_event("change")
                    return True
                except Exception:
                    pass
            elif kind in ("text", "textarea"):
                loc.fill(str(value))
                loc.dispatch_event("input")
                loc.dispatch_event("change")
                return True
        except Exception:
            return False
        return False

    def submit(self, page: Any) -> SubmissionResult:
        try:
            btn = page.get_by_role("button", name=re.compile(r"submit( application)?|send application|apply", re.I))
            if btn.count():
                btn.last.click(force=True, timeout=8000)
            else:
                alt = page.locator("button[type=submit], input[type=submit]")
                if alt.count():
                    alt.last.click(force=True, timeout=8000)
                else:
                    return SubmissionResult(
                        success=False,
                        status="FAILED",
                        error="Generic submit button not found",
                    )

            ok, conf_text = self.verify_confirmation(page, timeout=20)
            if ok:
                return SubmissionResult(
                    success=True,
                    status="SUBMITTED",
                    confirmation_text=conf_text,
                )
            return SubmissionResult(
                success=False,
                status="SUBMISSION_UNKNOWN",
                error="Submit clicked but confirmation receipt was unverified",
            )
        except Exception as e:
            return SubmissionResult(success=False, status="FAILED", error=str(e))

    def verify_confirmation(self, page: Any, timeout: int = 20) -> Tuple[bool, Optional[str]]:
        end = time.time() + timeout
        confirm_pat = re.compile(
            r"thank you for (applying|your application|your interest)|"
            r"application (has been |was )?(successfully )?(received|submitted|sent)|"
            r"we.ve received your application|successfully applied",
            re.I,
        )
        while time.time() < end:
            try:
                body = page.inner_text("body")
                if confirm_pat.search(body):
                    return True, "Confirmation pattern detected in page text"
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False, None
