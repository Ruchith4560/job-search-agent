"""Tests for ProfileBuilder merging logic."""

from pathlib import Path
from agent.ingest.github import GitHubProfileData, GitHubRepo
from agent.ingest.linkedin import (
    LinkedInExportData,
    RawLinkedInEducation,
    RawLinkedInPosition,
    RawLinkedInProfile,
    RawLinkedInSkill,
)
from agent.profile.builder import ProfileBuilder, categorize_skill, detect_stack_from_readme


def test_categorize_skill() -> None:
    assert categorize_skill("Python") == "Languages"
    assert categorize_skill("TypeScript") == "Languages"
    assert categorize_skill("React") == "Frameworks & Libraries"
    assert categorize_skill("Spring Boot") == "Frameworks & Libraries"
    assert categorize_skill("PostgreSQL") == "Databases & Cloud"
    assert categorize_skill("Docker") == "Databases & Cloud"
    assert categorize_skill("Git") == "Developer Tools & Practices"


def test_detect_stack_from_readme() -> None:
    readme = "Built with React 18, Vite, Tailwind CSS and a Spring Boot PostgreSQL backend."
    stack = detect_stack_from_readme(readme)
    assert "React" in stack
    assert "Spring Boot" in stack
    assert "PostgreSQL" in stack
    assert "Tailwind CSS" in stack


def test_profile_builder_merge(tmp_path: Path) -> None:
    # 1. Mock GitHub Data
    gh_repo = GitHubRepo(
        name="ai-travel-planner",
        full_name="user/ai-travel-planner",
        description="A full-stack travel planner",
        html_url="https://github.com/user/ai-travel-planner",
        stars=15,
        primary_language="TypeScript",
        languages={"TypeScript": 50000, "Java": 30000},
        topics=["travel", "react", "spring-boot"],
        last_activity="2026-10-25T00:00:00Z",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-10-25T00:00:00Z",
        raw_readme="Fullstack app with React 18, Spring Boot, and PostgreSQL",
    )
    gh_data = GitHubProfileData(
        username="testuser",
        fetched_at="2026-10-25T00:00:00Z",
        total_repos=1,
        repos=[gh_repo],
    )

    # 2. Mock LinkedIn Data
    lk_data = LinkedInExportData(
        profile=RawLinkedInProfile(
            first_name="Ruchith",
            last_name="Kumar",
            headline="Full Stack AI Engineer",
            geo_location="Bengaluru, India",
        ),
        positions=[
            RawLinkedInPosition(
                company_name="Tech Solutions",
                title="Software Engineer",
                description="Designed scalable microservices in Java and Spring Boot.\nImplemented CI/CD pipelines.",
                location="Bengaluru",
                started_on="Jan 2023",
                finished_on="",
            )
        ],
        education=[
            RawLinkedInEducation(
                school_name="Tech University",
                degree_name="B.Tech Computer Science",
                start_date="2019",
                end_date="2023",
            )
        ],
        skills=[
            RawLinkedInSkill(name="Java"),
            RawLinkedInSkill(name="Python"),
            RawLinkedInSkill(name="Docker"),
        ],
    )

    builder = ProfileBuilder()
    profile = builder.build(github_data=gh_data, linkedin_data=lk_data)

    # Verify Personal Info
    assert profile.personal_info.name == "Ruchith Kumar"
    assert profile.personal_info.headline == "Full Stack AI Engineer"
    assert profile.personal_info.links["github"] == "https://github.com/testuser"

    # Verify Projects
    assert len(profile.projects) == 1
    proj = profile.projects[0]
    assert proj.name == "ai-travel-planner"
    assert "TypeScript" in proj.stack
    assert "Spring Boot" in proj.stack
    assert proj.source == "github"

    # Verify Experience
    assert len(profile.experience) == 1
    exp = profile.experience[0]
    assert exp.company == "Tech Solutions"
    assert exp.is_current is True
    assert len(exp.achievements) == 2
    assert exp.achievements[0].source == "linkedin"

    # Verify Skills and Cross-Evidence
    skill_names = [s.name for s in profile.skills]
    assert "Java" in skill_names
    assert "TypeScript" in skill_names
    assert "Docker" in skill_names

    # Check Java evidence merges LinkedIn and GitHub
    java_skill = next(s for s in profile.skills if s.name.lower() == "java")
    assert "GitHub" in java_skill.evidence
    assert "LinkedIn" in java_skill.evidence

    # Verify persistence to disk
    out_file = tmp_path / "master_profile.json"
    saved = builder.save_profile(profile, output_path=str(out_file))
    assert saved.is_file()
