"""Tests for hard filtering engine."""

from agent.config import AppConfig, JobDiscoveryConfig, PreferencesConfig
from agent.jobs.filters import apply_hard_filters
from agent.jobs.schema import Job


def test_apply_hard_filters() -> None:
    config = AppConfig(
        preferences=PreferencesConfig(
            target_roles=["Backend Engineer", "Software Engineer"],
            locations=["Remote", "Bengaluru"],
            exclude_companies=["BadCompany"],
        ),
        jobs=JobDiscoveryConfig(
            exclude_keywords=["director", "vp", "recruiter"],
            allow_remote=True,
        ),
    )

    j_valid = Job.create(
        title="Backend Software Engineer",
        company="Good Corp",
        url="https://good.com/jobs/1",
        source="remotive",
        location="Remote",
        is_remote=True,
    )
    j_excluded_company = Job.create(
        title="Software Engineer",
        company="BadCompany Inc",
        url="https://bad.com/jobs/1",
        source="remotive",
        is_remote=True,
    )
    j_excluded_title = Job.create(
        title="Director of Engineering",
        company="Tech Corp",
        url="https://tech.com/jobs/2",
        source="lever",
        is_remote=True,
    )
    j_excluded_role = Job.create(
        title="Senior Marketing Lead",
        company="Tech Corp",
        url="https://tech.com/jobs/3",
        source="lever",
        is_remote=True,
    )
    j_wrong_location = Job.create(
        title="Backend Engineer",
        company="Local Only Corp",
        url="https://local.com/jobs/4",
        source="lever",
        location="Berlin, Germany (Onsite)",
        is_remote=False,
    )

    jobs = [j_valid, j_excluded_company, j_excluded_title, j_excluded_role, j_wrong_location]
    accepted, rejected = apply_hard_filters(jobs, config)

    assert len(accepted) == 1
    assert accepted[0].title == "Backend Software Engineer"
    assert len(rejected) == 4
