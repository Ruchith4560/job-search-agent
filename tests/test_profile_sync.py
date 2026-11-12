"""Tests for automatic profile synchronization and ATS resume optimization."""

from pathlib import Path
from unittest.mock import MagicMock
from agent.config import AppConfig
from agent.ingest.github import GitHubProfileData, GitHubRepo
from agent.profile.schema import MasterProfile, PersonalInfo, ProjectItem, SkillItem
from agent.profile.sync import ProfileSyncManager


def test_profile_sync_detects_new_repo_and_optimizes_resume(tmp_path: Path) -> None:
    # 1. Setup mock master profile
    master_file = tmp_path / "master_profile.json"
    initial_profile = MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Full Stack Developer",
            email="macharuchith1@gmail.com",
            phone="6305239230",
            location="Hyderabad, India",
        ),
        skills=[
            SkillItem(name="React", category="Frontend", source="github"),
            SkillItem(name="Node.js", category="Backend", source="github"),
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="MongoDB", category="Databases", source="github"),
            SkillItem(name="Docker", category="DevOps", source="github"),
            SkillItem(name="SQL", category="Databases", source="github"),
            SkillItem(name="Git", category="Tools", source="github"),
        ],
        projects=[
            ProjectItem(
                name="Servicedesk Pro",
                description="Incident management dashboard",
                stack=["React", "Node.js", "MongoDB"],
                source="github",
            )
        ],
        version="1.0",
    )
    master_file.write_text(initial_profile.model_dump_json(indent=2), encoding="utf-8")

    cfg = AppConfig()
    cfg.paths.master_profile_file = str(master_file)
    cfg.paths.github_raw_file = str(tmp_path / "github.json")

    mgr = ProfileSyncManager(config=cfg)

    # Mock GitHub returning a brand new project
    mock_new_repo = GitHubRepo(
        name="AI_Code_Reviewer",
        full_name="Ruchith4560/AI_Code_Reviewer",
        description="Automated code analyzer built with FastAPI and React",
        html_url="https://github.com/Ruchith4560/AI_Code_Reviewer",
        primary_language="Python",
        languages={"Python": 12000, "TypeScript": 4000},
        topics=["fastapi", "react", "ai"],
        last_activity="2026-11-12T10:00:00Z",
        created_at="2026-11-12T10:00:00Z",
        updated_at="2026-11-12T12:00:00Z",
        readme_summary="AI Code Reviewer automated analysis engine.",
    )
    mock_gh_data = GitHubProfileData(
        username="Ruchith4560",
        fetched_at="2026-11-12T12:00:00Z",
        total_repos=2,
        repos=[
            GitHubRepo(
                name="Servicedesk Pro",
                full_name="Ruchith4560/servicedesk-pro",
                html_url="https://github.com/Ruchith4560/servicedesk-pro",
                last_activity="2026-01-01T00:00:00Z",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
            mock_new_repo,
        ],
    )
    mgr.ingester.fetch_user_repos = MagicMock(return_value=mock_gh_data)

    # Run check
    check = mgr.check_for_updates()
    assert check["has_changes"] is True
    assert "AI_Code_Reviewer" in check["new_repos"]

    # Run sync and optimization
    out_dir = tmp_path / "output"
    sync_res = mgr.sync_and_optimize(force=False, output_dir=str(out_dir))

    assert sync_res["status"] == "synchronized"
    assert sync_res["is_ats_compliant"] is True
    assert sync_res["ats_score"] >= 85
    assert "AI_Code_Reviewer" in sync_res["new_projects"]

    # Verify updated profile saved to disk
    updated_profile = MasterProfile.model_validate_json(master_file.read_text(encoding="utf-8"))
    assert any(p.name == "AI_Code_Reviewer" for p in updated_profile.projects)
    assert float(updated_profile.version) > 1.0

    # Verify generated resume PDFs exist
    assert Path(sync_res["named_pdf_path"]).exists()
    assert Path(sync_res["base_pdf_path"]).exists()
