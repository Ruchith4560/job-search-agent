"""Tests for scam indicators and deal-breaker filtering."""

from agent.jobs.filters import check_for_scam, is_experience_eligible, is_unpaid_role
from agent.jobs.schema import Job


def test_scam_filter_detects_fee_charging() -> None:
    job = Job.create(
        title="Software Intern",
        company="Shady Corp",
        url="https://shady.com/1",
        source="remotive",
        description="To complete your registration, candidate must pay a refundable training fee of ₹1500.",
    )
    reason = check_for_scam(job)
    assert reason is not None
    assert "fee" in reason.lower() or "deposit" in reason.lower()


def test_scam_filter_detects_bank_details() -> None:
    job = Job.create(
        title="Web Developer",
        company="Fake Co",
        url="https://fake.com/2",
        source="remotive",
        description="Please share your bank account details and credit card number for initial onboarding.",
    )
    reason = check_for_scam(job)
    assert reason is not None
    assert "bank" in reason.lower() or "card" in reason.lower()


def test_experience_filter_rejects_senior_roles() -> None:
    job = Job.create(
        title="Software Engineer",
        company="Enterprise",
        url="https://enterprise.com/3",
        source="remotive",
        description="Requires 4+ years of professional backend engineering experience with Java.",
    )
    eligible, reason = is_experience_eligible(job, max_years=1)
    assert eligible is False
    assert reason is not None


def test_experience_filter_accepts_internship_and_freshers() -> None:
    job1 = Job.create(
        title="SDE Intern",
        company="Google",
        url="https://google.com/careers/intern",
        source="greenhouse",
        description="Open to current students in computer science or related degree programs.",
    )
    eligible1, _ = is_experience_eligible(job1, max_years=1)
    assert eligible1 is True

    job2 = Job.create(
        title="Graduate Engineer Trainee",
        company="Canonical",
        url="https://canonical.com/careers/get",
        source="greenhouse",
        description="Entry level role for 0-1 years of experience.",
    )
    eligible2, _ = is_experience_eligible(job2, max_years=1)
    assert eligible2 is True


def test_unpaid_filter_detects_unpaid_internships() -> None:
    job = Job.create(
        title="Marketing & Tech Intern",
        company="Unpaid Startup",
        url="https://startup.com/unpaid",
        source="remotive",
        description="This is an unpaid internship for college credit.",
    )
    assert is_unpaid_role(job) is True
