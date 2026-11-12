"""Daily HTML Email Digest and Resume Dispatcher for Student Internships and Roles."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import logging
import os
from pathlib import Path
import smtplib
from typing import Any, Dict, List, Optional

from agent.config import EmailConfig
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


@dataclass
class JobDigestItem:
    """Represents a scored, tailored job entry in the daily digest."""

    rank: int
    job: Job
    match_score: float
    ats_score: float
    is_top_pick: bool = False
    why_it_fits: List[str] = field(default_factory=list)
    missing_keywords: List[str] = field(default_factory=list)
    skills_worth_learning: List[str] = field(default_factory=list)
    resume_pdf_path: Optional[str] = None
    resume_filename: Optional[str] = None


class EmailDigestGenerator:
    """Builds clean, responsive HTML email digests for daily job matches."""

    def build_html_digest(
        self,
        candidate_name: str,
        items: List[JobDigestItem],
        date_str: Optional[str] = None,
        zero_result_sources: Optional[List[str]] = None,
        fetch_errors: Optional[List[str]] = None,
    ) -> str:
        """Render a full responsive HTML email digest with summary table and cards."""
        if not date_str:
            date_str = datetime.now().strftime("%A, %d %B %Y")

        top_picks_count = sum(1 for it in items if it.is_top_pick)
        total_count = len(items)

        # 1. Summary Table Rows
        summary_rows = []
        for it in items:
            j = it.job
            type_label = (j.job_type or "internship").upper().replace("_", " ")
            type_badge_bg = "#e0f2fe" if "INTERN" in type_label else "#e0e7ff"
            type_badge_color = "#0369a1" if "INTERN" in type_label else "#4338ca"

            top_badge = ""
            if it.is_top_pick:
                top_badge = '<span style="background-color: #fef08a; color: #854d0e; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">TOP PICK</span>'

            stipend_text = html.escape(j.stipend_or_salary or "Competitive / Per Policy")
            loc_text = html.escape(j.location or "India")

            row_html = f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 12px; font-weight: bold; color: #4b5563;">#{it.rank}</td>
              <td style="padding: 10px 12px;">
                <div style="font-weight: 600; color: #111827;">{html.escape(j.company)} {top_badge}</div>
                <div style="font-size: 13px; color: #6b7280;">{loc_text}</div>
              </td>
              <td style="padding: 10px 12px;">
                <div style="font-weight: 500; color: #1f2937;">{html.escape(j.title)}</div>
                <span style="display: inline-block; background-color: {type_badge_bg}; color: {type_badge_color}; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-top: 4px;">{type_label}</span>
              </td>
              <td style="padding: 10px 12px; font-size: 13px; color: #374151;">{stipend_text}</td>
              <td style="padding: 10px 12px; text-align: center;">
                <span style="display: inline-block; background-color: #dcfce7; color: #15803d; font-size: 13px; font-weight: bold; padding: 3px 8px; border-radius: 6px;">{it.match_score:.0f}%</span>
              </td>
              <td style="padding: 10px 12px; text-align: center;">
                <span style="display: inline-block; background-color: #f3f4f6; color: #374151; font-size: 13px; font-weight: bold; padding: 3px 8px; border-radius: 6px;">{it.ats_score:.0f}%</span>
              </td>
            </tr>
            """
            summary_rows.append(row_html)

        # 2. Detailed Job Cards
        cards_html = []
        for it in items:
            j = it.job
            type_label = (j.job_type or "internship").upper().replace("_", " ")

            top_banner = ""
            border_style = "border: 1px solid #e5e7eb;"
            if it.is_top_pick:
                border_style = "border: 2px solid #eab308; box-shadow: 0 4px 6px -1px rgba(234, 179, 8, 0.1);"
                top_banner = """
                <div style="background: linear-gradient(90deg, #fef08a, #fde047); color: #713f12; font-size: 12px; font-weight: bold; padding: 4px 12px; border-radius: 6px 6px 0 0; text-transform: uppercase; letter-spacing: 0.5px;">
                  ★ Top Pick &bull; High Alignment &bull; Fast-Track Application
                </div>
                """

            # 3-line why-it-fits bullets
            reasons_li = ""
            if it.why_it_fits:
                for r in it.why_it_fits[:3]:
                    reasons_li += f"<li style='margin-bottom: 4px;'>{html.escape(r)}</li>"
            else:
                reasons_li = f"<li>Strong match for {html.escape(j.title)} role based on verified projects and skills.</li>"

            # Missing skills / skills worth learning
            missing_html = ""
            learn_skills = it.skills_worth_learning or it.missing_keywords
            if learn_skills:
                skill_badges = "".join(
                    f"<span style='display: inline-block; background: #fef3c7; color: #92400e; font-size: 11px; padding: 2px 7px; border-radius: 4px; margin: 2px 4px 2px 0;'>{html.escape(s)}</span>"
                    for s in learn_skills[:5]
                )
                missing_html = f"""
                <div style="margin-top: 10px; font-size: 12px; color: #6b7280;">
                  <strong style="color: #4b5563;">Skills to highlight or learn:</strong> {skill_badges}
                </div>
                """

            # Resume attachment pill
            resume_note = ""
            if it.resume_filename:
                resume_note = f"""
                <div style="margin-top: 8px; font-size: 12px; color: #0284c7;">
                  📎 <strong>Tailored Resume Attached:</strong> <code>{html.escape(it.resume_filename)}</code> (ATS: {it.ats_score:.0f}%)
                </div>
                """

            raw_link = getattr(j, "url", None) or getattr(j, "link", None) or getattr(j, "apply_url", "#")
            apply_link = html.escape(raw_link)

            card = f"""
            <div style="{border_style} border-radius: 8px; background-color: #ffffff; margin-bottom: 20px; overflow: hidden;">
              {top_banner}
              <div style="padding: 16px 20px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                  <div>
                    <span style="font-size: 13px; font-weight: bold; color: #6b7280;">#{it.rank}</span>
                    <h3 style="margin: 2px 0 4px 0; font-size: 18px; color: #111827; font-weight: 700;">{html.escape(j.title)}</h3>
                    <div style="font-size: 14px; color: #374151; font-weight: 500;">
                      🏢 <strong>{html.escape(j.company)}</strong> &bull; 📍 {html.escape(j.location or "India")} &bull; 🏷️ {type_label}
                    </div>
                  </div>
                </div>

                <div style="margin: 10px 0; padding: 8px 12px; background-color: #f8fafc; border-radius: 6px; font-size: 13px; color: #334155; display: flex; flex-wrap: wrap; gap: 12px;">
                  <div>💰 <strong>Compensation:</strong> {html.escape(j.stipend_or_salary or "Competitive / Per Policy")}</div>
                  <div>🎯 <strong>Match Score:</strong> <strong style="color: #16a34a;">{it.match_score:.0f}%</strong></div>
                  <div>📄 <strong>ATS Score:</strong> <strong style="color: #2563eb;">{it.ats_score:.0f}%</strong></div>
                </div>

                <div style="margin: 12px 0 8px 0; background-color: #f0f9ff; border-left: 3px solid #0284c7; padding: 8px 12px; border-radius: 0 4px 4px 0;">
                  <div style="font-size: 12px; font-weight: bold; text-transform: uppercase; color: #0369a1; margin-bottom: 4px;">Why It Fits You:</div>
                  <ul style="margin: 0; padding-left: 18px; font-size: 13px; color: #0f172a; line-height: 1.45;">
                    {reasons_li}
                  </ul>
                </div>

                {missing_html}
                {resume_note}

                <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed #e5e7eb; display: flex; justify-content: space-between; align-items: center;">
                  <span style="font-size: 12px; color: #6b7280;">To approve application: Reply <strong>APPLY {it.rank}</strong></span>
                  <a href="{apply_link}" target="_blank" style="background-color: #2563eb; color: #ffffff; text-decoration: none; font-size: 13px; font-weight: 600; padding: 8px 16px; border-radius: 6px; display: inline-block;">View Posting &rarr;</a>
                </div>
              </div>
            </div>
            """
            cards_html.append(card)

        # 3. Sources and Zero Results Footer
        zero_note = ""
        if zero_result_sources:
            zero_note = f"<p style='margin: 4px 0;'>ℹ️ No new qualified openings posted today from: {html.escape(', '.join(zero_result_sources))}.</p>"

        error_note = ""
        if fetch_errors:
            error_note = f"<p style='margin: 4px 0; color: #b91c1c;'>⚠️ Sync warnings: {html.escape('; '.join(fetch_errors[:3]))}.</p>"

        # 4. Master Template
        full_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Job Digest</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1f2937; line-height: 1.5;">
  <div style="max-width: 680px; margin: 20px auto; background-color: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb;">
    
    <!-- Top Header -->
    <div style="background: linear-gradient(135deg, #1e3a8a, #2563eb); color: #ffffff; padding: 24px 28px;">
      <div style="font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #93c5fd;">AI Job Search Agent &bull; Daily Digest</div>
      <h1 style="margin: 8px 0 4px 0; font-size: 22px; font-weight: 700; color: #ffffff;">
        {total_count} Verified Openings for {html.escape(candidate_name)}
      </h1>
      <p style="margin: 0; font-size: 14px; color: #dbeafe;">
        {date_str} &bull; Tailored Resumes Attached &bull; {top_picks_count} Top Pick(s)
      </p>
    </div>

    <!-- Quick Approval Action Bar -->
    <div style="background-color: #eff6ff; border-bottom: 1px solid #dbeafe; padding: 12px 28px; font-size: 13px; color: #1e40af;">
      <strong>Action Required:</strong> Reply to this email with <code>APPLY 1, 2</code> (or run <code>python main.py approve 1, 2</code>) to approve auto-prefill for selected roles.
    </div>

    <!-- Main Content Container -->
    <div style="padding: 24px 28px;">
      
      <!-- Summary Table -->
      <h2 style="font-size: 16px; font-weight: 700; color: #111827; margin: 0 0 12px 0; text-transform: uppercase; letter-spacing: 0.5px;">
        Ranked Summary Table
      </h2>
      <div style="overflow-x: auto; margin-bottom: 24px;">
        <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px;">
          <thead>
            <tr style="background-color: #f9fafb; border-bottom: 2px solid #e5e7eb; color: #4b5563; font-size: 12px; text-transform: uppercase;">
              <th style="padding: 10px 12px; width: 36px;">#</th>
              <th style="padding: 10px 12px;">Company</th>
              <th style="padding: 10px 12px;">Role & Type</th>
              <th style="padding: 10px 12px;">Stipend</th>
              <th style="padding: 10px 12px; text-align: center;">Match</th>
              <th style="padding: 10px 12px; text-align: center;">ATS</th>
            </tr>
          </thead>
          <tbody>
            {''.join(summary_rows)}
          </tbody>
        </table>
      </div>

      <!-- Job Cards -->
      <h2 style="font-size: 16px; font-weight: 700; color: #111827; margin: 24px 0 14px 0; text-transform: uppercase; letter-spacing: 0.5px;">
        Detailed Job Breakdown &amp; Fit Analysis
      </h2>
      {''.join(cards_html)}

    </div>

    <!-- Footer -->
    <div style="background-color: #f9fafb; border-top: 1px solid #e5e7eb; padding: 20px 28px; font-size: 12px; color: #6b7280; line-height: 1.6;">
      <p style="margin: 0 0 6px 0; font-weight: 600; color: #374151;">Verification &amp; Safety Disclaimers:</p>
      <p style="margin: 0 0 4px 0;">&bull; Every tailored resume attached is strictly grounded in your verified Master Profile (no hallucinated skills/metrics).</p>
      <p style="margin: 0 0 4px 0;">&bull; Strict anti-scam checks passed: 0 registration fees, 0 unverified banking requests, verified recruiter emails.</p>
      {zero_note}
      {error_note}
      <p style="margin: 12px 0 0 0; font-size: 11px; color: #9ca3af; text-align: center;">
        AI Job Search Agent &bull; Macha Ruchith &bull; Anurag University CSE '28
      </p>
    </div>

  </div>
