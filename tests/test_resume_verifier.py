"""Tests for strict resume verification and hallucination detection (Hard Rule 2)."""

import pytest
from agent.profile.schema import (
    EducationItem,
    ExperienceItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)
from agent.resume.schema import (
    ResumeData,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
)
from agent.resume.verifier import ResumeVerifier, VerificationError


@pytest.fixture
def base_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(name="Ruchith Macha"),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="FastAPI", category="Frameworks & Libraries", source="github"),
            SkillItem(name="Docker", category="Databases & Cloud", source="github"),
        ],
        experience=[
            ExperienceItem(
                company="IEEE Student Branch",
                title="Content Lead",
                source="linkedin",
            )
        ],
        projects=[
            ProjectItem(
                name="Smart Healthcare System",
                stack=["Python", "FastAPI"],
                source="github",
            )
        ],
        education=[
            EducationItem(
                school="Anurag University",
                degree="B.Tech",
                source="linkedin",
            )
        ],
    )


def test_verifier_passes_on_valid_data(base_profile: MasterProfile) -> None:
    valid_resume = ResumeData(
        name="Ruchith Macha",
        skills_by_category={"Languages": ["Python"], "Frameworks": ["FastAPI"]},
        experience=[
            ResumeExperience(
                company="IEEE Student Branch",
                title="Content Lead",
                dates="2025",
                bullets=["Created content"],
            )
        ],
        projects=[
            ResumeProject(
                name="Smart Healthcare System",
                stack=["Python", "FastAPI"],
                bullets=["Developed API"],
            )
        ],
        education=[
            ResumeEducation(
                school="Anurag University",
                degree="B.Tech",
                dates="2024 - 2028",
            )
        ],
    )

    verifier = ResumeVerifier(strict=True)
    issues = verifier.verify(valid_resume, base_profile)
    assert len(issues) == 0


def test_verifier_fails_on_hallucinated_company(base_profile: MasterProfile) -> None:
    fake_resume = ResumeData(
        name="Ruchith Macha",
        skills_by_category={"Languages": ["Python"]},
        experience=[
            ResumeExperience(
                company="Google Inc",  # Invented company
                title="Senior Staff Engineer",
                dates="2022",
            )
        ],
    )

    verifier = ResumeVerifier(strict=True)
    with pytest.raises(VerificationError, match="Unsupported Company: 'Google Inc'"):
        verifier.verify(fake_resume, base_profile)


def test_verifier_fails_on_hallucinated_skill(base_profile: MasterProfile) -> None:
    fake_resume = ResumeData(
        name="Ruchith Macha",
        skills_by_category={
            "Cloud": ["Kubernetes", "AWS"]  # Invented skills
        },
    )

    verifier = ResumeVerifier(strict=True)
    with pytest.raises(VerificationError, match="Unsupported Skill: 'Kubernetes'"):
        verifier.verify(fake_resume, base_profile)


def test_verifier_fails_on_hallucinated_project(base_profile: MasterProfile) -> None:
    fake_resume = ResumeData(
        name="Ruchith Macha",
        skills_by_category={"Languages": ["Python"]},
        projects=[
            ResumeProject(
                name="Autonomous Flying Car OS",  # Invented project
                stack=["C++"],
            )
        ],
    )

    verifier = ResumeVerifier(strict=True)
    with pytest.raises(VerificationError, match="Unsupported Project: 'Autonomous Flying Car OS'"):
        verifier.verify(fake_resume, base_profile)
