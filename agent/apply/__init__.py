"""Application tailoring, cover letter drafting, pre-fill, and approval gate package."""

from agent.apply.approval import (
    ApprovalDecision,
    ApprovalGate,
    FieldDiff,
    PreFillSummary,
)
from agent.apply.cover_letter import (
    CoverLetterData,
    CoverLetterGenerator,
    CoverLetterVerificationError,
    CoverLetterVerifier,
)
from agent.apply.pipeline import ApplicationTailorPipeline
from agent.apply.prefill import FormPreFiller, is_sensitive_field
from agent.apply.render_cover_letter import (
    render_cover_letter_docx,
    render_cover_letter_pdf,
    render_cover_letter_text,
)
from agent.apply.tailor import ResumeTailorer

__all__ = [
    "ApplicationTailorPipeline",
    "ApprovalDecision",
    "ApprovalGate",
    "CoverLetterData",
    "CoverLetterGenerator",
    "CoverLetterVerificationError",
    "CoverLetterVerifier",
    "FieldDiff",
    "FormPreFiller",
    "PreFillSummary",
    "ResumeTailorer",
    "is_sensitive_field",
    "render_cover_letter_docx",
    "render_cover_letter_pdf",
    "render_cover_letter_text",
]


def __getattr__(name: str):
    if name in ("enqueue", "run_queue", "check_replies", "process"):
        import agent.apply.auto_apply as _aa
        return getattr(_aa, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
