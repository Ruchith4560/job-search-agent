"""
auto_apply.py - complete the "last mile" of the job agent.

Flow per application:
  APPROVED -> FILLING -> (unknown required fields?) -> WAITING_ANSWER -> (you reply) -> READY
  READY/APPROVED -> fill again with learned answers -> submit -> SUBMITTED
  Anything it cannot do safely (login, OTP, CAPTCHA, repeated failures) -> NEEDS_MANUAL

Rules:
  * Never invents an answer. If a REQUIRED field has no source, it emails you.
  * Optional fields with no source are left blank.
  * Dry-run by default: fills the form and screenshots it, but does NOT submit
    unless you pass --submit.

Env vars: GMAIL_USER, GMAIL_APP_PASSWORD   (use GitHub Secrets on Actions)

Usage:
  python -m agent.apply.auto_apply run              # dry run (no submit)
  python -m agent.apply.auto_apply run --submit     # real submissions
  python -m agent.apply.auto_apply check-replies
  python -m agent.apply.auto_apply status
"""
from __future__ import annotations

import argparse
import difflib
import email
import email.utils
import imaplib
import json
import os
import random
import re
import smtplib
import sqlite3
import time
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

DATA = Path(os.getenv("AGENT_DATA_DIR", "data"))
DB_PATH = Path(os.getenv("AGENT_DB_PATH", DATA / "tracker.db"))
PROFILE_PATH = Path(os.getenv("AGENT_PROFILE_PATH", "master_profile.json" if Path("master_profile.json").exists() else DATA / "master_profile.json"))
ANSWERS_PATH = DATA / "custom_answers.json"
AUTH_DIR = DATA / "auth"
STORAGE_STATE_PATH = AUTH_DIR / "storage_state.json"
USER_DATA_DIR = DATA / "browser_profile"

USER = os.getenv("GMAIL_USER", "macharuchith1@gmail.com")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

MAX_SUBMITS_PER_DAY = 10
MAX_ATTEMPTS = 3

# ---- Fixed facts (single source of truth; overrides stale values in the JSON) ----
CGPA = "9.05"
DEFAULTS = {
    "full_name": "Macha Ruchith",
    "first_name": "Macha",
    "last_name": "Ruchith",
    "email": "macharuchith1@gmail.com",
    "phone": "+916305239230",
    "linkedin": "https://linkedin.com/in/ruchith-macha",
    "github": "https://github.com/Ruchith4560",
    "college": "Anurag University",
    "degree": "B.Tech in Computer Science and Engineering",
    "branch": "Computer Science and Engineering",
    "grad_year": "2028",
    "country": "India",
    "location": "500068, Hyderabad, Telangana, India",
    "city": "Hyderabad",
    "state": "Telangana",
    "postal_code": "500068",
    "cgpa": CGPA,
    "work_auth": "Yes",
    "visa_sponsorship": "No",
    "relocate": "Yes",
    "notice_period": "Immediately available",
    "hear_about": "LinkedIn / Company Careers Page",
    "gender": "Male",
    "nationality": "Indian",
    "travel_commit": "Yes",
    "own_words": "Yes",
    "privacy_consent": "Yes",
    "math_highschool": "Top performer, achieved distinction (>95%) in high school mathematics.",
    "language_highschool": "Top performer, fluent and achieved distinction in native language.",
    "linux_stack": "Hands-on experience in Ubuntu Linux, Docker containerization, Python backend, C/C++, Shell scripting, Git, and Linux networking middleware.",
}

# label regex -> profile key. Order matters. Deliberately conservative:
# anything ambiguous falls through to "unknown" and is asked by email.
RULES = [
    (r"first\s*name|given name", "first_name"),
    (r"last\s*name|surname|family name", "last_name"),
    (r"^(full |legal )?name\b|your (full )?name|full name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|contact number|whatsapp", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"portfolio|personal (site|website)|website", "portfolio"),
    (r"authoriz\w* to work|legally (authorized|eligible|permitted)|work authorization|eligible to work", "work_auth"),
    (r"sponsor\w*|require (visa|sponsorship)|need sponsorship", "visa_sponsorship"),
    (r"notice period|how soon|earliest (start|available)|availability to join", "notice_period"),
    (r"relocat\w*|willing to relocate", "relocate"),
    (r"how did you hear|hear about (us|this)|source", "hear_about"),
    (r"cgpa|gpa|grade point", "cgpa"),
    (r"graduat\w*\s*(year|date)|year of (graduation|passing)|passing year|batch", "grad_year"),
    (r"university|college|institution|school name", "college"),
    (r"degree|qualification", "degree"),
    (r"branch|major|field of study|specializ|discipline", "branch"),
    (r"postal|zip|pin\s*code", "postal_code"),
    (r"\bstate\b|province|region", "state"),
    (r"\bcity\b|current location|where are you (based|located)|current address|street", "location"),
    (r"nationality", "nationality"),
    (r"country\s*(do you\s*)?(currently\s*)?(work|live|reside|based)?", "country"),
    (r"\bcountry\b", "country"),
    (r"meet in person|travel|commit to this|willing.*travel", "travel_commit"),
    (r"plagiarism|own words|ai generated content", "own_words"),
    (r"mathematics|math", "math_highschool"),
    (r"native language", "language_highschool"),
    (r"recruitment privacy|privacy policy|privacy notice", "privacy_consent"),
    (r"linux|ubuntu|middleware|software stacks", "linux_stack"),
]
DECLINE = re.compile(r"decline|prefer not|do not wish|don.t wish|not to (say|disclose|answer)", re.I)
SENSITIVE = re.compile(r"gender|race|ethnic|veteran|disabilit|pronoun|sexual|hispanic|caste|religion", re.I)
CONSENT = re.compile(r"agree|consent|acknowledge|privacy|terms|certify|confirm|accurate", re.I)
CONFIRM = re.compile(
    r"thank you for (applying|your application|your interest)|"
    r"application (has been |was )?(successfully )?(received|submitted|sent)|"
    r"we.ve received your application|successfully applied|application complete|"
    r"almost there! just one more step to complete your application|applythankyou",
    re.I,
)

