"""Tests for MatchPipeline end-to-end integration and SQLite state update."""

from pathlib import Path
from agent.config import AppConfig
from agent.jobs.db import JobDatabase
from agent.jobs.match import MatchPipeline
from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile, PersonalInfo, ProjectItem, SkillItem


def test_match_pipeline_end_to_end(tmp_path: Path) -> None:
    db_file = tmp_path / "match_test.db"
    cache_file = tmp_path / "match_cache.json"
    db = JobDatabase(str(db_file))

    profile = MasterProfile(
        personal_info=PersonalInfo(name="Ruchith Macha"),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="FastAPI", category="Frameworks & Libraries", source="github"),
            SkillItem(name="Docker", category="Databases & Cloud", source="github"),
        ],
        projects=[
            ProjectItem(name="Smart Healthcare", stack=["Python", "FastAPI"], source="github"),
        ],
    )

    # Job that should qualify
    j_high = Job.create(
        title="FastAPI Python Engineer",
        company="HealthTech",
        url="http://h.com/1",
        source="remotive",
        tags=["Python", "FastAPI", "Docker"],
        description="Looking for Python and FastAPI specialist.",
    )

    # Job that should have lower match
    j_low = Job.create(
        title="Cobol Mainframe Developer",
        company="LegacyBank",
        url="http://l.com/1",
        source="remotive",
        tags=["Cobol", "Mainframe"],
        description="Maintain legacy financial systems in Cobol.",
    )

    db.upsert_jobs([j_high, j_low])

    config = AppConfig()
    pipeline = MatchPipeline(config=config)
    pipeline.scorer.cache_path = cache_file

    matches = pipeline.match_jobs(
        profile=profile,
        jobs=[j_high, j_low],
        top_n=2,
        threshold=60,
        use_llm=False,
        db=db,
    )

    assert len(matches) >= 1
    top = matches[0]
    assert top.job_id == j_high.id
    assert top.llm_score >= 60

    # Verify that in SQLite, j_high is updated to 'shortlisted'
    db_job = db.get_job_by_id(j_high.id)
    assert db_job is not None
    assert db_job.status == "shortlisted"

    # j_low should still be 'found' (did not meet threshold)
    db_low = db.get_job_by_id(j_low.id)
    assert db_low is not None
    assert db_low.status == "found"
