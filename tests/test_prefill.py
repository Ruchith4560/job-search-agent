"""Unit tests for the Playwright-based form pre-fill engine and field mapping."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from agent.apply.approval import ApprovalDecision, ApprovalGate, FieldDiff
from agent.apply.prefill import FormPreFiller
from agent.jobs.schema import Job
from agent.profile.schema import (
    EducationItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)


@pytest.fixture
def sample_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Full-Stack Developer",
            email="ruchith@example.com",
            phone="1234567890",
            location="Hyderabad, India",
            links={
                "github": "https://github.com/Ruchith4560",
                "linkedin": "https://linkedin.com/in/ruchith-macha",
            },
        ),
        skills=[
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="React", category="Frameworks", source="github"),
        ],
        education=[
            EducationItem(school="Anurag University", degree="B.Tech", source="linkedin")
        ],
        projects=[
            ProjectItem(
                name="travel_expense_calculator",
                stack=["Java", "Spring Boot", "React"],
                source="github",
            )
        ],
    )


@pytest.fixture
def sample_job() -> Job:
    return Job.create(
        title="Full Stack Software Engineer",
        company="GlobalTech",
        url="https://boards.greenhouse.io/globaltech/jobs/123",
        source="greenhouse",
    )


def test_form_prefiller_flow_approve(
    sample_profile: MasterProfile, sample_job: Job, tmp_path: Path
) -> None:
    output_dir = tmp_path / "output"

    # Mock Playwright components
    mock_page = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    mock_playwright_ctx = MagicMock()
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    gate = ApprovalGate(interactive=False)
    prefiller = FormPreFiller(approval_gate=gate, headless=True)

    with patch("agent.apply.prefill.sync_playwright") as mock_sync:
        mock_sync.return_value.__enter__.return_value = mock_playwright_ctx

        result = prefiller.prefill_and_submit(
            profile=sample_profile,
            job=sample_job,
            resume_pdf_path=str(tmp_path / "resume.pdf"),
            cover_letter_txt_path=str(tmp_path / "cover_letter.txt"),
            output_dir=str(output_dir),
            auto_decision=ApprovalDecision.APPROVE,
        )

        assert result["decision"] == "approve"
        assert result["status"] == "applied"
        assert result["company"] == "GlobalTech"
        assert result["job_id"] == sample_job.id

        # Verify browser was navigated and closed
        mock_page.goto.assert_called_once()
        mock_browser.close.assert_called_once()


def test_form_prefiller_flow_manual_review(
    sample_profile: MasterProfile, sample_job: Job, tmp_path: Path
) -> None:
    output_dir = tmp_path / "output"

    mock_page = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    mock_playwright_ctx = MagicMock()
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    gate = ApprovalGate(interactive=False)
    prefiller = FormPreFiller(approval_gate=gate, headless=True)

    with patch("agent.apply.prefill.sync_playwright") as mock_sync:
        mock_sync.return_value.__enter__.return_value = mock_playwright_ctx

        result = prefiller.prefill_and_submit(
            profile=sample_profile,
            job=sample_job,
            output_dir=str(output_dir),
            auto_decision=ApprovalDecision.MANUAL,
        )

        assert result["decision"] == "manual"
        assert result["status"] == "prefilled"
        mock_browser.close.assert_called_once()


def test_form_prefiller_flow_cancel(
    sample_profile: MasterProfile, sample_job: Job, tmp_path: Path
) -> None:
    output_dir = tmp_path / "output"

    mock_page = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    mock_playwright_ctx = MagicMock()
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    gate = ApprovalGate(interactive=False)
    prefiller = FormPreFiller(approval_gate=gate, headless=True)

    with patch("agent.apply.prefill.sync_playwright") as mock_sync:
        mock_sync.return_value.__enter__.return_value = mock_playwright_ctx

        result = prefiller.prefill_and_submit(
            profile=sample_profile,
            job=sample_job,
            output_dir=str(output_dir),
            auto_decision=ApprovalDecision.CANCEL,
        )

        assert result["decision"] == "cancel"
        assert result["status"] == "cancelled"
        mock_browser.close.assert_called_once()
