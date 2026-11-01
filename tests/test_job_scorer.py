"""Tests for JobScorer and persistent evaluation caching."""

from pathlib import Path
from unittest.mock import MagicMock, patch
from agent.jobs.match_schema import MatchScore
from agent.jobs.schema import Job
from agent.jobs.scorer import JobScorer
from agent.llm import ClaudeClient
from agent.profile.schema import MasterProfile, PersonalInfo, ProjectItem, SkillItem


def sample_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(name="Ruchith Macha"),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="FastAPI", category="Frameworks & Libraries", source="github"),
            SkillItem(name="Docker", category="Databases & Cloud", source="github"),
        ],
        projects=[
            ProjectItem(name="AI Health", stack=["Python", "FastAPI"], source="github"),
        ],
    )


def test_heuristic_scoring_and_cache(tmp_path: Path) -> None:
    cache_file = tmp_path / "match_cache.json"
    scorer = JobScorer(cache_path=str(cache_file))

    profile = sample_profile()
    job = Job.create(
        title="FastAPI Backend Engineer",
        company="ScaleAI",
        url="https://scale.com/1",
        source="remotive",
        tags=["Python", "FastAPI", "Docker"],
        description="Develop production FastAPI microservices using Docker.",
    )

    # First call: computes and writes to cache
    score1 = scorer.score_job(job, similarity=0.75, profile=profile, use_llm=False)

    assert isinstance(score1, MatchScore)
    assert score1.job_id == job.id
    assert score1.llm_score >= 70
    assert "Python" in score1.matched_skills
    assert "FastAPI" in score1.matched_skills
    assert cache_file.is_file()

    # Second call: reads directly from cache
    score2 = scorer.score_job(job, similarity=0.75, profile=profile, use_llm=False)
    assert score2.llm_score == score1.llm_score
    assert score2.reason == score1.reason


def test_claude_scoring_with_mock(tmp_path: Path) -> None:
    cache_file = tmp_path / "claude_cache.json"
    mock_claude = MagicMock(spec=ClaudeClient)

    mock_match_score = MatchScore(
        job_id="test_id",
        job_title="FastAPI Engineer",
        company="ScaleAI",
        similarity_score=0.8,
        llm_score=92,
        matched_skills=["Python", "FastAPI"],
        missing_skills=["Kubernetes"],
        reason="Candidate demonstrates production experience with FastAPI and Python.",
        recommendation="strong_match",
    )
    mock_claude.generate_json.return_value = mock_match_score

    scorer = JobScorer(claude_client=mock_claude, cache_path=str(cache_file))
    profile = sample_profile()
    job = Job.create(
        title="FastAPI Engineer",
        company="ScaleAI",
        url="https://scale.com/1",
        source="remotive",
    )

    score = scorer.score_job(job, similarity=0.8, profile=profile, use_llm=True)
    assert score.llm_score == 92
    assert score.recommendation == "strong_match"
    mock_claude.generate_json.assert_called_once()
