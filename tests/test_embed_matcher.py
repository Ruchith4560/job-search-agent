"""Tests for vector embedding serialization and cosine shortlisting."""

from agent.jobs.embed import EmbeddingMatcher, job_to_text, profile_to_text
from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile, PersonalInfo, ProjectItem, SkillItem


def test_profile_and_job_to_text() -> None:
    profile = MasterProfile(
        personal_info=PersonalInfo(name="Test Dev", headline="Python Backend Engineer"),
        skills=[SkillItem(name="Python", source="github"), SkillItem(name="FastAPI", source="github")],
        projects=[ProjectItem(name="MyAPI", stack=["Python", "FastAPI"], source="github")],
    )
    p_text = profile_to_text(profile)
    assert "Python Backend Engineer" in p_text
    assert "FastAPI" in p_text

    job = Job.create(
        title="Python Engineer",
        company="Stripe",
        url="https://stripe.com/1",
        source="remotive",
        tags=["Python", "Docker"],
        description="We build FastAPI services",
    )
    j_text = job_to_text(job)
    assert "Python Engineer" in j_text
    assert "Stripe" in j_text


def test_embedding_matcher_ranks_relevant_jobs_higher() -> None:
    profile = MasterProfile(
        personal_info=PersonalInfo(name="Pythonista"),
        skills=[
            SkillItem(name="Python", source="github"),
            SkillItem(name="FastAPI", source="github"),
            SkillItem(name="PostgreSQL", source="github"),
        ],
        projects=[
            ProjectItem(name="API Service", stack=["Python", "FastAPI", "PostgreSQL"], source="github"),
        ],
    )

    # Highly relevant job
    j_relevant = Job.create(
        title="Senior Python Backend Developer",
        company="CloudScale",
        url="http://a.com",
        source="remotive",
        tags=["Python", "FastAPI", "PostgreSQL"],
        description="Building async FastAPI services with PostgreSQL database.",
    )

    # Irrelevant job
    j_irrelevant = Job.create(
        title="iOS Swift Developer",
        company="AppWorks",
        url="http://b.com",
        source="remotive",
        tags=["Swift", "Xcode", "iOS"],
        description="Write Swift and UIKit mobile applications for iOS devices.",
    )

    matcher = EmbeddingMatcher()
    shortlisted = matcher.shortlist(profile, [j_irrelevant, j_relevant], top_n=2)

    assert len(shortlisted) == 2
    # The Python job must be ranked first
    top_job, top_score = shortlisted[0]
    second_job, second_score = shortlisted[1]

    assert top_job.title == "Senior Python Backend Developer"
    assert top_score > second_score