# --------------------------------------------------------------------------- DB


def db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30.0)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS apply_state(
            job_id TEXT PRIMARY KEY, company TEXT, role TEXT, url TEXT,
            resume TEXT, cover TEXT, state TEXT, attempts INTEGER DEFAULT 0,
            token TEXT, pending TEXT, last_error TEXT, updated_at TEXT)"""
    )
    return c


def enqueue(job_id, company, role, url, resume, cover=None):
    """Call this from your existing `approve` command."""
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO apply_state(job_id,company,role,url,resume,cover,state,updated_at)"
            " VALUES(?,?,?,?,?,?,'APPROVED',?)",
            (str(job_id), company, role, url, str(resume), str(cover) if cover else None, _now()),
        )


def set_state(job_id, state, **fields):
    fields["state"] = state
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE apply_state SET {cols} WHERE job_id=?", [*fields.values(), job_id])


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ----------------------------------------------------------------- profile/answers


def _dig(obj, names):
    """Find first value for any key in `names` anywhere in a nested dict."""
    names = {n.lower() for n in names}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k.lower() in names and isinstance(v, (str, int, float)) and str(v).strip():
                    return str(v)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def load_profile() -> dict:
    p = dict(DEFAULTS)
    if PROFILE_PATH.exists():
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        p["phone"] = _dig(raw, ["phone", "mobile", "phone_number"])
        p["linkedin"] = _dig(raw, ["linkedin", "linkedin_url"])
        p["portfolio"] = _dig(raw, ["portfolio", "website", "portfolio_url"])
        p["location"] = _dig(raw, ["city", "location"])
        json_cgpa = _dig(raw, ["cgpa", "gpa"])
        if json_cgpa and json_cgpa != CGPA:
            print(f"[warn] master_profile.json has CGPA {json_cgpa}; using {CGPA}")
    return {k: v for k, v in p.items() if v}


def load_answers() -> dict:
    if ANSWERS_PATH.exists():
        return json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
    return {}


def save_answer(question: str, answer: str):
    a = load_answers()
    a[norm(question)] = answer
    ANSWERS_PATH.write_text(json.dumps(a, indent=2, ensure_ascii=False), encoding="utf-8")


def norm(s: str) -> str:
    s = re.sub(r"[_\*\u2731]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def lookup_answer(label: str, answers: dict):
    n = norm(label)
    if not n:
        return None
    index = {norm(k): v for k, v in answers.items()}
    if n in index:
        return index[n]
    close = difflib.get_close_matches(n, list(index), n=1, cutoff=0.88)
    if close:
        return index[close[0]]
    for k, v in index.items():
        if len(k) >= 15 and (k in n or n in k):
            return v
    return None


# --------------------------------------------------------------- field handling

EXTRACT_JS = r"""
() => {
  const txt = el => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g,' ').trim();
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const labelOf = el => {
    let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = txt(l); }
    if (!t && el.getAttribute('aria-labelledby'))
      t = el.getAttribute('aria-labelledby').split(' ').map(i => txt(document.getElementById(i))).join(' ').trim();
    if (!t) t = el.getAttribute('aria-label') || '';
    if (!t) { const l = el.closest('label'); if (l) t = txt(l); }
    if (!t) { const w = el.closest('fieldset, .field, .form-group, [class*=field], [class*=question], li');
      if (w) { const l = w.querySelector('legend, label'); if (l) t = txt(l); } }
    if (!t) t = el.placeholder || el.name || '';
    return t.slice(0, 300);
  };
  const isReq = (el, label) => el.required || el.getAttribute('aria-required') === 'true' || /[*\u2731]/.test(label);
  let n = 0; const out = []; const groups = {};
  document.querySelectorAll('input, textarea, select').forEach(el => {
    const type = (el.type || '').toLowerCase();
    if (['hidden','submit','button','image','reset','password'].includes(type)) return;
    if (el.disabled) return;
    if (!['file','radio','checkbox'].includes(type) && !vis(el)) return;
    const aa = 'aa' + (n++); el.setAttribute('data-aa', aa);
    const label = labelOf(el);
    if (type === 'file') { out.push({aa, kind:'file', label, required:isReq(el,label), options:[]}); return; }
    if (type === 'radio') {
      const key = el.name || aa;
      if (!groups[key]) {
        const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend');
        const w = el.closest('[class*=question], [class*=field], .form-group');
        const ql = lg ? txt(lg) : (w && w.querySelector('label, legend, .label') ? txt(w.querySelector('label, legend, .label')) : label);
        groups[key] = {aa:key, kind:'radio', label:ql, required:isReq(el, ql) || el.required, options:[]};
        out.push(groups[key]);
      }
      groups[key].options.push({aa, label: label || el.value});
      return;
    }
    if (type === 'checkbox') { out.push({aa, kind:'checkbox', label, required:isReq(el,label), options:[]}); return; }
    if (el.tagName === 'SELECT') {
      out.push({aa, kind:'select', label, required:isReq(el,label),
        options:[...el.options].filter(o => o.value !== '' ).map(o => ({label: txt(o)}))});
      return;
    }
    const combo = el.getAttribute('role') === 'combobox' || !!el.getAttribute('aria-autocomplete');
    out.push({aa, kind:'text', label, required:isReq(el,label), options:[], combo, type});
  });
  return out;
}
"""


def pick_option(value: str, labels: list[str]):
    if not labels:
        return None
    if value == "__DECLINE__":
        return next((l for l in labels if DECLINE.search(l)), None)
    v = norm(value)
    nl = {l: norm(l) for l in labels}

    # Direct Yes / No option resolution
    if v.startswith("yes"):
        for l, n in nl.items():
            if n == "yes" or n.startswith("yes"):
                return l
    if v.startswith("no"):
        for l, n in nl.items():
            if n == "no" or n.startswith("no"):
                return l

    for l, n in nl.items():
        if n == v:
            return l
    if v in ("yes", "no"):
        for l, n in nl.items():
            if n.startswith(v):
                return l
    for l, n in nl.items():
        if n and (v in n or n in v) and len(n) > 1:
            return l
    close = difflib.get_close_matches(v, list(nl.values()), n=1, cutoff=0.75)
    if close:
        return next(l for l, n in nl.items() if n == close[0])
    return None


def resolve(f: dict, profile: dict, answers: dict):
    label, low = f["label"], f["label"].lower()
    a = lookup_answer(label, answers)          # answers you taught it win
    if a is not None:
        return a
    if f["kind"] == "checkbox" and CONSENT.search(low):
        return "yes"
    if SENSITIVE.search(low):
        return "__DECLINE__"
    for pat, key in RULES:
        if re.search(pat, low) and profile.get(key):
            return profile[key]
    if CONSENT.search(low):
        return "Yes"
    return None


def fill_field(page, f: dict, value: str) -> bool:
    kind = f["kind"]
    try:
        if kind == "radio":
            opt = pick_option(value, [o["label"] for o in f["options"]])
            if not opt:
                return False
            aa = next(o["aa"] for o in f["options"] if o["label"] == opt)
            page.locator(f'[data-aa="{aa}"]').check(force=True)
            return True
        loc = page.locator(f'[data-aa="{f["aa"]}"]')
        if kind == "select":
            opt = pick_option(value, [o["label"] for o in f["options"]])
            if not opt:
                return False
            loc.select_option(label=opt)
        elif kind == "checkbox":
            loc.check(force=True)
        else:
            loc.fill(str(value))
            if f.get("combo"):            # react-select style dropdowns
                page.wait_for_timeout(500)
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
        return True
    except Exception as e:                 # noqa: BLE001
        print(f"  [fill-fail] {f['label'][:50]}: {e}")
        return False


def extract_external_apply_url(page) -> str | None:
    """Detect if the page is an aggregator/board and extract direct external application URL."""
    try:
        url = page.evaluate(r"""() => {
            const links = Array.from(document.querySelectorAll('a[href]'));
            const currentHost = window.location.hostname.toLowerCase();
            const atsHosts = ['greenhouse.io', 'lever.co', 'smartrecruiters.com', 'myworkdayjobs.com', 'ashbyhq.com', 'workable.com', 'bamboohr.com', 'breezy.hr', 'icims.com', 'phenom'];

            // 1. Direct ATS link on the page
            for (const a of links) {
                const h = (a.href || '').toLowerCase();
                if (atsHosts.some(ats => h.includes(ats))) return a.href;
            }

            // 2. Links inside apply modals (e.g. Remotive modal)
            const modal = document.querySelector('[id*="apply-modal"], .apply-modal, [class*="modal"]');
            if (modal) {
                for (const a of modal.querySelectorAll('a[href]')) {
                    const h = a.href || '';
                    if (h.startsWith('http') && !h.includes(currentHost)) return h;
                }
            }

            // 3. Links with text indicating external application
            for (const a of links) {
                const txt = ((a.innerText || a.textContent) || '').toLowerCase();
                const h = a.href || '';
                if ((txt.includes('apply on company') || txt.includes('apply externally') || txt.includes('original job') || txt.includes('apply for this job') || txt.includes('apply now')) && h.startsWith('http') && !h.includes(currentHost)) {
                    return h;
                }
            }
            return null;
        }""")
        return url
    except Exception:
        return None


def get_fields(page) -> list[dict]:
    try:
        fields = page.evaluate(EXTRACT_JS)
    except Exception:
        fields = []
    if len([f for f in fields if f["kind"] != "file"]) < 3:   # probably a landing page
        import re as _re
        for role in ("link", "button"):
            btn = page.get_by_role(role, name=_re.compile(r"^\s*apply", _re.I))
            if btn.count():
                try:
                    btn.first.click(force=True, timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    page.wait_for_timeout(2500)
                    # Clear any modal backdrop overlay if present
                    page.evaluate("() => { const o = document.querySelector('.tw-opacity-75, [class*=\"backdrop\"], [class*=\"overlay\"]'); if (o) o.remove(); }")
                    fields = page.evaluate(EXTRACT_JS)
                    break
                except Exception as e:
                    print(f"  [nav] Note clicking apply role {role}: {e}")
                    break
    return fields


def resolve_resume_path(job: dict) -> Path | None:
    """Resolve a valid, existing PDF resume for the job across Windows and Linux environments."""
    p_str = job.get("resume")
    if p_str:
        p = Path(p_str)
        if p.exists() and p.is_file():
            return p
        # Check normalized relative path if an absolute path from another OS was saved
        norm_str = str(p_str).replace("\\", "/")
        if "data/output" in norm_str:
            rel = Path(norm_str[norm_str.index("data/output"):])
            if rel.exists() and rel.is_file():
                return rel

    # Check job-specific tailored directory
    job_dir = DATA / "output" / slug(job)
    if job_dir.is_dir():
        for candidate in [job_dir / "tailored_resume.pdf", *job_dir.glob("*.pdf")]:
            if candidate.exists() and candidate.is_file():
                return candidate

    # Check general master resume in data/output or repo root
    for fb in [DATA / "output" / "resume.pdf", DATA / "resume.pdf", Path("resume.pdf")]:
        if fb.exists() and fb.is_file():
            return fb

    # Dynamically generate fallback resume PDF from master_profile.json
    try:
        from agent.profile.schema import MasterProfile
        from agent.resume.generator import ResumeGenerator
        from agent.resume.render import render_pdf
        prof_path = PROFILE_PATH if PROFILE_PATH.exists() else Path("master_profile.json")
        if prof_path.exists():
            prof = MasterProfile.model_validate_json(prof_path.read_text(encoding="utf-8"))
            gen = ResumeGenerator()
            data = gen.generate(prof, target_role=job.get("role", "Software Engineer"))
            out_pdf = DATA / "output" / "resume.pdf"
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            render_pdf(data, str(out_pdf))
            if out_pdf.exists():
                return out_pdf
    except Exception as e:
        print(f"  [warn] Could not dynamically build fallback resume: {e}")

    return None


def fill_form(page, job, profile, answers):
    """Returns (unknown_required, filled_labels)."""
    unknown, filled = [], []
    for f in get_fields(page):
        label = f["label"]
        if f["kind"] == "file":
            is_cover = bool(re.search(r"cover", label, re.I))
            if is_cover:
                path = job.get("cover")
                if not path or not Path(path).exists():
                    continue
                page.locator(f'[data-aa="{f["aa"]}"]').set_input_files(str(Path(path).resolve()))
                filled.append(label)
            else:
                resume_file = resolve_resume_path(job)
                if not resume_file or not resume_file.exists():
                    if f["required"]:
                        unknown.append({"label": label, "options": []})
                    continue
                page.locator(f'[data-aa="{f["aa"]}"]').set_input_files(str(resume_file.resolve()))
                filled.append(label)
            continue
        value = resolve(f, profile, answers)
        ok = value is not None and fill_field(page, f, value)
        if ok:
            filled.append(label)
        elif f["required"]:
            unknown.append({"label": label, "options": [o["label"] for o in f["options"]]})
        time.sleep(random.uniform(0.2, 0.7))
    return unknown, filled


# ----------------------------------------------------------------- submit logic


def has_login_wall(page) -> bool:
    if page.locator("input[type=password]:visible").count() > 0:
        return True
    url_lower = page.url.lower()
    if any(p in url_lower for p in ("/login", "/signin", "/signup", "/auth/")):
        return True
    oauth_texts = ["use linkedin", "sign in with linkedin", "continue with google", "log in to apply", "sign in to apply"]
    for b in page.locator("button, a").all():
        try:
            if b.is_visible() and any(p in b.inner_text().lower() for p in oauth_texts):
                return True
        except Exception:
            pass
    return False


def handle_oauth_sso(page) -> bool:
    """Attempts 1-click SSO (Continue with Google / Use LinkedIn) when an active session exists."""
    import re as _re
    sso_patterns = [
        r"continue with google|sign in with google|use google|log in with google",
        r"use linkedin|sign in with linkedin|continue with linkedin|apply with linkedin|easy apply",
    ]
    for pat in sso_patterns:
        regex = _re.compile(pat, _re.I)
        for role in ("button", "link"):
            btn = page.get_by_role(role, name=regex)
            if btn.count() and btn.first.is_visible():
                try:
                    print(f"  [auth] Triggering 1-click SSO ({pat})...")
                    try:
                        with page.expect_popup(timeout=4000) as popup_info:
                            btn.first.click()
                        popup = popup_info.value
                        popup.wait_for_load_state("domcontentloaded", timeout=15000)
                        popup.wait_for_timeout(2000)
                        # If on Google account chooser, select candidate's account if visible
                        acct = popup.locator(f"text='{USER}'")
                        if acct.count():
                            acct.first.click()
                            popup.wait_for_timeout(2000)
                    except Exception:
                        btn.first.click(force=True)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3500)
                    return True
                except Exception as e:
                    print(f"  [auth] SSO click attempt failed: {e}")
    return False


def login_session(target: str = "google"):
    """Launch a visible browser for candidate to log into Google / LinkedIn, then save session state.
    
    This eliminates the need to type passwords or solve 2FA on every application run,
    allowing the auto-apply agent to seamlessly bypass login walls using your real accounts.
    """
    from playwright.sync_api import sync_playwright

    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        if STORAGE_STATE_PATH.exists():
            ctx_kwargs["storage_state"] = str(STORAGE_STATE_PATH)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        targets = ["google", "linkedin"] if target == "all" else [target]
        for t in targets:
            login_url = "https://accounts.google.com" if t == "google" else "https://www.linkedin.com/login"
            print(f"\n[auth] Opening {login_url} in a visible browser.")
            print(f"[auth] Please sign into your {t.title()} account ({USER}) in the browser window.")
            print("[auth] Complete 2-Step Verification if prompted.")
            page.goto(login_url)

            try:
                input(f"\n>>> Press [ENTER] in this terminal AFTER you have logged into {t.title()}... ")
            except (EOFError, KeyboardInterrupt):
                pass

        context.storage_state(path=str(STORAGE_STATE_PATH))
        print(f"\n[auth] Successfully captured and saved authenticated session to: {STORAGE_STATE_PATH}\n")
        browser.close()


def click_submit(page) -> bool:
    import re as _re
    try:
        page.evaluate("() => { const o = document.querySelector('.tw-opacity-75, [class*=\"backdrop\"], [class*=\"overlay\"]'); if (o) o.remove(); }")
    except Exception:
        pass
    btn = page.get_by_role("button", name=_re.compile(r"submit( application)?|send application|apply", _re.I))
    if btn.count():
        try:
            btn.last.click(force=True, timeout=8000)
            return True
        except Exception as e:
            print(f"  [submit-click] Button click failed: {e}")
    alt = page.locator("button[type=submit], input[type=submit]")
    if alt.count():
        try:
            alt.last.click(force=True, timeout=8000)
            return True
        except Exception as e:
            print(f"  [submit-click] Alt submit click failed: {e}")
    return False


def wait_confirmation(page, timeout=20) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if CONFIRM.search(page.inner_text("body")):
                return True
        except Exception:                  # page navigating
            pass
        page.wait_for_timeout(1000)
    return False


def _poll_step(page, step_str: str, timeout: int = 30) -> bool:
    for _ in range(timeout):
        page.wait_for_timeout(1000)
        if step_str.lower() in page.url.lower():
            return True
    return False


def is_phenom_portal(page, job_url: str = "") -> bool:
    url_lower = (page.url + " " + job_url).lower()
    if "phenompeople.com" in url_lower or "careers.mastercard.com" in url_lower:
        return True
    try:
        if page.locator("#phoneWidget, #previousworker, input[name*='cntryFields']").count() > 0:
            return True
    except Exception:
        pass
    return False


def fill_phenom_portal(page, job: dict, profile: dict, answers: dict, submit: bool, out_dir: Path) -> str:
    """Specialized driver for Phenom People ATS (e.g. Mastercard Launch Program)."""
    # 1. Landing page check: If URL has /job/ or an Apply Now link/button
    if "/job/" in page.url.lower():
        apply_btn = page.get_by_role("link", name=re.compile(r"apply(\s*now)?", re.I))
        if apply_btn.count():
            print("  [phenom] Clicking Apply Now on landing page...")
            apply_btn.first.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

    # 2. Wait for form controls or file upload input (which is attached, often visually hidden)
    try:
        page.wait_for_selector("input[type=file]", state="attached", timeout=25000)
    except Exception:
        page.wait_for_selector("select#country", timeout=15000)
    page.wait_for_timeout(2000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 1: Upload resume
    file_inp = page.locator("input[type=file]")
    resume_file = resolve_resume_path(job)
    if file_inp.count() and resume_file and resume_file.exists():
        print(f"  [phenom] Uploading resume: {resume_file}...")
        file_inp.first.set_input_files(str(resume_file.resolve()))
        page.wait_for_timeout(7000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 1: Fill required fields
    print("  [phenom] Filling Step 1 (Personal Information)...")
    page.select_option("#country", label="India")
    page.locator("#country").dispatch_event("change")
    page.wait_for_timeout(3000)

    phone_code = page.locator("#phoneWidget\\.countryPhoneCode, select[id*='countryPhoneCode']")
    if phone_code.count():
        try:
            phone_code.first.select_option(value="IND_91")
        except Exception:
            phone_code.first.select_option(label="India (+91)")
        phone_code.first.dispatch_event("change")

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

    cb = page.locator("label:has(#emailAgreement), #emailAgreement")
    if cb.count():
        cb.first.click(force=True)

    phone_inp = page.locator("input[id='phoneWidget.phoneNumber'], input[name='phoneWidget.phoneNumber']")
    if phone_inp.count() and not phone_inp.first.input_value():
        phone_inp.first.fill(profile.get("phone", "6305239230"))
        phone_inp.first.dispatch_event("input")
        phone_inp.first.dispatch_event("change")

    fn_inp = page.locator("input[name='cntryFields.firstName'], input#firstName")
    if fn_inp.count() and not fn_inp.first.input_value():
        fn_inp.first.fill(profile.get("first_name", "Ruchith"))
        fn_inp.first.dispatch_event("input")
        fn_inp.first.dispatch_event("change")

    ln_inp = page.locator("input[name='cntryFields.lastName'], input#lastName")
    if ln_inp.count() and not ln_inp.first.input_value():
        ln_inp.first.fill(profile.get("last_name", "Macha"))
        ln_inp.first.dispatch_event("input")
        ln_inp.first.dispatch_event("change")

    em_inp = page.locator("input[name='email'], input#email")
    if em_inp.count() and not em_inp.first.input_value():
        em_inp.first.fill(profile.get("email", "macharuchith1@gmail.com"))
        em_inp.first.dispatch_event("input")
        em_inp.first.dispatch_event("change")

    addr = page.locator("input[name='cntryFields.addressLine1'], input#addressLine1")
    if addr.count() and not addr.first.input_value():
        addr.first.fill("Hyderabad, Telangana")
        addr.first.dispatch_event("input")
        addr.first.dispatch_event("change")

    page.wait_for_timeout(2000)

    # Next: Step 1 -> Step 2
    print("  [phenom] Advancing Step 1 -> Step 2...")
    page.locator("button#next").click(force=True)
    _poll_step(page, "step=2", timeout=30)
    page.wait_for_timeout(2000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 2: Work & Education
    print("  [phenom] Filling Step 2 (Work & Education)...")
    exp1_comp = page.locator("input[id='experienceData[1].companyName']")
    if exp1_comp.count() and not exp1_comp.input_value():
        exp1_comp.fill("Malai Club")
        exp1_comp.dispatch_event("input")
        exp1_comp.dispatch_event("change")

    deg_sel = page.locator("select[id='educationData[0].degree']")
    if deg_sel.count():
        deg_sel.select_option(label="Bachelors")
        deg_sel.dispatch_event("input")
        deg_sel.dispatch_event("change")
        deg_sel.dispatch_event("blur")

    field_sel = page.locator("select[id='educationData[0].fieldOfStudy']")
    if field_sel.count():
        try:
            field_sel.select_option(label="Computer Science")
            field_sel.dispatch_event("input")
            field_sel.dispatch_event("change")
            field_sel.dispatch_event("blur")
        except Exception:
            pass

    gpa_inp = page.locator("input[id='educationData[0].gradeAverage']")
    if gpa_inp.count() and not gpa_inp.input_value():
        gpa_inp.fill(CGPA)
        gpa_inp.dispatch_event("input")
        gpa_inp.dispatch_event("change")

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

    page.wait_for_timeout(2000)

    # Next: Step 2 -> Step 3
    print("  [phenom] Advancing Step 2 -> Step 3...")
    page.locator("button#next").click(force=True)
    _poll_step(page, "step=3", timeout=30)
    page.wait_for_timeout(2000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 3: Job specific questions
    print("  [phenom] Filling Step 3 (Job Specific Questions)...")
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

    page.wait_for_timeout(2000)

    # Next: Step 3 -> Step 4
    print("  [phenom] Advancing Step 3 -> Step 4...")
    page.locator("button#next").click(force=True)
    _poll_step(page, "step=4", timeout=30)
    page.wait_for_timeout(2000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 4: Conflict questionnaire
    print("  [phenom] Filling Step 4 (Conflict Questionnaire)...")
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

    page.wait_for_timeout(2000)

    # Next: Step 4 -> Step 5
    print("  [phenom] Advancing Step 4 -> Step 5...")
    page.locator("button#next").click(force=True)
    _poll_step(page, "step=5", timeout=30)
    page.wait_for_timeout(2000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 5: Applicant acknowledgment
    print("  [phenom] Filling Step 5 (Applicant Acknowledgment)...")
    ack_cb = page.locator("label:has(#termConditions_non_us\\.agreementCheck), #termConditions_non_us\\.agreementCheck")
    if ack_cb.count():
        ack_cb.first.click(force=True)
    page.wait_for_timeout(2000)

    # Next: Step 5 -> Step 6 (Review)
    print("  [phenom] Advancing Step 5 -> Step 6 (Review)...")
    page.locator("button#next").click(force=True)
    _poll_step(page, "step=6", timeout=30)
    page.wait_for_timeout(4000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 6: Review & Final Submission
    before = out_dir / "before_submit.png"
    page.screenshot(path=str(before), full_page=True)
    print(f"  [phenom] Reached Step 6 (Review). Proof screenshot saved: {before}")

    if not submit:
        set_state(job["job_id"], "READY", last_error="dry-run: filled, not submitted")
        print("  [phenom dry-run] Reached Step 6 Review successfully without submitting.")
        return "DRY_RUN_OK"

    # Submit
    submit_btn = page.locator("button[atm-id='submit-button'], button.btn-submit:not(#ph-search-backdrop), button:has-text('Submit'):not(#ph-search-backdrop)")
    if not submit_btn.count():
        submit_btn = page.locator("button#next")
    if not submit_btn.count():
        set_state(job["job_id"], "NEEDS_MANUAL", last_error="submit button not found on step 6")
        return "NEEDS_MANUAL"

    print("  [phenom submit] Clicking final Submit button on Step 6...")
    submit_btn.first.click(force=True)
    ok = wait_confirmation(page, timeout=30)
    after = out_dir / "after_submit.png"
    page.screenshot(path=str(after), full_page=True)

    if ok or "thank" in page.url.lower() or "applythankyou" in page.url.lower() or "thank" in page.inner_text("body").lower() or "received" in page.inner_text("body").lower():
        set_state(job["job_id"], "SUBMITTED", last_error=None)
        # Suppress synthetic agent emails: the official confirmation email is dispatched
        # directly by the employer (e.g. Mastercard, Workday, Greenhouse) to candidate's inbox.
        print(f"  [phenom] Application SUBMITTED successfully and confirmed! Official confirmation dispatched by {job['company']} directly to {profile.get('email', USER)}.")
        return "SUBMITTED"

    state = "NEEDS_MANUAL" if job["attempts"] + 1 >= MAX_ATTEMPTS else "READY"
    set_state(job["job_id"], state, last_error="confirmation not detected after submit")
    return state


def slug(job) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{job['company']}_{job['role']}".lower()).strip("_")[:60]


# ------------------------------------------------------------------------ email


def send_mail(subject: str, html: str, attachments: list[str] | None = None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = USER, USER, subject
    msg.set_content("Open this email in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    for p in attachments or []:
        if not p:
            continue
        p = Path(p)
        if p.exists():
            sub = "pdf" if p.suffix == ".pdf" else "png" if p.suffix == ".png" else "octet-stream"
            main = "image" if sub == "png" else "application"
            if p.suffix == ".txt":
                main, sub = "text", "plain"
            msg.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(USER, APP_PASSWORD)
            s.send_message(msg)
    except Exception as e:
        print(f"  [warn] Could not deliver email '{subject}': {e}")


def send_inquiry(job, token, questions):
    items = ""
    for i, q in enumerate(questions, 1):
        opts = f"<br><i>Options: {' | '.join(q['options'])}</i>" if q["options"] else ""
        items += f"<p><b>Q{i}.</b> {q['label']}{opts}</p>"
    html = (
        f"<h3>{job['company']} - {job['role']}</h3>"
        f"<p>The application form needs these answers. <b>Reply to this email</b> in this format "
        f"(keep the subject as it is):</p><pre>Q1: your answer\nQ2: your answer</pre>{items}"
        f"<p>Link: <a href='{job['url']}'>{job['url']}</a></p>"
    )
    send_mail(f"[Job Agent Action Required] Additional info needed for {job['company']} - "
              f"{job['role']} [JOB-{token}]", html)


def _plain_body(msg) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain":
            raw = part.get_payload(decode=True) or b""
            text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
            lines = []
            for ln in text.splitlines():
                if re.match(r"^\s*On .+ wrote:\s*$", ln) or ln.startswith(">"):
                    break
                lines.append(ln)
            return "\n".join(lines)
    return ""


def parse_answers(body: str) -> dict[int, str]:
    out = {}
    pat = r"^\s*Q\s*(\d+)\s*[:.\-)]\s*(.*?)(?=^\s*Q\s*\d+\s*[:.\-)]|\Z)"
    for m in re.finditer(pat, body, re.S | re.M):
        ans = m.group(2).strip()
        if ans:
            out[int(m.group(1))] = ans
    return out


def check_replies() -> int:
    """Read your replies, learn the answers, mark jobs READY. Returns jobs updated."""
    if not APP_PASSWORD:
        print("GMAIL_APP_PASSWORD not set")
        return 0
    updated = 0
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=10)
        M.login(USER, APP_PASSWORD)
        M.select("INBOX")
        _, ids = M.search(None, '(UNSEEN SUBJECT "JOB-")')
        for i in ids[0].split():
            _, data = M.fetch(i, "(BODY.PEEK[])")
            msg = email.message_from_bytes(data[0][1])
            if email.utils.parseaddr(msg.get("From", ""))[1].lower() != USER.lower():
                continue                               # only YOUR replies are trusted
            m = re.search(r"JOB-([0-9a-f]{8})", msg.get("Subject", ""))
            if not m:
                continue
            with db() as c:
                row = c.execute("SELECT * FROM apply_state WHERE token=? AND state='WAITING_ANSWER'",
                                (m.group(1),)).fetchone()
            if not row:
                continue
            pending = json.loads(row["pending"] or "[]")
            got = parse_answers(_plain_body(msg))      # answers are DATA, never instructions
            still = []
            for idx, q in enumerate(pending, 1):
                if idx in got:
                    save_answer(q["label"], got[idx])
                else:
                    still.append(q)
            M.store(i, "+FLAGS", "\\Seen")
            if still:
                set_state(row["job_id"], "WAITING_ANSWER", pending=json.dumps(still))
                send_inquiry(dict(row), row["token"], still)
            else:
                set_state(row["job_id"], "READY", pending="[]")
                updated += 1
        M.logout()
    except Exception as e:
        print(f"  [warn] IMAP reply check failed ({e}); continuing queue run.")
    return updated


# ------------------------------------------------------------------ main worker


def process(job: dict, submit: bool, headless: bool = True) -> str:
    try:
        from playwright.sync_api import sync_playwright

        profile, answers = load_profile(), load_answers()
        out_dir = DATA / "output" / slug(job)
        out_dir.mkdir(parents=True, exist_ok=True)
        cur_attempts = (job.get("attempts") or 0) + 1
        set_state(job["job_id"], "FILLING", attempts=cur_attempts)

        # Hydrate storage state from environment variable (e.g. GitHub secret AUTH_STORAGE_STATE) if available
        auth_secret = os.getenv("AUTH_STORAGE_STATE")
        if auth_secret and not STORAGE_STATE_PATH.exists():
            try:
                AUTH_DIR.mkdir(parents=True, exist_ok=True)
                STORAGE_STATE_PATH.write_text(auth_secret, encoding="utf-8")
                print("  [auth] Successfully initialized storage_state from AUTH_STORAGE_STATE environment secret.")
            except Exception as e:
                print(f"  [auth warn] Could not write AUTH_STORAGE_STATE: {e}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            ctx_kwargs = {
                "viewport": {"width": 1280, "height": 1600},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            }
            if STORAGE_STATE_PATH.exists():
                ctx_kwargs["storage_state"] = str(STORAGE_STATE_PATH)
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            try:
                page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                if has_login_wall(page):
                    if STORAGE_STATE_PATH.exists() and handle_oauth_sso(page):
                        page.wait_for_timeout(3000)
                    if has_login_wall(page):
                        set_state(job["job_id"], "NEEDS_MANUAL", last_error="login required: OAuth (Google / LinkedIn / account login)")
                        return "NEEDS_MANUAL"

                if is_phenom_portal(page, job.get("url", "")):
                    print(f"  [portal] Detected Phenom People ATS for {job['company']}. Executing multi-step flow...")
                    return fill_phenom_portal(page, job, profile, answers, submit, out_dir)

                unknown, filled = fill_form(page, job, profile, answers)
                print(f"  filled {len(filled)} fields, {len(unknown)} unknown required")

                # If 0 fields filled, check if page is an aggregator/board linking to external ATS
                if len(filled) == 0:
                    ext_url = extract_external_apply_url(page)
                    if ext_url and ext_url != page.url:
                        print(f"  [redirect] Detected external ATS portal: {ext_url}. Navigating...")
                        try:
                            page.goto(ext_url, wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_timeout(2500)
                            unknown, filled = fill_form(page, job, profile, answers)
                            print(f"  filled {len(filled)} fields on destination portal, {len(unknown)} unknown required")
                        except Exception as e:
                            print(f"  [redirect-fail] Could not open destination portal {ext_url}: {e}")

                # If STILL 0 fields filled, this is an informational listing, bulletin board, or requires manual apply
                if len(filled) == 0:
                    try:
                        mailto = page.evaluate("() => { const a = document.querySelector('a[href^=\"mailto:\"]'); return a ? a.href.replace('mailto:', '') : null; }")
                    except Exception:
                        mailto = None
                    if mailto:
                        last_err = f"Email application required: send resume to {mailto}"
                    else:
                        last_err = "No application form fields detected on listing page (manual apply or external link required)"
                    print(f"  [manual] {job['company']}: {last_err}")
                    set_state(job["job_id"], "NEEDS_MANUAL", last_error=last_err)
                    return "NEEDS_MANUAL"

                if has_login_wall(page):
                    if STORAGE_STATE_PATH.exists() and handle_oauth_sso(page):
                        page.wait_for_timeout(3000)
                        unknown, filled = fill_form(page, job, profile, answers)
                    if has_login_wall(page):
                        set_state(job["job_id"], "NEEDS_MANUAL", last_error="login required: OAuth (Google / LinkedIn / account login)")
                        return "NEEDS_MANUAL"

                if unknown:
                    token = job["token"] or uuid.uuid4().hex[:8]
                    set_state(job["job_id"], "WAITING_ANSWER", token=token, pending=json.dumps(unknown))
                    send_inquiry(job, token, unknown)
                    return "WAITING_ANSWER"

                before = out_dir / "before_submit.png"
                page.screenshot(path=str(before), full_page=True)
                if not submit:
                    set_state(job["job_id"], "READY", last_error="dry-run: filled, not submitted")
                    return "DRY_RUN_OK"

                if not click_submit(page):
                    set_state(job["job_id"], "NEEDS_MANUAL", last_error="submit button not found")
                    return "NEEDS_MANUAL"

                ok = wait_confirmation(page)
                after = out_dir / "after_submit.png"
                page.screenshot(path=str(after), full_page=True)
                if ok:
                    set_state(job["job_id"], "SUBMITTED", last_error=None)
                    # Suppress synthetic agent emails: the official confirmation email is dispatched
                    # directly by the employer to candidate's inbox.
                    print(f"  [submit] Application SUBMITTED and confirmed by {job['company']}! Official confirmation email dispatched by {job['company']} directly to {profile.get('email', USER)}.")
                    return "SUBMITTED"

                blocker = "captcha/verification" if page.locator(
                    "iframe[src*='captcha'], iframe[src*='turnstile'], .g-recaptcha, .h-captcha"
                ).count() else "no confirmation detected (validation error?)"
                state = "NEEDS_MANUAL" if cur_attempts >= MAX_ATTEMPTS else "READY"
                set_state(job["job_id"], state, last_error=blocker)
                if state == "NEEDS_MANUAL":
                    resume_p = resolve_resume_path(job)
                    send_mail(f"[Job Agent] Please finish manually: {job['company']} - {job['role']}",
                              f"<p>{blocker}</p><a href='{job['url']}'>{job['url']}</a>",
                              [str(resume_p) if resume_p else None, str(after)])
                return state
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:                 # noqa: BLE001
        att = (job.get("attempts") or 0) + 1
        state = "NEEDS_MANUAL" if att >= MAX_ATTEMPTS else "READY"
        set_state(job["job_id"], state, last_error=str(e)[:300])
        print(f"  [error] Exception in process({job.get('company')}): {e}")
        return "ERROR"


def submitted_today() -> int:
    with db() as c:
        return c.execute("SELECT COUNT(*) FROM apply_state WHERE state='SUBMITTED' AND updated_at LIKE ?",
                         (datetime.now().strftime("%Y-%m-%d") + "%",)).fetchone()[0]


def run_queue(submit=False, headless=True, limit=10):
    if APP_PASSWORD:
        check_replies()
    with db() as c:
        # Reset any stale FILLING states from prior interrupted/crashed runs back to APPROVED
        c.execute("UPDATE apply_state SET state='APPROVED' WHERE state='FILLING'")
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM apply_state WHERE state IN ('APPROVED','READY') ORDER BY updated_at LIMIT ?",
            (limit,))]
    if not rows:
        print("No applications pending in queue (0 in APPROVED or READY state).")
        return

    for job in rows:
        if submit and submitted_today() >= MAX_SUBMITS_PER_DAY:
            print("daily cap reached")
            break
        print(f"-> {job['company']} | {job['role']}")
        try:
            res = process(job, submit, headless)
            print("  result:", res)
        except Exception as e:
            print(f"  [error] Uncaught exception processing {job['company']}: {e}")
            set_state(job["job_id"], "NEEDS_MANUAL", last_error=str(e)[:300])
        time.sleep(random.uniform(3, 8) if headless else random.uniform(20, 60))


def status():
    with db() as c:
        for r in c.execute("SELECT state, COUNT(*) n FROM apply_state GROUP BY state"):
            print(f"{r['state']:<15}{r['n']}")


if __name__ == "__main__":
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd", choices=["run", "check-replies", "status", "login"])
        ap.add_argument("--submit", action="store_true", help="really submit (default: dry run)")
        ap.add_argument("--headed", action="store_true")
        ap.add_argument("--limit", type=int, default=10)
        ap.add_argument("--target", default="google", choices=["google", "linkedin", "all"], help="target service to log into (google, linkedin, or all)")
        a = ap.parse_args()
        if a.cmd == "run":
            run_queue(a.submit, not a.headed, a.limit)
        elif a.cmd == "check-replies":
            print("updated:", check_replies())
        elif a.cmd == "login":
            login_session(a.target)
        else:
            status()
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise
