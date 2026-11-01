"""Unit tests for pipeline status dashboard, CSV/JSON export, and daily digest."""

import json
from pathlib import Path
import pytest
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job
from agent.tracker.dashboard import TrackerDashboard, format_status_badge
from agent.tracker.digest import DailyDigestGenerator
from agent.tracker.export import export_jobs_to_csv, export_jobs_to_json


@pytest.fixture
def populated_db(tmp_path: Path) -> JobDatabase:
    db_file = tmp_path / "test_tracker.db"
    db = JobDatabase(str(db_file))

    jobs = [
        Job.create(
            title="Frontend Engineer",
            company="Alpha Corp",
            url="https://alpha.example.com/jobs/1",
            source="remotive",
            location="Remote",
            tags=["React", "TypeScript"],
        ),
        Job.create(
            title="Backend Engineer",
            company="Beta Inc",
            url="https://beta.example.com/jobs/2",
            source="remoteok",
            location="Remote",
            tags=["Java", "Spring Boot"],
        ),
        Job.create(
            title="Full Stack Developer",
            company="Gamma Tech",
            url="https://gamma.example.com/jobs/3",
            source="greenhouse",
            location="Bangalore",
            tags=["Python", "FastAPI"],
        ),
    ]

    jobs[0].status = "shortlisted"
    jobs[1].status = "applied"
    jobs[2].status = "interview"

    for j in jobs:
        db.upsert_job(j)

    return db


def test_tracker_dashboard_metrics(populated_db: JobDatabase) -> None:
    dashboard = TrackerDashboard(populated_db)
    metrics = dashboard.get_summary_metrics()

    assert metrics["total_jobs"] == 3
    assert metrics["status_counts"]["shortlisted"] == 1
    assert metrics["status_counts"]["applied"] == 1
    assert metrics["status_counts"]["interview"] == 1
    assert metrics["in_progress"] == 1
    assert metrics["applied"] == 1
    assert metrics["active_conversations"] == 1


def test_format_status_badge() -> None:
    badge_applied = format_status_badge("applied")
    assert "APPLIED" in badge_applied
    badge_shortlisted = format_status_badge("shortlisted")
    assert "SHORTLISTED" in badge_shortlisted


def test_export_jobs_to_csv_and_json(
    populated_db: JobDatabase, tmp_path: Path
) -> None:
    csv_file = tmp_path / "export.csv"
    json_file = tmp_path / "export.json"

    export_jobs_to_csv(populated_db, output_path=str(csv_file))
    export_jobs_to_json(populated_db, output_path=str(json_file))

    assert csv_file.is_file()
    csv_text = csv_file.read_text(encoding="utf-8")
    assert "Alpha Corp" in csv_text
    assert "Beta Inc" in csv_text
    assert "Gamma Tech" in csv_text

    assert json_file.is_file()
    json_data = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(json_data) == 3
    assert json_data[0]["company"] in ("Alpha Corp", "Beta Inc", "Gamma Tech")


def test_daily_digest_generator(populated_db: JobDatabase, tmp_path: Path) -> None:
    generator = DailyDigestGenerator(populated_db)
    digest = generator.generate_digest(candidate_name="Ruchith Macha")

    assert digest["metrics"]["total_jobs"] == 3
    assert "Alpha Corp" in digest["markdown"]
    assert "Ruchith Macha" in digest["markdown"]

    md_out = tmp_path / "daily_digest.md"
    saved = generator.save_markdown_report(digest, output_path=str(md_out))

    assert saved.is_file()
    assert "# Daily Job Search Digest" in saved.read_text(encoding="utf-8")
