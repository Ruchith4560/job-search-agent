"""Tests for job de-duplication and URL normalization."""

from agent.jobs.dedupe import clean_url, deduplicate_jobs
from agent.jobs.schema import Job


def test_clean_url_strips_tracking() -> None:
    raw = "https://boards.greenhouse.io/canonical/jobs/12345?gh_src=linkedin&utm_source=feed&mode=json/"
    cleaned = clean_url(raw)
    assert cleaned == "https://boards.greenhouse.io/canonical/jobs/12345"


def test_deduplicate_jobs_identical_and_near_identical() -> None:
    j1 = Job.create(
        title="Backend Engineer (Python)",
        company="Stripe",
        url="https://stripe.com/jobs/1",
        source="greenhouse",
    )
    # Same company and title with slight url query difference
    j2 = Job.create(
        title="Backend Engineer (Python)",
        company="Stripe",
        url="https://stripe.com/jobs/1?ref=jobboard",
        source="remotive",
    )
    # Different job
    j3 = Job.create(
        title="Frontend Engineer",
        company="Stripe",
        url="https://stripe.com/jobs/2",
        source="greenhouse",
    )

    unique = deduplicate_jobs([j1, j2, j3])
    assert len(unique) == 2
    assert unique[0].title == "Backend Engineer (Python)"
    assert unique[1].title == "Frontend Engineer"
