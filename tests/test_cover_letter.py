"""Unit tests for cover letter generation, anti-hallucination verification, and multi-format rendering."""

from pathlib import Path
import pytest
from agent.apply.cover_letter import (
    CoverLetterData,
    CoverLetterGenerator,
    CoverLetterVerificationError,
    CoverLetterVerifier,
)
from agent.apply.render_cover_letter import (
    render_cover_letter_docx,
    render_cover_letter_pdf,
    render_cover_letter_text,
)
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
def sample_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Full-Stack Engineer",
            email="ruchith@example.com",
            phone="+91 9999999999",
            location="Hyderabad, India",
            links={
                "github": "https://github.com/Ruchith4560",
                "linkedin": "https://linkedin.com/in/ruchith-macha",
            },
        ),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="Java", category="Languages", source="github"),
            SkillItem(name="React", category="Frameworks", source="github"),
            SkillItem(name="Spring Boot", category="Frameworks", source="github"),
            SkillItem(name="FastAPI", category="Frameworks", source="github"),
        ],
        experience=[
            ExperienceItem(
                company="IEEE CS AU",
                title="Content Specialist",
                start_date="2024-08",
                end_date="2025-05",
                is_current=True,
                source="linkedin",
            )
        ],
        education=[
            EducationItem(
                school="Anurag University",
                degree="B.Tech Computer Science and Engineering",
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
                stack=["Java", "Spring Boot", "React", "PostgreSQL"],
                highlights=[
                    AchievementItem(text="Architected full-stack expense tracking with Spring Boot and React.", source="github"),
                ],
                source="github",
            )
        ],
    )


@pytest.fixture
def target_job() -> Job:
    return Job.create(
        title="Software Engineer - Full Stack",
        company="Acme Cloud",
        url="https://acme.example.com/jobs/1",
        source="greenhouse",
        description="Looking for an engineer to build modern web applications using Java, React, and REST APIs.",
        tags=["Java", "React", "REST"],
    )


def test_deterministic_cover_letter_generation(
    sample_profile: MasterProfile, target_job: Job
) -> None:
    generator = CoverLetterGenerator()
    letter = generator.generate(sample_profile, target_job, use_llm=False)

    assert letter.candidate_name == "Ruchith Macha"
    assert letter.company_name == "Acme Cloud"
    assert letter.job_title == "Software Engineer - Full Stack"

    # Paragraph checks
    assert "Acme Cloud" in letter.opening_paragraph
    assert "Software Engineer - Full Stack" in letter.opening_paragraph
    assert "Anurag University" in letter.opening_paragraph

    # Body paragraph must reference verified project
    assert "travel_expense_calculator" in letter.body_paragraph
    assert "Spring Boot" in letter.body_paragraph or "React" in letter.body_paragraph
    assert "IEEE CS AU" in letter.body_paragraph

    # Plain text conversion
    txt = letter.to_plain_text()
    assert "Ruchith Macha" in txt
    assert "Dear Hiring Team," in txt
    assert "Sincerely," in txt


def test_cover_letter_verifier_catches_fabrication(
    sample_profile: MasterProfile, target_job: Job
) -> None:
    verifier = CoverLetterVerifier(strict=True)
    generator = CoverLetterGenerator(verifier=verifier)
    letter = generator.generate(sample_profile, target_job, use_llm=False)

    # Valid letter passes verification
    verifier.verify(letter, sample_profile, target_job)

    # Corrupt candidate name
    letter.candidate_name = "John Doe"
    with pytest.raises(CoverLetterVerificationError) as exc:
        verifier.verify(letter, sample_profile, target_job)
    assert "Candidate name mismatch" in str(exc.value)

    # Corrupt target company
    letter.candidate_name = "Ruchith Macha"
    letter.company_name = "Fabricated Corp"
    with pytest.raises(CoverLetterVerificationError) as exc:
        verifier.verify(letter, sample_profile, target_job)
    assert "Target company mismatch" in str(exc.value)


def test_cover_letter_rendering_docx_pdf_txt(
    sample_profile: MasterProfile, target_job: Job, tmp_path: Path
) -> None:
    generator = CoverLetterGenerator()
    letter = generator.generate(sample_profile, target_job, use_llm=False)

    pdf_path = tmp_path / "cover_letter.pdf"
    docx_path = tmp_path / "cover_letter.docx"
    txt_path = tmp_path / "cover_letter.txt"

    render_cover_letter_pdf(letter, str(pdf_path))
    render_cover_letter_docx(letter, str(docx_path))
    render_cover_letter_text(letter, str(txt_path))

    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 1000

    assert docx_path.is_file()
    assert docx_path.stat().st_size > 1000

    assert txt_path.is_file()
    assert "Acme Cloud" in txt_path.read_text(encoding="utf-8")
