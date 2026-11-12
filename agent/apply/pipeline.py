"""Tailoring and application asset generation orchestrator for Phase 6."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, Optional

from agent.apply.cover_letter import (
    CoverLetterData,
    CoverLetterGenerator,
    CoverLetterVerifier,
)
from agent.apply.render_cover_letter import (
    render_cover_letter_docx,
    render_cover_letter_pdf,
    render_cover_letter_text,
)
from agent.apply.tailor import ResumeTailorer
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job
from agent.llm import ClaudeClient
from agent.profile.schema import MasterProfile
from agent.resume.render import render_docx, render_html, render_pdf
from agent.resume.schema import ResumeData
from agent.resume.verifier import ResumeVerifier

logger = logging.getLogger(__name__)


def sanitize_slug(text: str) -> str:
    """Create a clean filesystem-safe slug from text."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return slug[:40] if len(slug) > 40 else slug


def build_resume_filename(candidate_name: str, role_title: str, company: str, ext: str = "pdf") -> str:
    """Format resume filename according to Name_Role_Company convention.

    Example: RuchithMacha_FullStackDeveloper_Fluence.pdf
    """
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", candidate_name.title()) or "Candidate"
    clean_role = re.sub(r"[^a-zA-Z0-9]", "", role_title.title()) or "Role"
    clean_company = re.sub(r"[^a-zA-Z0-9]", "", company.title()) or "Company"
    return f"{clean_name}_{clean_role}_{clean_company}.{ext}"


class ApplicationTailorPipeline:
    """Orchestrates end-to-end resume tailoring, cover letter drafting, and multi-format rendering."""

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        resume_verifier: Optional[ResumeVerifier] = None,
        cover_letter_verifier: Optional[CoverLetterVerifier] = None,
    ) -> None:
        """Initialize pipeline with verifiers and generators."""
        self.claude_client = claude_client
        self.resume_tailorer = ResumeTailorer(verifier=resume_verifier)
        self.cover_letter_generator = CoverLetterGenerator(
            claude_client=claude_client, verifier=cover_letter_verifier
        )

    def process_application(
        self,
        profile: MasterProfile,
        job: Job,
        output_dir: str = "data/output",
        use_llm: bool = False,
        db: Optional[JobDatabase] = None,
    ) -> Dict[str, Any]:
        """Execute complete tailoring, rendering, and manifest generation for a target job.

        Args:
            profile: Verified MasterProfile.
            job: Target Job instance.
            output_dir: Root directory for application outputs.
            use_llm: Whether to use Claude for tailored cover letter.
            db: Optional JobDatabase to update job status.

        Returns:
            Dictionary containing paths, manifest, and tailoring metrics.
        """
        # 1. Target Directory Setup
        comp_slug = sanitize_slug(job.company) or "company"
        role_slug = sanitize_slug(job.title) or "role"
        folder_name = f"{comp_slug}_{role_slug}"
        target_dir = Path(output_dir) / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Preparing tailored application packet in: {target_dir}")

        # 2. Tailor and Verify Resume
        tailored_resume, metadata = self.resume_tailorer.tailor(profile=profile, job=job)

        # 3. Draft and Verify Cover Letter
        cover_letter = self.cover_letter_generator.generate(
            profile=profile, job=job, use_llm=use_llm
        )

        # 4. Render Resume Files (Named per Section 7: Name_Role_Company.pdf)
        candidate_name = profile.personal_info.name or "Candidate"
        std_resume_filename = build_resume_filename(candidate_name, job.title, job.company, ext="pdf")
        std_docx_filename = build_resume_filename(candidate_name, job.title, job.company, ext="docx")

        resume_named_pdf_path = target_dir / std_resume_filename
        resume_pdf_path = target_dir / "tailored_resume.pdf"
        resume_docx_path = target_dir / "tailored_resume.docx"
        resume_named_docx_path = target_dir / std_docx_filename
        resume_html_path = target_dir / "tailored_resume.html"

        # Render primary named PDF and copy to tailored_resume.pdf for compatibility
        render_pdf(tailored_resume, output_path=str(resume_named_pdf_path))
        render_pdf(tailored_resume, output_path=str(resume_pdf_path))

        render_docx(tailored_resume, output_path=str(resume_named_docx_path))
        render_docx(tailored_resume, output_path=str(resume_docx_path))

        html_content = render_html(tailored_resume)
        resume_html_path.write_text(html_content, encoding="utf-8")

        # 5. Render Cover Letter Files
        cl_pdf_path = target_dir / "cover_letter.pdf"
        cl_docx_path = target_dir / "cover_letter.docx"
        cl_txt_path = target_dir / "cover_letter.txt"

        render_cover_letter_pdf(cover_letter, output_path=str(cl_pdf_path))
        render_cover_letter_docx(cover_letter, output_path=str(cl_docx_path))
        render_cover_letter_text(cover_letter, output_path=str(cl_txt_path))

        # 6. Build and Save Application Manifest
        ats_score = metadata.get("ats_score", 0.0)
        manifest = {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "candidate_name": candidate_name,
            "resume_filename": std_resume_filename,
            "ats_score": ats_score,
            "ats_metrics": {
                "keyword_score": metadata.get("keyword_score", 0.0),
                "format_score": metadata.get("format_score", 0.0),
                "missing_keywords": metadata.get("missing_keywords", []),
                "skills_worth_learning": metadata.get("skills_worth_learning", []),
            },
            "tailored_at": datetime.now(timezone.utc).isoformat(),
            "output_directory": str(target_dir.resolve()),
            "matched_skills": metadata["matched_skills"],
            "featured_projects": metadata["selected_projects"],
            "files": {
                "named_resume_pdf": str(resume_named_pdf_path.resolve()),
                "tailored_resume_pdf": str(resume_pdf_path.resolve()),
                "tailored_resume_docx": str(resume_docx_path.resolve()),
                "tailored_resume_html": str(resume_html_path.resolve()),
                "cover_letter_pdf": str(cl_pdf_path.resolve()),
                "cover_letter_docx": str(cl_docx_path.resolve()),
                "cover_letter_txt": str(cl_txt_path.resolve()),
            },
            "verified": True,
        }

        manifest_path = target_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 7. Update Job Status and ATS Score in SQLite
        if db:
            db.update_status(job.id, "tailored")
            db.update_scores(job.id, ats_score=ats_score)
            logger.info(f"Updated status for job {job.id} to 'tailored' with ATS score {ats_score}%.")

        return {
            "status": "success",
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "target_dir": target_dir,
            "resume_pdf_path": resume_named_pdf_path,
            "ats_score": ats_score,
            "manifest": manifest,
            "matched_skills": metadata["matched_skills"],
            "featured_projects": metadata["selected_projects"],
            "tailored_resume": tailored_resume,
            "cover_letter": cover_letter,
        }
