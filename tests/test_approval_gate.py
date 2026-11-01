"""Unit tests for the Human-in-the-Loop Approval Gate."""

import pytest
from agent.apply.approval import (
    ApprovalDecision,
    ApprovalGate,
    FieldDiff,
    PreFillSummary,
)
from agent.apply.prefill import is_sensitive_field


@pytest.fixture
def sample_summary() -> PreFillSummary:
    return PreFillSummary(
        job_id="test_job_123",
        company="Innovatech",
        title="Full Stack Engineer",
        application_url="https://boards.greenhouse.io/innovatech/jobs/123",
        resume_path="data/output/test/tailored_resume.pdf",
        cover_letter_path="data/output/test/cover_letter.txt",
        filled_fields=[
            FieldDiff(field_name="First Name", value="Ruchith"),
            FieldDiff(field_name="Last Name", value="Macha"),
            FieldDiff(field_name="Email", value="ruchith@example.com"),
        ],
        custom_answers=[
            FieldDiff(field_name="Favorite Stack", value="Spring Boot, React, FastAPI"),
        ],
        sensitive_skipped=[
            "Desired Salary / Compensation",
            "Are you legally authorized to work in the US without sponsorship?",
        ],
    )


def test_is_sensitive_field_detection() -> None:
    # Sensitive terms must return True
    assert is_sensitive_field("Desired Salary") is True
    assert is_sensitive_field("Target Compensation Expectations") is True
    assert is_sensitive_field("Will you now or in the future require visa sponsorship?") is True
    assert is_sensitive_field("Equal Opportunity Voluntary Self-Identification: Gender") is True
    assert is_sensitive_field("Veteran Status") is True
    assert is_sensitive_field("Disability accommodation request") is True

    # Standard fields must return False
    assert is_sensitive_field("First Name") is False
    assert is_sensitive_field("Email Address") is False
    assert is_sensitive_field("Phone Number") is False
    assert is_sensitive_field("LinkedIn Profile URL") is False
    assert is_sensitive_field("GitHub Repository") is False


def test_approval_gate_auto_decisions(sample_summary: PreFillSummary) -> None:
    gate = ApprovalGate(interactive=False)

    decision_approve = gate.request_approval(
        sample_summary, auto_decision=ApprovalDecision.APPROVE
    )
    assert decision_approve == ApprovalDecision.APPROVE

    decision_manual = gate.request_approval(
        sample_summary, auto_decision=ApprovalDecision.MANUAL
    )
    assert decision_manual == ApprovalDecision.MANUAL

    decision_cancel = gate.request_approval(
        sample_summary, auto_decision=ApprovalDecision.CANCEL
    )
    assert decision_cancel == ApprovalDecision.CANCEL


def test_approval_gate_non_interactive_fallback(sample_summary: PreFillSummary) -> None:
    gate = ApprovalGate(interactive=False)
    # When non-interactive and no auto_decision is passed, must default to MANUAL
    decision = gate.request_approval(sample_summary)
    assert decision == ApprovalDecision.MANUAL
