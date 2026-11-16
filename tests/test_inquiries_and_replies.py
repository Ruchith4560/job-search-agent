"""Tests for custom answers store, pending inquiries manager, and email reply parsing."""

from pathlib import Path
from agent.apply.inquiries import CustomAnswersStore, PendingInquiryManager, PendingInquiry
from agent.notify.email_listener import parse_reply_answers
from agent.notify.email_sender import EmailDigestSender
from agent.config import EmailConfig
from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job


def test_custom_answers_matching(tmp_path: Path) -> None:
    store_file = tmp_path / "custom_answers.json"
    store = CustomAnswersStore(store_path=str(store_file))

    # Test pre-seeded defaults
    ans1 = store.find_answer("Are you legally authorized to work in India?")
    assert ans1 is not None
    assert "authorized" in ans1.lower()

    ans2 = store.find_answer("What is your expected salary or stipend?")
    assert ans2 is not None
    assert "₹" in ans2 or "25,000" in ans2

    ans3 = store.find_answer("What is your earliest start date or notice period?")
    assert ans3 is not None
    assert "immediately" in ans3.lower() or "15 days" in ans3.lower()

    # Test saving new answer
    store.save_answer("favorite_ide", "VS Code")
    assert store.find_answer("What is your favorite IDE?") == "VS Code"


def test_pending_inquiries_lifecycle(tmp_path: Path) -> None:
    inq_file = tmp_path / "pending_inquiries.json"
    mgr = PendingInquiryManager(storage_path=str(inq_file))

    questions = [
        {"id": "Q1", "key": "notice_period", "label": "What is your notice period?"},
        {"id": "Q2", "key": "work_authorization", "label": "Are you eligible to work in India?"},
    ]

    inquiry = mgr.create_or_update(
        job_id="test1234",
        company="TechCorp",
        title="Python Intern",
        portal_url="https://techcorp.com/jobs/1",
        questions=questions,
    )

    assert inquiry.status == "waiting_for_reply"
    pending = mgr.get_pending()
    assert len(pending) == 1
    assert pending[0].company == "TechCorp"

    # Record answers
    updated = mgr.record_answers("test1234", {"Q1": "Immediate", "Q2": "Yes"})
    assert updated is not None
    assert updated.status == "answered"
    assert updated.answers["Q1"] == "Immediate"
    assert len(mgr.get_pending()) == 0


def test_parse_reply_answers_variations() -> None:
    questions = [
        {"id": "Q1", "label": "What is your notice period?"},
        {"id": "Q2", "label": "Are you authorized to work in India?"},
    ]

    # Variation 1: Q1: / Q2: formatted
    email_text_1 = """Hi Agent,
Q1: Immediate availability
Q2: Yes, Indian citizen

Thanks,
Ruchith
> On Mon, Nov 16, 2026 at 6:00 AM Agent wrote:
> What is your notice period?
"""
    ans1 = parse_reply_answers(email_text_1, questions)
    assert ans1.get("Q1") == "Immediate availability"
    assert ans1.get("Q2") == "Yes, Indian citizen"

    # Variation 2: Numbered 1. 2.
    email_text_2 = """1. 15 days notice
2. Yes
"""
    ans2 = parse_reply_answers(email_text_2, questions)
    assert ans2.get("Q1") == "15 days notice"
    assert ans2.get("Q2") == "Yes"

    # Variation 3: Plain lines
    email_text_3 = """Immediate
Yes
"""
    ans3 = parse_reply_answers(email_text_3, questions)
    assert ans3.get("Q1") == "Immediate"
    assert ans3.get("Q2") == "Yes"


def test_inquiry_email_preview_dispatch(tmp_path: Path) -> None:
    preview_file = tmp_path / "inquiry_preview.html"
    cfg = EmailConfig(
        enabled=True,
        recipient_email="macharuchith1@gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="macharuchith1@gmail.com",
    )

    sender = EmailDigestSender(config=cfg, preview_output_path=str(preview_file))
    job = Job.create(
        title="Full Stack Intern",
        company="GlobalTech",
        url="https://globaltech.com/apply",
        source="greenhouse",
    )

    questions = [
        {"id": "Q1", "label": "Expected monthly stipend?"},
        {"id": "Q2", "label": "Notice period?"},
    ]

    res = sender.dispatch_inquiry_email(
        job=job,
        questions=questions,
        candidate_name="Ruchith Macha",
        dry_run=True,
    )

    assert res["status"] == "preview_saved"
    p_path = Path(res["preview_path"])
    assert p_path.exists()
    content = p_path.read_text(encoding="utf-8")
    assert "GlobalTech" in content
    assert "Full Stack Intern" in content
    assert "Expected monthly stipend?" in content
    assert "Q1" in content
