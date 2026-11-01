"""Tests for Job schema and deterministic ID generation."""

from agent.jobs.schema import Job, generate_job_id


def test_generate_job_id_deterministic() -> None:
    id1 = generate_job_id("Stripe", "Backend Engineer", "https://stripe.com/jobs/123?utm_source=test")
    id2 = generate_job_id("stripe", "backend engineer", "https://stripe.com/jobs/123")
    assert id1 == id2
    assert len(id1) == 16


def test_job_factory_method() -> None:
    job = Job.create(
        title="Python Engineer",
        company="Acme Corp",
        url="https://acme.com/jobs/42",
        source="remotive",
        location="Remote",
        is_remote=True,
        description="Write FastAPI services",
        tags=["Python", "FastAPI"],
    )
    assert job.id == generate_job_id("Acme Corp", "Python Engineer", "https://acme.com/jobs/42")
    assert job.title == "Python Engineer"
    assert job.company == "Acme Corp"
    assert job.is_remote is True
    assert job.status == "found"
