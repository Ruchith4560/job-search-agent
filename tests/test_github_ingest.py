"""Tests for GitHub ingestion module."""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from github import GithubException
import pytest

from agent.ingest.github import (
    GitHubIngester,
    GitHubProfileData,
    GitHubRepo,
    extract_fallback_summary,
)


def test_extract_fallback_summary() -> None:
    readme = """# Project Title
[![Build Status](https://travis-ci.org/test.svg)](https://travis-ci.org/test)

A modern, high-performance asynchronous API service built with FastAPI and PostgreSQL.
It provides automatic authentication, background worker queues, and caching.

## License
MIT License
"""
    summary = extract_fallback_summary(readme, max_length=150)
    assert "FastAPI and PostgreSQL" in summary
    assert "# Project Title" not in summary
    assert "Build Status" not in summary
    assert "MIT License" not in summary


def test_github_ingester_fetch_and_save(tmp_path: Path) -> None:
    # Setup mock repo
    mock_repo1 = MagicMock()
    mock_repo1.name = "backend-api"
    mock_repo1.full_name = "testuser/backend-api"
    mock_repo1.description = "Production FastAPI backend"
    mock_repo1.html_url = "https://github.com/testuser/backend-api"
    mock_repo1.stargazers_count = 42
    mock_repo1.forks_count = 7
    mock_repo1.language = "Python"
    mock_repo1.get_languages.return_value = {"Python": 25000, "SQL": 5000}
    mock_repo1.get_topics.return_value = ["fastapi", "docker", "postgresql"]
    mock_repo1.fork = False
    mock_repo1.archived = False
    now = datetime.now(timezone.utc)
    mock_repo1.pushed_at = now
    mock_repo1.created_at = now
    mock_repo1.updated_at = now

    mock_readme = MagicMock()
    mock_readme.encoding = "utf-8"
    mock_readme.decoded_content = b"# backend-api\n\nA robust microservice for data orchestration."
    mock_repo1.get_readme.return_value = mock_readme

    # Forked repo that should be skipped by default
    mock_repo_fork = MagicMock()
    mock_repo_fork.name = "upstream-fork"
    mock_repo_fork.fork = True

    mock_user = MagicMock()
    mock_user.get_repos.return_value = [mock_repo1, mock_repo_fork]

    with patch("agent.ingest.github.Github") as mock_gh_cls:
        mock_gh = MagicMock()
        mock_gh.get_user.return_value = mock_user
        mock_gh_cls.return_value = mock_gh

        ingester = GitHubIngester(token="fake_token")
        profile_data = ingester.fetch_user_repos(username="testuser", include_forks=False)

        assert profile_data.username == "testuser"
        assert profile_data.total_repos == 1  # Fork skipped
        repo = profile_data.repos[0]
        assert repo.name == "backend-api"
        assert repo.stars == 42
        assert repo.primary_language == "Python"
        assert "docker" in repo.topics
        assert "A robust microservice" in (repo.readme_summary or "")

        # Test JSON serialization
        out_file = tmp_path / "github.json"
        saved_path = ingester.save_to_json(profile_data, output_path=str(out_file))
        assert saved_path.is_file()

        with open(saved_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        assert raw["username"] == "testuser"
        assert len(raw["repos"]) == 1
        assert raw["repos"][0]["name"] == "backend-api"


def test_github_ingester_readme_404_handled() -> None:
    mock_repo = MagicMock()
    mock_repo.name = "no-readme-repo"
    mock_repo.full_name = "testuser/no-readme-repo"
    mock_repo.description = "Repo without readme"
    mock_repo.html_url = "https://github.com/testuser/no-readme-repo"
    mock_repo.stargazers_count = 5
    mock_repo.forks_count = 0
    mock_repo.language = "Rust"
    mock_repo.get_languages.return_value = {"Rust": 1000}
    mock_repo.get_topics.return_value = []
    mock_repo.fork = False
    mock_repo.archived = False
    mock_repo.pushed_at = datetime.now(timezone.utc)
    mock_repo.created_at = datetime.now(timezone.utc)
    mock_repo.updated_at = datetime.now(timezone.utc)

    # Simulate 404 from PyGithub
    fake_404 = GithubException(status=404, data={"message": "Not Found"})
    mock_repo.get_readme.side_effect = fake_404

    mock_user = MagicMock()
    mock_user.get_repos.return_value = [mock_repo]

    with patch("agent.ingest.github.Github") as mock_gh_cls:
        mock_gh = MagicMock()
        mock_gh.get_user.return_value = mock_user
        mock_gh_cls.return_value = mock_gh

        ingester = GitHubIngester(token=None)
        data = ingester.fetch_user_repos(username="testuser")

        assert len(data.repos) == 1
        assert data.repos[0].readme_summary is None
        assert data.repos[0].raw_readme is None
