import re
import sys
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

resume_pdf = str(Path("data/output/resume.pdf").resolve())
out_dir = Path("data/output/mastercard_software_engineer_ii")
out_dir.mkdir(parents=True, exist_ok=True)

def log(msg):
    print(msg)
    sys.stdout.flush()

def poll_step(page, step_target, timeout=30):
    for s in range(timeout):
        page.wait_for_timeout(1000)
        curr = page.url.lower()
        if step_target.lower() in curr:
            log(f"  --> Reached {step_target} in {s+1}s (URL: {page.url})")
            return True
    log(f"  [TIMEOUT] {step_target} not reached. Current URL: {page.url}")
    return False

log("==================================================================")
log("       MASTERCARD LAUNCH PROGRAM - AUTO APPLICATION SUBMISSION     ")
log("==================================================================")
log("Candidate: Macha Ruchith | Anurag University | CGPA: 9.05")
log("Role: Software Engineer II (Launch Program) | Pune, India")
log(f"Resume: {resume_pdf}")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 1800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    page.on("dialog", lambda d: (log(f"[DIALOG] {d.type}: {d.message}"), d.accept()))

    # Track all network requests to catch application submission
    def on_req(req):
        if any(w in req.url.lower() for w in ["submit", "apply", "candidate", "status"]):
            log(f"  [NET REQ] {req.method} {req.url[:120]}")
    def on_resp(resp):
        if any(w in resp.url.lower() for w in ["submit", "apply", "candidate", "status"]):
            log(f"  [NET RESP] {resp.status} {resp.url[:120]}")
    page.on("request", on_req)
    page.on("response", on_resp)

    apply_url = "https://careers.mastercard.com/us/en/apply?jobSeqNo=MASRUSR290039EXTERNALENUS"
    log(f"\n[1] Navigating to apply portal: {apply_url}")
    page.goto(apply_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("select#country, input[type=file]", state="attached", timeout=45000)
    page.wait_for_timeout(2000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 1: Upload resume
    file_inp = page.locator("input[type=file]")
    if file_inp.count():
        log("[2] Uploading candidate resume...")
        file_inp.first.set_input_files(resume_pdf)
        log("    Waiting 7s for Phenom resume parser...")
        page.wait_for_timeout(7000)

    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 1: Fill required fields
    log("[3] Filling Step 1 (Personal Information)...")
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

    fn_inp = page.locator("input[name='cntryFields.firstName'], input#firstName")
    if fn_inp.count() and not fn_inp.first.input_value():
        fn_inp.first.fill("Ruchith")
        fn_inp.first.dispatch_event("input")
        fn_inp.first.dispatch_event("change")

    ln_inp = page.locator("input[name='cntryFields.lastName'], input#lastName")
    if ln_inp.count() and not ln_inp.first.input_value():
        ln_inp.first.fill("Macha")
        ln_inp.first.dispatch_event("input")
        ln_inp.first.dispatch_event("change")

    em_inp = page.locator("input[name='email'], input#email")
    if em_inp.count() and not em_inp.first.input_value():
        em_inp.first.fill("macharuchith1@gmail.com")
        em_inp.first.dispatch_event("input")
        em_inp.first.dispatch_event("change")

    addr = page.locator("input[name='cntryFields.addressLine1'], input#addressLine1")
    if addr.count() and not addr.first.input_value():
        addr.first.fill("Hyderabad, Telangana")
        addr.first.dispatch_event("input")
        addr.first.dispatch_event("change")

    page.wait_for_timeout(1500)

    # Next: Step 1 -> Step 2
    log("[4] Advancing Step 1 -> Step 2 (Work & Education)...")
    page.locator("button#next").click(force=True)
    if not poll_step(page, "step=2", timeout=30):
        log("[ERROR] Failed to reach Step 2")
        browser.close()
        sys.exit(1)

    page.wait_for_timeout(2500)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 2: Work & Education
    log("[5] Filling Step 2 (Work & Education)...")
    exp1_comp = page.locator("input[id='experienceData[1].companyName']")
    if exp1_comp.count() and not exp1_comp.input_value():
        exp1_comp.fill("Malai Club")
        exp1_comp.dispatch_event("input")
        exp1_comp.dispatch_event("change")
        exp1_comp.dispatch_event("blur")

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
        gpa_inp.fill("9.05")
        gpa_inp.dispatch_event("input")
        gpa_inp.dispatch_event("change")
        gpa_inp.dispatch_event("blur")

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

    # Next: Step 2 -> Step 3
    log("[6] Advancing Step 2 -> Step 3 (Job Questions)...")
    page.locator("button#next").click(force=True)
    if not poll_step(page, "step=3", timeout=30):
        log("[ERROR] Failed to reach Step 3")
        browser.close()
        sys.exit(1)

    page.wait_for_timeout(2500)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 3: Job specific questions
    log("[7] Filling Step 3 (Job Specific Questions)...")
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
            page.wait_for_timeout(300)

    page.wait_for_timeout(1500)

    # Next: Step 3 -> Step 4
    log("[8] Advancing Step 3 -> Step 4 (Conflict Questionnaire)...")
    page.locator("button#next").click(force=True)
    if not poll_step(page, "step=4", timeout=30):
        log("[ERROR] Failed to reach Step 4")
        browser.close()
        sys.exit(1)

    page.wait_for_timeout(2500)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 4: Conflict questionnaire
    log("[9] Filling Step 4 (Conflict Questionnaire)...")
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
            page.wait_for_timeout(200)

    page.wait_for_timeout(1500)

    # Next: Step 4 -> Step 5
    log("[10] Advancing Step 4 -> Step 5 (Applicant Acknowledgment)...")
    page.locator("button#next").click(force=True)
    if not poll_step(page, "step=5", timeout=30):
        log("[ERROR] Failed to reach Step 5")
        browser.close()
        sys.exit(1)

    page.wait_for_timeout(2500)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 5: Applicant acknowledgment
    log("[11] Filling Step 5 (Applicant Acknowledgment)...")
    ack_cb = page.locator("label:has(#termConditions_non_us\\.agreementCheck), #termConditions_non_us\\.agreementCheck")
    if ack_cb.count():
        ack_cb.first.click(force=True)
    page.wait_for_timeout(2000)

    # Next: Step 5 -> Step 6 (Review)
    log("[12] Advancing Step 5 -> Step 6 (Review)...")
    page.locator("button#next").click(force=True)
    if not poll_step(page, "step=6", timeout=30):
        log("[ERROR] Failed to reach Step 6")
        browser.close()
        sys.exit(1)

    page.wait_for_timeout(4000)
    page.evaluate("() => { const el = document.getElementById('onetrust-consent-sdk'); if (el) el.remove(); }")

    # Step 6: Review & Final Submit
    log(f"\n==================================================")
    log(f"=== STEP 6 REACHED: APPLICATION REVIEW & SUBMIT ===")
    log(f"==================================================")
    log(f"Current URL: {page.url}")
    log(f"Page Title: {page.title()}")

    before_path = out_dir / "before_submit.png"
    page.screenshot(path=str(before_path), full_page=True)
    log(f"[PROOF] Pre-submission review screenshot saved to: {before_path}")

    # Inspect the exact submit button element
    btn_data = page.evaluate("""() => {
        const prev = document.getElementById('previous');
        const container = prev ? prev.parentElement : null;
        const allBtns = Array.from(document.querySelectorAll('button, a, input[type=submit], input[type=button]')).map(b => ({
            id: b.id,
            tag: b.tagName,
            type: b.type,
            className: b.className,
            text: b.innerText ? b.innerText.trim() : (b.value || ''),
            outerHTML: b.outerHTML,
            visible: b.offsetParent !== null
        })).filter(b => b.visible);
        return {
            containerHTML: container ? container.outerHTML : null,
            visibleButtons: allBtns
        };
    }""")
    log(f"Navigation container on Step 6:\n{btn_data['containerHTML']}")
    log(f"Visible buttons on Step 6 ({len(btn_data['visibleButtons'])}):")
    for b in btn_data['visibleButtons']:
        log(f"  Tag: {b['tag']}, ID: '{b['id']}', Class: '{b['className']}', Text: '{b['text']}'")

    # Find the target submit button:
    # 1. Any button with text 'Submit'
    # 2. Any button with ID containing 'submit'
    # 3. Any button with class containing 'submit' that is not search
    # 4. Any button in the navigation container that is not 'previous'
    target_selector = None
    submit_btn = None

    for b in btn_data['visibleButtons']:
        txt = b['text'].lower()
        bid = b['id'].lower()
        bcls = b['className'].lower()
        if 'search' in bid or 'search' in bcls:
            continue
        if txt == 'submit' or 'submit' in bid:
            log(f"  --> Identified candidate: {b}")
            if b['id']:
                target_selector = f"#{b['id']}"
            else:
                target_selector = f"button:has-text('{b['text']}')"
            break

    if not target_selector:
        # Fallback: check within previous button's parent
        target_selector = "#previous ~ button, .btn-submit, button[type='submit']:not(#ph-search-backdrop)"

    log(f"\n[13] EXECUTING FINAL APPLICATION SUBMISSION...")
    log(f"     Target selector: {target_selector}")
    submit_btn = page.locator(target_selector).first
    if not submit_btn.count():
        log("[ERROR] Final Submit button not found on Step 6 Review screen!")
        browser.close()
        sys.exit(1)

    log(f"     Found submit button outerHTML: {submit_btn.evaluate('e => e.outerHTML')}")
    log("     Scrolling to submit button and clicking...")
    submit_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(1000)
    
    # Click submit button
    submit_btn.click(force=True)

    log("     Waiting 20s for submission confirmation and network responses...")
    for s in range(20):
        page.wait_for_timeout(1000)
        curr = page.url.lower()
        if "step=6" not in curr or "thank" in curr or "confirm" in curr or "status" in curr:
            log(f"     State transition detected at {s+1}s: URL={page.url}")

    # Check for confirmation indicators
    body_text = page.inner_text("body")
    after_path = out_dir / "after_submit.png"
    page.screenshot(path=str(after_path), full_page=True)
    log(f"[PROOF] Post-submission proof screenshot saved to: {after_path}")

    log(f"\nPost-Submit URL: {page.url}")
    log(f"Post-Submit Title: {page.title()}")

    # Extract confirmation headers/text
    confirmation_headers = [h.inner_text().strip() for h in page.locator("h1:visible, h2:visible, h3:visible, .thank-you, [class*='confirm']").all()]
    log(f"Confirmation headers on page: {confirmation_headers}")

    confirmed = any(term in body_text.lower() for term in [
        "thank you", "received", "submitted", "application complete", "successfully applied", "congratulations", "profile created"
    ]) or "thank" in page.url.lower() or "confirm" in page.url.lower() or "status" in page.url.lower()

    if confirmed:
        log("\n=======================================================")
        log(">>> APPLICATION SUBMISSION SUCCESSFUL & CONFIRMED! <<<")
        log("=======================================================")
    else:
        log("\n[NOTE] Page state captured. Checking body text snippet:")
        log(body_text[:600])

    # Update SQLite database
    db_path = Path("data/tracker.db")
    if db_path.exists():
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE apply_state SET state='SUBMITTED', last_error=NULL, updated_at=? WHERE job_id='mastercard_r290039'",
                (now_str,)
            )
            conn.commit()
            log(f"[DB] Updated job 'mastercard_r290039' in data/tracker.db to state: SUBMITTED")

    browser.close()
    log("\n[ALL DONE] Mastercard application process completed!")
