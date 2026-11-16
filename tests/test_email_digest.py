"""Tests for the daily HTML email digest generator and dispatcher."""

from pathlib import Path
from agent.config import EmailConfig
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job
from agent.notify.email_sender import EmailDigestGenerator, EmailDigestSender, JobDigestItem


def test_email_digest_html_generation() -> None:
    generator = EmailDigestGenerator()
    job = Job.create(
        title="Software Engineer Intern",
        company="Fluence",
        url="https://fluence.com/careers/1",
        source="remotive",
        location="Hyderabad / Remote",
        description="Full stack software engineering internship.",
    )
    job.stipend_or_salary = "₹45,000 / month"
    job.job_type = "internship"

    item = JobDigestItem(
        rank=1,
        job=job,
        match_score=94.0,
        ats_score=88.0,
        is_top_pick=True,
        why_it_fits=[
            "Direct alignment with React and Node.js projects.",
            "High stipend of ₹45,000 / month with PPO conversion potential.",
            "Target location: Hyderabad / Remote India.",
        ],
        missing_keywords=["GraphQL"],
        skills_worth_learning=["GraphQL"],
        resume_filename="RuchithMacha_SoftwareEngineerIntern_Fluence.pdf",
    )

    html_content = generator.build_html_digest(
        candidate_name="Ruchith Macha",
        items=[item],
        date_str="Monday, 11 November 2026",
    )

    assert "Ruchith Macha" in html_content
    assert "TOP PICK" in html_content
    assert "Fluence" in html_content
    assert "Software Engineer Intern" in html_content
    assert "₹45,000 / month" in html_content
    assert "94%" in html_content
    assert "88%" in html_content
    assert "RuchithMacha_SoftwareEngineerIntern_Fluence.pdf" in html_content
    assert "APPLY 1" in html_content


def test_email_digest_offline_preview_and_never_email_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "test_tracker.db"
    db = JobDatabase(str(db_path))

    job1 = Job.create(
        title="Frontend Intern",
        company="StartupX",
        url="https://startupx.com/jobs/1",
        source="remoteok",
    )
    job2 = Job.create(
        title="Backend Intern",
        company="EnterpriseY",
        url="https://enterprisey.com/jobs/2",
        source="remotive",
    )
    db.upsert_jobs([job1, job2])

    preview_file = tmp_path / "daily_email_preview.html"
    cfg = EmailConfig(
        enabled=True,
        recipient_email="macharuchith1@gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="macharuchith1@gmail.com",
    )

    sender = EmailDigestSender(config=cfg, db=db, preview_output_path=str(preview_file))

    item1 = JobDigestItem(rank=1, job=job1, match_score=85.0, ats_score=86.0)
    item2 = JobDigestItem(rank=2, job=job2, match_score=78.0, ats_score=85.0)

    # Dry-run dispatch
    result = sender.dispatch_digest(
        candidate_name="Ruchith Macha",
        items=[item1, item2],
        dry_run=True,
    )

    assert result["status"] == "preview_saved"
    assert preview_file.exists()
    assert preview_file.stat().st_size > 500

    # Verify that in dry-run/preview mode, jobs are NOT prematurely marked as emailed
    unemailed = db.get_jobs(unemailed_only=True)
    assert len(unemailed) == 2

    # Now verify mark_as_emailed explicitly updates jobs so they won't be emailed twice
    db.mark_as_emailed([job1.id, job2.id])
    refetched_jobs = db.get_jobs(unemailed_only=True)
    assert len(refetched_jobs) == 0

    all_jobs = db.get_jobs()
    for j in all_jobs:
        assert j.emailed_at is not None


def test_application_confirmation_dispatch(tmp_path: Path) -> None:
    db_path = tmp_path / "test_tracker.db"
    db = JobDatabase(str(db_path))

    job = Job.create(
        title="Software Engineer Intern",
        company="Acme Corp",
        url="https://acme.com/apply/1",
        source="greenhouse",
    )
    db.upsert_jobs([job])

    cfg = EmailConfig(
        enabled=True,
        recipient_email="macharuchith1@gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="macharuchith1@gmail.com",
    )

    sender = EmailDigestSender(config=cfg, db=db)

    # Dry-run dispatch
    res = sender.dispatch_application_confirmation(
        job=job,
        candidate_name="Ruchith Macha",
        ats_score=92.0,
        dry_run=True,
    )

    assert res["status"] == "preview_saved"
    preview_path = Path(res["preview_path"])
    assert preview_path.exists()
    content = preview_path.read_text(encoding="utf-8")
    assert "Acme Corp" in content
    assert "Software Engineer Intern" in content
    assert "STATUS: APPLIED" in content
    assert "92%" in content

    # Verify update_status sets applied_at
    db.update_status(job.id, "applied")
    updated = db.get_job_by_id(job.id)
    assert updated.status == "applied"
    assert updated.applied_at is not None
