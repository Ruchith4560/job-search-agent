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
    "github": "https://github.com/Ruchith4560",
    "college": "Anurag University",
    "degree": "B.Tech",
    "branch": "Computer Science and Engineering",
    "grad_year": "2028",
    "country": "India",
    "cgpa": CGPA,
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
    (r"cgpa|gpa|grade point", "cgpa"),
    (r"graduat\w*\s*(year|date)|year of (graduation|passing)|passing year|batch", "grad_year"),
    (r"university|college|institution|school name", "college"),
    (r"degree|qualification", "degree"),
    (r"branch|major|field of study|specializ", "branch"),
    (r"\bcity\b|current location|where are you (based|located)", "location"),
    (r"country", "country"),
]
DECLINE = re.compile(r"decline|prefer not|do not wish|don.t wish|not to (say|disclose|answer)", re.I)
SENSITIVE = re.compile(r"gender|race|ethnic|veteran|disabilit|pronoun|sexual|hispanic|caste|religion", re.I)
CONSENT = re.compile(r"agree|consent|acknowledge|privacy|terms|certify|confirm|accurate", re.I)
CONFIRM = re.compile(
    r"thank you for (applying|your application|your interest)|"
    r"application (has been |was )?(successfully )?(received|submitted|sent)|"
    r"we.ve received your application|successfully applied|application complete",
    re.I,
)

# --------------------------------------------------------------------------- DB


def db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
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


def get_fields(page) -> list[dict]:
    fields = page.evaluate(EXTRACT_JS)
    if len([f for f in fields if f["kind"] != "file"]) < 3:   # probably a landing page
        import re as _re
        for role in ("link", "button"):
            btn = page.get_by_role(role, name=_re.compile(r"^\s*apply", _re.I))
            if btn.count():
                btn.first.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2500)
                fields = page.evaluate(EXTRACT_JS)
                break
    return fields


def fill_form(page, job, profile, answers):
    """Returns (unknown_required, filled_labels)."""
    unknown, filled = [], []
    for f in get_fields(page):
        label = f["label"]
        if f["kind"] == "file":
            is_cover = bool(re.search(r"cover", label, re.I))
            path = job["cover"] if is_cover else job["resume"]
            if not path or not Path(path).exists():
                if f["required"]:
                    unknown.append({"label": label, "options": []})
                continue
            page.locator(f'[data-aa="{f["aa"]}"]').set_input_files(path)
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
    return page.locator("input[type=password]:visible").count() > 0


def click_submit(page) -> bool:
    import re as _re
    btn = page.get_by_role("button", name=_re.compile(r"submit( application)?|send application|apply", _re.I))
    if btn.count():
        btn.last.click()
        return True
    alt = page.locator("button[type=submit], input[type=submit]")
    if alt.count():
        alt.last.click()
        return True
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
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
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
    from playwright.sync_api import sync_playwright

    profile, answers = load_profile(), load_answers()
    out_dir = DATA / "output" / slug(job)
    out_dir.mkdir(parents=True, exist_ok=True)
    set_state(job["job_id"], "FILLING", attempts=job["attempts"] + 1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(viewport={"width": 1280, "height": 1600}).new_page()
        try:
            page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            if has_login_wall(page):
                set_state(job["job_id"], "NEEDS_MANUAL", last_error="login required")
                return "NEEDS_MANUAL"

            unknown, filled = fill_form(page, job, profile, answers)
            print(f"  filled {len(filled)} fields, {len(unknown)} unknown required")

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
                send_mail(
                    f"[Application Confirmed] Successfully applied to {job['company']} - {job['role']}",
                    f"<p>Submitted {_now()}<br><a href='{job['url']}'>{job['url']}</a></p>",
                    [job["resume"], job["cover"] or "", str(after)],
                )
                return "SUBMITTED"

            blocker = "captcha/verification" if page.locator(
                "iframe[src*='captcha'], iframe[src*='turnstile'], .g-recaptcha, .h-captcha"
            ).count() else "no confirmation detected (validation error?)"
            state = "NEEDS_MANUAL" if job["attempts"] + 1 >= MAX_ATTEMPTS else "READY"
            set_state(job["job_id"], state, last_error=blocker)
            if state == "NEEDS_MANUAL":
                send_mail(f"[Job Agent] Please finish manually: {job['company']} - {job['role']}",
                          f"<p>{blocker}</p><a href='{job['url']}'>{job['url']}</a>",
                          [job["resume"], str(after)])
            return state
        except Exception as e:             # noqa: BLE001
            state = "NEEDS_MANUAL" if job["attempts"] + 1 >= MAX_ATTEMPTS else "READY"
            set_state(job["job_id"], state, last_error=str(e)[:300])
            return "ERROR"
        finally:
            browser.close()


def submitted_today() -> int:
    with db() as c:
        return c.execute("SELECT COUNT(*) FROM apply_state WHERE state='SUBMITTED' AND updated_at LIKE ?",
                         (datetime.now().strftime("%Y-%m-%d") + "%",)).fetchone()[0]


def run_queue(submit=False, headless=True, limit=10):
    if APP_PASSWORD:
        check_replies()
    with db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM apply_state WHERE state IN ('APPROVED','READY') ORDER BY updated_at LIMIT ?",
            (limit,))]
    for job in rows:
        if submit and submitted_today() >= MAX_SUBMITS_PER_DAY:
            print("daily cap reached")
            break
        print(f"-> {job['company']} | {job['role']}")
        print("  result:", process(job, submit, headless))
        time.sleep(random.uniform(20, 60))   # human-like spacing between applications


def status():
    with db() as c:
        for r in c.execute("SELECT state, COUNT(*) n FROM apply_state GROUP BY state"):
            print(f"{r['state']:<15}{r['n']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "check-replies", "status"])
    ap.add_argument("--submit", action="store_true", help="really submit (default: dry run)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "run":
        run_queue(a.submit, not a.headed, a.limit)
    elif a.cmd == "check-replies":
        print("updated:", check_replies())
    else:
        status()
