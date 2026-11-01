"""Unit tests for the end-to-end application tailoring pipeline."""

from pathlib import Path
import pytest
from agent.apply.pipeline import ApplicationTailorPipeline, sanitize_slug
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job
from agent.profile.schema import (
    AchievementItem,
    EducationItem,
    ExperienceItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)


@pytest.fixture
def test_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Full-Stack Engineer",
            email="ruchith@example.com",
            phone="+91 9999999999",
            location="Hyderabad, India",
            links={"github": "https://github.com/Ruchith4560"},
        ),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="Java", category="Languages", source="github"),
            SkillItem(name="React", category="Frameworks", source="github"),
            SkillItem(name="Spring Boot", category="Frameworks", source="github"),
        ],
        experience=[
            ExperienceItem(
                company="IEEE CS AU",
                title="Content Specialist",
                start_date="2024-08",
                is_current=True,
                source="linkedin",
            )
        ],
        education=[
            EducationItem(
                school="Anurag University",
                degree="B.Tech Computer Science",
                start_date="2024",
                end_date="2028",
                source="linkedin",
            )
        ],
        projects=[
            ProjectItem(
                name="travel_expense_calculator",
                url="https://github.com/Ruchith4560/travel_expense_calculator",
                description="Spring Boot & React expense management app",
                stack=["Java", "Spring Boot", "React"],
                highlights=[
                    AchievementItem(text="Built expense manager with Spring Boot and React.", source="github"),
                ],
                source="github",
            )
        ],
    )


def test_sanitize_slug() -> None:
    assert sanitize_slug("Acme & Co.") == "acme_co"
    assert sanitize_slug("Senior Software Engineer (Remote)") == "senior_software_engineer_remote"


def test_application_tailor_pipeline_end_to_end(
    test_profile: MasterProfile, tmp_path: Path
) -> None:
    db_path = tmp_path / "test_tracker.db"
    db = JobDatabase(str(db_path))

    job = Job.create(
        title="Full Stack Software Engineer",
        company="TechCorp Labs",
        url="https://techcorp.example.com/job/123",
        source="remotive",
        description="Looking for Java, React, and Spring Boot engineers.",
        tags=["Java", "React"],
    )
    db.upsert_job(job)

    pipeline = ApplicationTailorPipeline()
    output_root = tmp_path / "output"

    result = pipeline.process_application(
        profile=test_profile,
        job=job,
        output_dir=str(output_root),
        use_llm=False,
        db=db,
    )

    assert result["status"] == "success"
    assert result["company"] == "TechCorp Labs"
    target_dir = Path(result["target_dir"])
    assert target_dir.is_dir()

    # Verify all 6 documents and manifest are generated
    assert (target_dir / "tailored_resume.pdf").is_file()
    assert (target_dir / "tailored_resume.docx").is_file()
    assert (target_dir / "tailored_resume.html").is_file()
    assert (target_dir / "cover_letter.pdf").is_file()
    assert (target_dir / "cover_letter.docx").is_file()
    assert (target_dir / "cover_letter.txt").is_file()
    assert (target_dir / "manifest.json").is_file()

    # Check manifest contents
    manifest = result["manifest"]
    assert manifest["job_id"] == job.id
    assert manifest["verified"] is True
    assert "Java" in manifest["matched_skills"]
    assert "travel_expense_calculator" in manifest["featured_projects"]

    # Verify database status updated to 'tailored'
    db_job = db.get_job_by_id(job.id)
    assert db_job is not None
    assert db_job.status == "tailored"