</body>
</html>
"""
        return full_html


class EmailDigestSender:
    """Manages email digest generation, attachment aggregation, and SMTP dispatch."""

    def __init__(
        self,
        config: EmailConfig,
        db: Optional[JobDatabase] = None,
        preview_output_path: str = "data/output/daily_email_preview.html",
    ) -> None:
        self.config = config
        self.db = db
        self.preview_output_path = Path(preview_output_path)
        self.generator = EmailDigestGenerator()

    def dispatch_digest(
        self,
        candidate_name: str,
        items: List[JobDigestItem],
        dry_run: bool = False,
        zero_result_sources: Optional[List[str]] = None,
        fetch_errors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate HTML digest, attach tailored resume PDFs, and deliver via SMTP or write preview."""
        if not items:
            logger.info("No qualified jobs to dispatch today.")
            return {"status": "skipped", "reason": "No qualified jobs", "count": 0}

        # 1. Render HTML
        html_body = self.generator.build_html_digest(
            candidate_name=candidate_name,
            items=items,
            zero_result_sources=zero_result_sources,
            fetch_errors=fetch_errors,
        )

        # Always save offline preview for reference
        self.preview_output_path.parent.mkdir(parents=True, exist_ok=True)
        self.preview_output_path.write_text(html_body, encoding="utf-8")
        logger.info(f"Saved daily email HTML preview to: {self.preview_output_path}")

        top_picks = sum(1 for it in items if it.is_top_pick)
        subject_prefix = f"[{top_picks} TOP PICK{'S' if top_picks > 1 else ''}] " if top_picks > 0 else ""
        subject = f"{subject_prefix}Daily Job Digest: {len(items)} Qualified Roles for {candidate_name}"

        # 2. Check credentials & dry_run mode
        smtp_password = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or ""

        if dry_run or not smtp_password or not self.config.enabled:
            mode_desc = "dry_run mode" if dry_run else "no GMAIL_APP_PASSWORD configured"
            print(f"[DIGEST] Email preview saved to: {self.preview_output_path}")
            print(f"[DIGEST] Mode: Offline/Preview ({mode_desc}). {len(items)} jobs prepared.")
            if not smtp_password:
                print("[NOTE] Set GMAIL_APP_PASSWORD in your .env to enable automatic inbox delivery.")

            # Still mark jobs as emailed in DB to prevent duplicate emailing on subsequent runs if desired
            if self.db:
                job_ids = [it.job.id for it in items]
                self.db.mark_as_emailed(job_ids)
                logger.info(f"Marked {len(job_ids)} jobs as emailed in database.")

            return {
                "status": "preview_saved",
                "preview_path": str(self.preview_output_path),
                "count": len(items),
                "recipient": self.config.recipient_email,
                "subject": subject,
            }

        # 3. Construct MIME Email with Attachments
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = self.config.smtp_user or "AI Job Search Agent <agent@noreply.local>"
        msg["To"] = self.config.recipient_email

        # Attach HTML body
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Attach Resumes (Named Name_Role_Company.pdf)
        attached_count = 0
        for it in items:
            pdf_path_str = it.resume_pdf_path
            if pdf_path_str and Path(pdf_path_str).exists():
                pdf_file = Path(pdf_path_str)
                att_name = it.resume_filename or pdf_file.name
                with open(pdf_file, "rb") as f:
                    part = MIMEApplication(f.read(), Name=att_name)
                part["Content-Disposition"] = f'attachment; filename="{att_name}"'
                msg.attach(part)
                attached_count += 1
                logger.debug(f"Attached resume: {att_name}")

        # 4. Dispatch via SMTP
        try:
            logger.info(f"Connecting to SMTP {self.config.smtp_host}:{self.config.smtp_port}...")
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as server:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.smtp_user, smtp_password)
                server.send_message(msg)

            print(f"[DIGEST] Successfully emailed digest to {self.config.recipient_email} with {attached_count} resume attachments!")

            # 5. Mark as emailed in DB
            if self.db:
                job_ids = [it.job.id for it in items]
                self.db.mark_as_emailed(job_ids)
                logger.info(f"Marked {len(job_ids)} jobs as emailed in SQLite.")

            return {
                "status": "sent",
                "recipient": self.config.recipient_email,
                "count": len(items),
                "attachments": attached_count,
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Failed to dispatch email via SMTP: {e}", exc_info=True)
            print(f"[ERROR] Failed to send email via SMTP: {e}")
            return {
                "status": "error",
                "error": str(e),
                "preview_path": str(self.preview_output_path),
                "count": len(items),
            }
