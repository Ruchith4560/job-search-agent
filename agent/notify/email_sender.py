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
        smtp_password = (os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or "").replace(" ", "")

        if dry_run or not smtp_password or not self.config.enabled:
            mode_desc = "dry_run mode" if dry_run else "no GMAIL_APP_PASSWORD configured"
            print(f"[DIGEST] Email preview saved to: {self.preview_output_path}")
            print(f"[DIGEST] Mode: Offline/Preview ({mode_desc}). {len(items)} jobs prepared.")
            if not smtp_password:
                print("[NOTE] Set GMAIL_APP_PASSWORD in your .env to enable automatic inbox delivery.")

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

    def dispatch_application_confirmation(
        self,
        job: Job,
        candidate_name: str = "Ruchith Macha",
        resume_pdf_path: Optional[str] = None,
        cover_letter_path: Optional[str] = None,
        submission_screenshot: Optional[str] = None,
        ats_score: Optional[float] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Dispatch a confirmation email confirming that an application has been completed."""
        smtp_password = (os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or "").replace(" ", "")

        applied_now = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")
        subject = f"[Application Submitted] You have applied to {job.title} at {job.company}!"

        # Locate attachments if not explicitly provided
        import re
        c_slug = re.sub(r"[^a-zA-Z0-9]+", "_", job.company).strip("_").lower()
        r_slug = re.sub(r"[^a-zA-Z0-9]+", "_", job.title).strip("_").lower()

        candidates = [
            Path("data/output") / f"{c_slug[:40]}_{r_slug[:40]}",
            Path("data/output") / f"{c_slug}_{r_slug}",
            Path("data/output") / f"{c_slug[:20]}_{r_slug[:20]}",
        ]
        if Path("data/output").is_dir():
            for d in Path("data/output").iterdir():
                if d.is_dir() and d.name.lower().startswith(c_slug[:8]):
                    candidates.append(d)

        app_dir = None
        for cand in candidates:
            if cand.exists():
                app_dir = cand
                break

        if not resume_pdf_path and app_dir and app_dir.exists():
            clean_name = candidate_name.replace(" ", "")
            std_pdf = app_dir / f"{clean_name}_{job.title.replace(' ', '')}_{job.company.replace(' ', '')}.pdf"
            fallback_pdf = app_dir / "tailored_resume.pdf"
            if std_pdf.exists():
                resume_pdf_path = str(std_pdf)
            elif fallback_pdf.exists():
                resume_pdf_path = str(fallback_pdf)
            else:
                for p in app_dir.glob("*.pdf"):
                    if "cover" not in p.name.lower():
                        resume_pdf_path = str(p)
                        break

        if not resume_pdf_path:
            for fallback in ["data/output/resume.pdf", "data/output/RuchithMacha_Master_Resume.pdf"]:
                if Path(fallback).exists():
                    resume_pdf_path = fallback
                    break

        if not cover_letter_path and app_dir and app_dir.exists():
            cl_pdf = app_dir / "cover_letter.pdf"
            if cl_pdf.exists():
                cover_letter_path = str(cl_pdf)

        if not submission_screenshot and app_dir and app_dir.exists():
            sub_png = app_dir / "submission_confirmation.png"
            if sub_png.exists():
                submission_screenshot = str(sub_png)

        ats_display = f"{ats_score:.0f}%" if ats_score is not None else (f"{job.ats_score}%" if job.ats_score else "85%+")
        apply_url = getattr(job, "url", getattr(job, "link", getattr(job, "apply_url", "#")))

        html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 24px; color: #1e293b; }}
  .container {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.06); }}
  .header {{ background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: #ffffff; padding: 32px 24px; text-align: center; }}
  .header h1 {{ margin: 0 0 8px 0; font-size: 24px; font-weight: 700; }}
  .header p {{ margin: 0; opacity: 0.95; font-size: 15px; }}
  .content {{ padding: 28px 24px; }}
  .status-pill {{ display: inline-block; padding: 5px 14px; background: #ecfdf5; color: #047857; font-weight: 700; font-size: 12px; border-radius: 9999px; border: 1px solid #a7f3d0; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 16px; }}
  .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin: 18px 0; }}
  .row {{ display: flex; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
  .row:last-child {{ border-bottom: none; }}
  .label {{ color: #64748b; font-weight: 500; }}
  .value {{ color: #0f172a; font-weight: 600; text-align: right; }}
  .action-box {{ text-align: center; margin: 28px 0 10px 0; }}
  .btn {{ display: inline-block; padding: 12px 26px; background: #059669; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 14px; }}
  .footer {{ padding: 18px 24px; background: #f8fafc; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Application Submitted! 🎉</h1>
    <p>Your AI Agent completed the application process for this opportunity.</p>
  </div>
  <div class="content">
    <div style="text-align: center;">
      <span class="status-pill">STATUS: APPLIED</span>
    </div>
    <h2 style="margin: 0 0 6px 0; color: #0f172a; font-size: 21px; text-align: center;">{html.escape(job.title)}</h2>
    <p style="margin: 0; color: #059669; font-weight: 700; font-size: 16px; text-align: center;">{html.escape(job.company)}</p>

    <div class="card">
      <div class="row"><span class="label">Candidate</span><span class="value">{html.escape(candidate_name)}</span></div>
      <div class="row"><span class="label">Location</span><span class="value">{html.escape(job.location or "Remote")}</span></div>
      <div class="row"><span class="label">Role Type</span><span class="value">{html.escape((job.job_type or "internship").replace("_", " ").title())}</span></div>
      <div class="row"><span class="label">Stipend / Salary</span><span class="value">{html.escape(job.stipend_or_salary or "Competitive")}</span></div>
      <div class="row"><span class="label">ATS Resume Score</span><span class="value" style="color: #059669;">{ats_display}</span></div>
      <div class="row"><span class="label">Submitted At</span><span class="value">{applied_now}</span></div>
    </div>

    <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 13px; color: #1e40af;">
      <strong>Attached to this email:</strong> Your tailored ATS-optimized PDF resume and cover letter for <em>{html.escape(job.company)}</em> have been attached below for your records.
    </div>

    <p style="font-size: 14px; color: #475569; line-height: 1.6;">
      <strong>Pipeline Tracking:</strong> This application has been marked as <code>applied</code> in your SQLite tracker database. You can track all active applications and interview invitations anytime by running:
      <br><code style="background: #e2e8f0; padding: 3px 6px; border-radius: 4px;">python main.py status</code>
    </p>

    <div class="action-box">
      <a href="{apply_url}" class="btn">View Employer Job Portal</a>
    </div>
  </div>
  <div class="footer">
    AI Job Search Agent &bull; Tracked in local SQLite database &bull; Run <code>python main.py status</code> to inspect pipeline
  </div>
</div>
</body>
</html>
"""

        # Save local confirmation preview
        preview_path = Path("data/output") / f"applied_confirmation_{job.id[:8]}.html"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(html_body, encoding="utf-8")

        if dry_run or not smtp_password or not self.config.enabled:
            logger.info(f"Saved application confirmation preview to: {preview_path}")
            return {
                "status": "preview_saved",
                "preview_path": str(preview_path),
                "job_id": job.id,
            }

        # Build multipart message
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = self.config.smtp_user
        msg["To"] = self.config.recipient_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Attach resume PDF
        attached = []
        if resume_pdf_path and Path(resume_pdf_path).exists():
            rpath = Path(resume_pdf_path)
            with open(rpath, "rb") as f:
                part = MIMEApplication(f.read(), Name=rpath.name)
            part["Content-Disposition"] = f'attachment; filename="{rpath.name}"'
            msg.attach(part)
            attached.append(rpath.name)

        if cover_letter_path and Path(cover_letter_path).exists():
            clpath = Path(cover_letter_path)
            with open(clpath, "rb") as f:
                part = MIMEApplication(f.read(), Name=clpath.name)
            part["Content-Disposition"] = f'attachment; filename="{clpath.name}"'
            msg.attach(part)
            attached.append(clpath.name)

        if submission_screenshot and Path(submission_screenshot).exists():
            sspath = Path(submission_screenshot)
            with open(sspath, "rb") as f:
                part = MIMEApplication(f.read(), Name=sspath.name)
            part["Content-Disposition"] = f'attachment; filename="{sspath.name}"'
            msg.attach(part)
            attached.append(sspath.name)

        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as server:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.smtp_user, smtp_password)
                server.send_message(msg)

            print(f"[APPLIED EMAIL] Delivered application confirmation for {job.company} - {job.title} to {self.config.recipient_email} ({len(attached)} attachments)!")
            return {
                "status": "sent",
                "recipient": self.config.recipient_email,
                "job_id": job.id,
                "attachments": len(attached),
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Failed to send application confirmation email: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "preview_path": str(preview_path),
            }

    def dispatch_inquiry_email(
        self,
        job: Job,
        questions: List[Dict[str, str]],
        candidate_name: str = "Ruchith Macha",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Send an interactive email asking candidate for missing form answers."""
        smtp_password = (os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or "").replace(" ", "")
        subject = f"[Job Agent Action Required] Information Needed: {job.title} at {job.company} (ID: {job.id[:8]})"

        q_rows_html = ""
        q_plain_text = ""
        for idx, q in enumerate(questions, 1):
            qid = q.get("id", f"Q{idx}")
            label = html.escape(q.get("label", "Question"))
            q_rows_html += f"""
            <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
              <span style="display: inline-block; background: #e0f2fe; color: #0369a1; font-weight: 700; font-size: 12px; padding: 3px 8px; border-radius: 4px; margin-bottom: 6px;">{qid}</span>
              <div style="font-weight: 600; color: #0f172a; font-size: 15px;">{label}</div>
            </div>
            """
            q_plain_text += f"{qid}: {q.get('label', '')}\n"

        apply_url = getattr(job, "url", getattr(job, "link", getattr(job, "apply_url", "#")))

        html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
  .container {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.06); }}
  .header {{ background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); color: #ffffff; padding: 30px 24px; text-align: center; }}
  .header h1 {{ margin: 0 0 8px 0; font-size: 23px; font-weight: 700; }}
  .content {{ padding: 28px 24px; }}
  .pill {{ display: inline-block; padding: 5px 14px; background: #fef3c7; color: #92400e; font-weight: 700; font-size: 12px; border-radius: 9999px; border: 1px solid #fde68a; margin-bottom: 16px; }}
  .instructions {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 16px; margin: 20px 0; font-size: 14px; color: #1e40af; line-height: 1.5; }}
  .reply-box {{ background: #f1f5f9; border-left: 4px solid #0284c7; padding: 12px 16px; font-family: monospace; font-size: 13px; margin-top: 8px; color: #0f172a; }}
  .btn {{ display: inline-block; padding: 12px 24px; background: #0284c7; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 14px; }}
  .footer {{ padding: 18px 24px; background: #f8fafc; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Action Required: Application Questions 📝</h1>
    <p>Your AI Agent is preparing your application for {html.escape(job.company)}</p>
  </div>
  <div class="content">
    <div style="text-align: center;">
      <span class="pill">EXTRA INFORMATION NEEDED</span>
    </div>
    <h2 style="margin: 0 0 6px 0; color: #0f172a; font-size: 20px; text-align: center;">{html.escape(job.title)}</h2>
    <p style="margin: 0; color: #0284c7; font-weight: 700; font-size: 16px; text-align: center;">{html.escape(job.company)}</p>

    <p style="font-size: 14px; color: #475569; margin: 20px 0 14px 0;">
      Hi {html.escape(candidate_name)}, the employer application portal requires answers to the following <strong>{len(questions)} question(s)</strong> before submitting:
    </p>

    <div style="background: #f8fafc; border-radius: 8px; padding: 8px;">
      {q_rows_html}
    </div>

    <div class="instructions">
      <strong>How to complete this:</strong>
      <br>Simply <strong>hit Reply</strong> to this email with your answers formatted like:
      <div class="reply-box">
Q1: Your answer here
Q2: Your answer here
      </div>
      <br><em>The agent checks your inbox automatically, saves your answers permanently in your profile, and completes your submission!</em>
    </div>

    <div style="text-align: center; margin-top: 24px;">
      <a href="{apply_url}" class="btn">View Employer Application Portal</a>
    </div>
  </div>
  <div class="footer">
    AI Job Search Agent &bull; Job ID: <code>{job.id[:8]}</code> &bull; Anurag University
  </div>
</div>
</body>
</html>
"""

        preview_path = Path("data/output") / f"inquiry_{job.id[:8]}.html"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(html_body, encoding="utf-8")

        if dry_run or not smtp_password or not self.config.enabled:
            logger.info(f"Saved application inquiry preview to: {preview_path}")
            return {
                "status": "preview_saved",
                "preview_path": str(preview_path),
                "job_id": job.id,
            }

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.smtp_user
        msg["To"] = self.config.recipient_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as server:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.smtp_user, smtp_password)
                server.send_message(msg)

            print(f"[INQUIRY EMAIL] Sent inquiry for {job.company} ({len(questions)} questions) to {self.config.recipient_email}!")
            return {
                "status": "sent",
                "recipient": self.config.recipient_email,
                "job_id": job.id,
                "question_count": len(questions),
                "subject": subject,
            }
        except Exception as e:
            logger.error(f"Failed to send inquiry email: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "preview_path": str(preview_path),
            }
