"""Tests for resume generator and project selection."""

from agent.profile.schema import (
    EducationItem,
    ExperienceItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)
from agent.resume.generator import ResumeGenerator, score_project_relevance


def test_score_project_relevance() -> None:
    proj_basic = ProjectItem(name="basic-script", stack=["Python"], source="github")
    proj_rich = ProjectItem(
        name="fullstack-app",
        stack=["React", "FastAPI", "PostgreSQL", "Docker"],
        stars=10,
        source="github",
    )
    assert score_project_relevance(proj_rich) > score_project_relevance(proj_basic)


def test_resume_generator_compilation() -> None:
    profile = MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Full Stack Developer",
            email="test@example.com",
            phone="1234567890",
            location="Hyderabad, India",
            links={"github": "https://github.com/Ruchith4560"},
        ),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="React.js", category="Frameworks & Libraries", source="linkedin"),
            SkillItem(name="FastAPI", category="Frameworks & Libraries", source="github"),
        ],
        experience=[
            ExperienceItem(
                company="IEEE Student Branch",
                title="Content Specialist",
                source="linkedin",
            )
        ],
        projects=[
            ProjectItem(
                name="Smart AI Healthcare System",
                stack=["React.js", "FastAPI", "Python"],
                source="github",
            )
        ],
        education=[
            EducationItem(
                school="Anurag University",
                degree="B.Tech Computer Science",
                source="linkedin",
            )
        ],
    )

    generator = ResumeGenerator()
    resume = generator.generate(profile, max_projects=2)

    assert resume.name == "Ruchith Macha"
    assert resume.email == "test@example.com"
    assert len(resume.projects) == 1
    assert resume.projects[0].name == "Smart AI Healthcare System"
    assert len(resume.experience) == 1
    assert len(resume.education) == 1
