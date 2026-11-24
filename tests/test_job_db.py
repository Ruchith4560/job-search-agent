"""Tests for SQLite job storage and state tracking."""

from pathlib import Path
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job


def test_sqlite_upsert_and_status_preservation(tmp_path: Path) -> None:
    db_file = tmp_path / "test_tracker.db"
    db = JobDatabase(str(db_file))

    job1 = Job.create(
        title="Software Engineer",
        company="Canonical",
        url="https://canonical.com/careers/1",
        source="greenhouse",
        location="Remote",
        is_remote=True,
    )

    # 1. Insert new job
    is_new = db.upsert_job(job1)
    assert is_new is True
    assert db.count_total() == 1

    # 2. Change status to 'shortlisted'
    db.update_status(job1.id, "shortlisted")
    saved_job = db.get_job_by_id(job1.id)
    assert saved_job is not None
    assert saved_job.status == "shortlisted"

    # 3. Re-upserting same job should update description without reverting status
    job1_updated = Job.create(
        title="Software Engineer",
        company="Canonical",
        url="https://canonical.com/careers/1",
        source="greenhouse",
        location="Remote",
        is_remote=True,
        description="Updated description with more details",
    )
    is_new = db.upsert_job(job1_updated)
    assert is_new is False  # Updated, not new

    # Verify status remained 'shortlisted'
    reloaded = db.get_job_by_id(job1.id)
    assert reloaded is not None
    assert reloaded.status == "shortlisted"
    assert "Updated description" in reloaded.description


def test_batch_upsert_and_filter_by_status(tmp_path: Path) -> None:
    db_file = tmp_path / "batch.db"
    db = JobDatabase(str(db_file))

    j1 = Job.create(title="Dev 1", company="Co A", url="http://a.com/1", source="remotive")
    j2 = Job.create(title="Dev 2", company="Co B", url="http://b.com/2", source="arbeitnow")

    inserted, updated = db.upsert_jobs([j1, j2])
    assert inserted == 2
    assert updated == 0
    assert db.count_total() == 2

    # Query
    found_jobs = db.get_jobs(status="found")
    assert len(found_jobs) == 2
    by_source = db.get_jobs(source="remotive")
    assert len(by_source) == 1
    assert by_source[0].company == "Co A"
