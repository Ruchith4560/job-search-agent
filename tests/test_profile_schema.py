"""Tests for master profile schema and source tracking."""

import pytest
from pydantic import ValidationError

from agent.profile.schema import (
    AchievementItem,
    EducationItem,
    ExperienceItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)


def test_schema_requires_valid_source() -> None:
    # Valid source "github", "linkedin", or "manual"
    skill = SkillItem(name="Python", category="Languages", source="github")
    assert skill.source == "github"

    # Invalid source must fail validation
    with pytest.raises(ValidationError):
        SkillItem(name="Python", source="unverified_source")  # type: ignore


def test_master_profile_helpers() -> None:
    profile = MasterProfile(
        personal_info=PersonalInfo(name="Test User"),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="FastAPI", category="Frameworks & Libraries", source="github"),
            SkillItem(name="Docker", category="Databases & Cloud", source="linkedin"),
        ],
        projects=[
            ProjectItem(
                name="my-service",
                stack=["Python", "FastAPI"],
                highlights=[
                    AchievementItem(text="Handled 10k RPS", source="github")
                ],
                source="github",
            )
        ],
    )

    flat = profile.get_all_skills_flat()
    assert flat == ["Docker", "FastAPI", "Python"]

    grouped = profile.get_skills_by_category()
    assert "Languages" in grouped
    assert "Frameworks & Libraries" in grouped
    assert len(grouped["Languages"]) == 1
    assert grouped["Languages"][0].name == "Python"
