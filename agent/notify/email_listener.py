"""IMAP Email Reply Listener: checks Gmail inbox for replies to job inquiries, extracts answers, and completes applications."""

import email
from email.header import decode_header
import imaplib
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agent.apply.inquiries import CustomAnswersStore, PendingInquiryManager
from agent.config import EmailConfig, load_config
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job
from agent.notify.email_sender import EmailDigestSender

logger = logging.getLogger(__name__)


def clean_header_text(header_val: str) -> str:
    """Decode MIME encoded email header into clean text."""
    if not header_val:
        return ""
    decoded_parts = decode_header(header_val)
    res = []
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            res.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            res.append(str(part))
    return "".join(res)


def extract_plain_body(msg: email.message.Message) -> str:
    """Extract plain text message body from MIME email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            pass
    return body


def parse_reply_answers(text: str, questions: List[Dict[str, str]]) -> Dict[str, str]:
    """Parse answers corresponding to Q1, Q2, etc., from candidate's reply text."""
    answers: Dict[str, str] = {}
    lines = text.splitlines()

    # Strategy 1: Match Q1:, Q2:, etc.
    q_pattern = re.compile(r"^(?:Q|q)?(\d+)[\:\.\-\)]\s*(.+)$", re.IGNORECASE)
    for line in lines:
        line_clean = line.strip()
        # Skip quoted reply history lines
        if line_clean.startswith(">") or line_clean.startswith("On ") and "wrote:" in line_clean:
            continue

        m = q_pattern.match(line_clean)
        if m:
            q_num = int(m.group(1))
            val = m.group(2).strip()
            qid = f"Q{q_num}"
            answers[qid] = val

    # Strategy 2: If no Q1/Q2 prefixes, map non-empty lines sequentially to questions
    if not answers and questions:
        candidate_lines = []
        for line in lines:
            line_clean = line.strip()
            if not line_clean or line_clean.startswith(">") or line_clean.startswith("On "):
                continue
            if "wrote:" in line_clean:
                continue
            candidate_lines.append(line_clean)

        for idx, q in enumerate(questions):
            qid = q.get("id", f"Q{idx + 1}")
            if idx < len(candidate_lines):
                answers[qid] = candidate_lines[idx]

    return answers


class EmailReplyListener:
    """Connects to Gmail via IMAP and ingests replies to pending job inquiries."""

    def __init__(
        self,
        config: Optional[EmailConfig] = None,
        db: Optional[JobDatabase] = None,
        inquiry_mgr: Optional[PendingInquiryManager] = None,
        answers_store: Optional[CustomAnswersStore] = None,
    ) -> None:
        self.config = config or load_config().email
        self.db = db or JobDatabase()
        self.inquiry_mgr = inquiry_mgr or PendingInquiryManager()
        self.answers_store = answers_store or CustomAnswersStore()

    def check_for_replies(self, max_messages: int = 15) -> List[Dict[str, Any]]:
        """Query Gmail via IMAP for replies to active job inquiries.

        Returns:
            List of processed application updates.
        """
        user = os.getenv("GMAIL_USER") or self.config.smtp_user
        pw = (os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or "").replace(" ", "")

        if not user or not pw:
            logger.info("IMAP check skipped: GMAIL_APP_PASSWORD is not set.")
            return []

        pending_list = self.inquiry_mgr.get_pending()
        if not pending_list:
            logger.info("No applications currently waiting for candidate information.")
            return []

        processed: List[Dict[str, Any]] = []

        try:
            mail = imaplib.IMAP4_SSL(self.config.smtp_host.replace("smtp", "imap"), 993, timeout=15)
            mail.login(user, pw)
            mail.select("INBOX")

            # Search for emails matching [Job Agent Action Required]
            status, data = mail.search(None, '(SUBJECT "Job Agent Action Required")')
            if status != "OK" or not data or not data[0]:
                mail.logout()
                return []

            msg_ids = data[0].split()
            # Inspect the most recent matching messages
            for mid in reversed(msg_ids[-max_messages:]):
                status, msg_data = mail.fetch(mid, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = clean_header_text(msg.get("Subject", ""))
                from_addr = clean_header_text(msg.get("From", ""))
                body = extract_plain_body(msg)

                # Look for matching Job ID prefix in subject: "(ID: <prefix>)"
                id_match = re.search(r"\(ID:\s*([a-zA-Z0-9]{4,16})\)", subject, re.IGNORECASE)
                target_job_id = None
                inquiry = None

                if id_match:
                    prefix = id_match.group(1).lower()
                    for p in pending_list:
                        if p.job_id.lower().startswith(prefix):
                            target_job_id = p.job_id
                            inquiry = p
                            break

                # If no prefix in subject, match by company name in subject
                if not inquiry:
                    for p in pending_list:
                        if p.company.lower() in subject.lower():
                            target_job_id = p.job_id
                            inquiry = p
                            break

                if not inquiry or not target_job_id:
                    continue

                # Parse candidate's answers
                parsed_answers = parse_reply_answers(body, inquiry.questions)
                if not parsed_answers:
                    continue

                # Save learned answers permanently
                for q in inquiry.questions:
                    qid = q.get("id")
                    q_key = q.get("key", q.get("label", ""))
                    if qid in parsed_answers:
                        ans_val = parsed_answers[qid]
                        self.answers_store.save_answer(q_key, ans_val)

                # Mark inquiry answered and queue for real browser submission
                self.inquiry_mgr.record_answers(target_job_id, parsed_answers)
                self.db.update_status(target_job_id, "approved")

                # Update apply_state to READY so auto-apply worker submits the form
                try:
                    import sqlite3
                    with sqlite3.connect("data/tracker.db") as conn:
                        conn.execute(
                            "UPDATE apply_state SET state='READY', pending='[]', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                            (target_job_id,)
                        )
                        conn.commit()
                except Exception:
                    pass

                logger.info(
                    f"Candidate answers learned for {inquiry.company}. Application transitioned to READY for automated submission. "
                    "Artificial confirmation suppressed; authentic confirmation email will be delivered directly by employer."
                )

                processed.append({
                    "job_id": target_job_id,
                    "company": inquiry.company,
                    "title": inquiry.title,
                    "answers": parsed_answers,
                    "status": "ready",
                })

                # Remove from local pending list so we don't re-process in the same pass
                pending_list = [p for p in pending_list if p.job_id != target_job_id]

            mail.logout()

        except Exception as e:
            logger.error(f"Error checking IMAP for candidate replies: {e}", exc_info=True)

        return processed
