"""Unit tests for resume tailoring and project relevance scoring."""

import pytest
from agent.apply.tailor import (
    ResumeTailorer,
    calculate_project_match_score,
    extract_keywords_from_job,
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
from agent.resume.schema import ResumeProject
from agent.resume.verifier import VerificationError


@pytest.fixture
def sample_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Full-Stack Developer",
            email="ruchith@example.com",
            phone="+91 9999999999",
            location="Hyderabad, India",
            links={"github": "https://github.com/Ruchith4560"},
        ),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="Java", category="Languages", source="github"),
            SkillItem(name="JavaScript", category="Languages", source="github"),
            SkillItem(name="React", category="Frameworks", source="github"),
            SkillItem(name="FastAPI", category="Frameworks", source="github"),
            SkillItem(name="Spring Boot", category="Frameworks", source="github"),
            SkillItem(name="Docker", category="Tools", source="github"),
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
                description="Spring Boot and React expense manager",
                stack=["Java", "Spring Boot", "React", "PostgreSQL"],
                highlights=[
                    AchievementItem(text="Designed RESTful architecture with Spring Boot and React.", source="github"),
                ],
                source="github",
            ),
            ProjectItem(
                name="NextMail_Ai",
                url="https://github.com/Ruchith4560/NextMail_Ai",
                description="FastAPI AI mail intelligence service",
                stack=["Python", "FastAPI", "Docker"],
                highlights=[
                    AchievementItem(text="Built automated email intelligence with FastAPI and Docker.", source="github"),
                ],
                source="github",
            ),
        ],
    )


@pytest.fixture
def java_job() -> Job:
    return Job.create(
        title="Java Spring Backend Engineer",
        company="EnterpriseTech",
        url="https://example.com/job/java",
        source="remotive",
        description="Looking for an engineer experienced in Java, Spring Boot, and REST APIs.",
        tags=["Java", "Spring Boot", "Backend"],
    )


@pytest.fixture
def python_job() -> Job:
    return Job.create(
        title="Python AI Engineer",
        company="AiCorp",
        url="https://example.com/job/python",
        source="remoteok",
        description="We need FastAPI, Docker, and Python developers for microservices.",
        tags=["Python", "FastAPI", "Docker"],
    )


def test_extract_keywords_from_job(java_job: Job) -> None:
    keywords = extract_keywords_from_job(java_job)
    assert "java" in keywords
    assert "spring" in keywords or "spring boot" in " ".join(keywords)
    assert "backend" in keywords


def test_project_match_scoring(
    sample_profile: MasterProfile, java_job: Job, python_job: Job
) -> None:
    java_proj = sample_profile.projects[0]
    python_proj = sample_profile.projects[1]

    java_kws = extract_keywords_from_job(java_job)
    score_java_on_java = calculate_project_match_score(java_proj, java_kws, java_job)
    score_python_on_java = calculate_project_match_score(python_proj, java_kws, java_job)

    # Java project should score significantly higher for Java job
    assert score_java_on_java > score_python_on_java

    python_kws = extract_keywords_from_job(python_job)
    score_python_on_python = calculate_project_match_score(python_proj, python_kws, python_job)
    score_java_on_python = calculate_project_match_score(java_proj, python_kws, python_job)

    # Python project should score higher for Python job
    assert score_python_on_python > score_java_on_python


def test_resume_tailoring_reorders_skills_and_projects(
    sample_profile: MasterProfile, java_job: Job
) -> None:
    tailorer = ResumeTailorer()
    tailored_resume, metadata = tailorer.tailor(sample_profile, java_job)

    # 1. Matching skills prioritized
    languages = tailored_resume.skills_by_category["Languages"]
    assert languages[0] == "Java"  # Java moved to first position

    frameworks = tailored_resume.skills_by_category["Frameworks"]
    assert frameworks[0] == "Spring Boot"

    # 2. Project ranking: travel_expense_calculator should be first
    assert tailored_resume.projects[0].name == "travel_expense_calculator"

    # 3. Metadata output
    assert "Java" in metadata["matched_skills"]
    assert metadata["selected_projects"][0] == "travel_expense_calculator"


def test_resume_tailoring_anti_hallucination_guarantee(
    sample_profile: MasterProfile, java_job: Job
) -> None:
    tailorer = ResumeTailorer()
    tailored_resume, _ = tailorer.tailor(sample_profile, java_job)

    # Verify that the generated resume strictly conforms to master profile
    tailorer.verifier.verify(tailored_resume, sample_profile)

    # Inject an unverified fake skill to test verifier enforcement
    tailored_resume.skills_by_category["Languages"].append("KubernetesArchitecture")
    with pytest.raises(VerificationError) as exc_info:
        tailorer.verifier.verify(tailored_resume, sample_profile)
    assert "Unsupported Skill" in str(exc_info.value)
