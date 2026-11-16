"""Custom answers store and pending inquiries manager for job applications."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ANSWERS = {
    "work_authorization": "Yes, legally authorized to work in India without sponsorship",
    "visa_sponsorship": "No, I do not require visa sponsorship",
    "notice_period": "Immediately available / 15 days",
    "start_date": "Immediately available",
    "current_location": "Hyderabad, Telangana, India",
    "willing_to_relocate": "Yes, open to relocation across India and remote roles",
    "expected_stipend": "₹25,000 - ₹40,000 / month (negotiable)",
    "graduation_year": "2028",
    "university": "Anurag University",
    "degree": "B.Tech in Computer Science and Engineering",
    "cgpa": "8.5 / 10",
    "gender": "Male",
    "years_of_experience": "1 year (academic, projects, and club leadership)",
}

KEYWORD_MAP = {
    ("authorized", "authorization", "legally authorized", "eligible to work", "work permit", "citizen"): "work_authorization",
    ("sponsorship", "require sponsorship", "future sponsorship", "visa"): "visa_sponsorship",
    ("notice period", "how soon", "when can you start", "available to start", "start date", "earliest start"): "notice_period",
    ("location", "city", "where are you located", "based"): "current_location",
    ("relocate", "relocation", "willing to relocate", "open to relocation"): "willing_to_relocate",
    ("stipend", "salary expectation", "expected salary", "compensation", "expected ctc", "desired salary"): "expected_stipend",
    ("graduation", "graduating", "passout", "year of graduation", "expected graduation"): "graduation_year",
    ("college", "university", "institute", "school"): "university",
    ("degree", "major", "field of study", "branch"): "degree",
    ("gpa", "cgpa", "percentage", "marks"): "cgpa",
    ("gender",): "gender",
    ("years of experience", "experience in years", "total experience", "how many years"): "years_of_experience",
}


class CustomAnswersStore:
    """Manages persistent custom form answers and question matching."""

    def __init__(self, store_path: str = "data/custom_answers.json") -> None:
        self.path = Path(store_path)
        self.answers: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.is_file():
            try:
                self.answers = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not load custom answers ({e}). Initializing defaults.")
                self.answers = dict(DEFAULT_ANSWERS)
        else:
            self.answers = dict(DEFAULT_ANSWERS)
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.answers, indent=2, ensure_ascii=False), encoding="utf-8")

    def find_answer(self, question_text: str) -> Optional[str]:
        """Attempt to match a form question text against known answers."""
        if not question_text:
            return None

        q_lower = question_text.lower().strip()

        # 1. Exact or direct key match (with spaces and underscores)
        for key, val in self.answers.items():
            key_space = key.replace("_", " ")
            if key in q_lower or key_space in q_lower or q_lower in key:
                return val
            words = [w for w in key.split("_") if len(w) > 2]
            if len(words) >= 2 and all(w in q_lower for w in words):
                return val

        # 2. Keyword heuristic matching
        for keywords, answer_key in KEYWORD_MAP.items():
            if any(kw in q_lower for kw in keywords):
                if answer_key in self.answers:
                    return self.answers[answer_key]

        return None

    def save_answer(self, key_or_question: str, answer: str) -> str:
        """Store a new answer for future automated reuse."""
        clean_key = re.sub(r"[^a-zA-Z0-9]+", "_", key_or_question).strip("_").lower()[:40]
        self.answers[clean_key] = answer.strip()
        self._save()
        logger.info(f"Learned answer for '{clean_key}': {answer}")
        return clean_key

    def get_all(self) -> Dict[str, str]:
        return dict(self.answers)


@dataclass
class PendingInquiry:
    """Represents a job application paused waiting for applicant clarification."""

    job_id: str
    company: str
    title: str
    portal_url: str
    questions: List[Dict[str, str]]  # [{"id": "Q1", "key": "notice_period", "label": "..."}]
    status: str = "waiting_for_reply"  # waiting_for_reply, answered, applied
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    answered_at: Optional[str] = None
    answers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingInquiry":
        return cls(**data)


class PendingInquiryManager:
    """Tracks paused job applications awaiting candidate answers via email."""

    def __init__(self, storage_path: str = "data/pending_inquiries.json") -> None:
        self.path = Path(storage_path)
        self.inquiries: Dict[str, PendingInquiry] = {}
        self._load()

    def _load(self) -> None:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.inquiries = {
                    item["job_id"]: PendingInquiry.from_dict(item) for item in data
                }
            except Exception as e:
                logger.warning(f"Error loading pending inquiries ({e}). Starting fresh.")
                self.inquiries = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = [inq.to_dict() for inq in self.inquiries.values()]
        self.path.write_text(json.dumps(serialized, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_or_update(
        self,
        job_id: str,
        company: str,
        title: str,
        portal_url: str,
        questions: List[Dict[str, str]],
    ) -> PendingInquiry:
        inquiry = PendingInquiry(
            job_id=job_id,
            company=company,
            title=title,
            portal_url=portal_url,
            questions=questions,
            status="waiting_for_reply",
        )
        self.inquiries[job_id] = inquiry
        self._save()
        return inquiry

    def get_inquiry(self, job_id: str) -> Optional[PendingInquiry]:
        return self.inquiries.get(job_id)

    def get_pending(self) -> List[PendingInquiry]:
        return [inq for inq in self.inquiries.values() if inq.status == "waiting_for_reply"]

    def record_answers(self, job_id: str, answers: Dict[str, str]) -> Optional[PendingInquiry]:
        inquiry = self.inquiries.get(job_id)
        if not inquiry:
            # Try prefix match
            for jid, inq in self.inquiries.items():
                if jid.startswith(job_id.lower()):
                    inquiry = inq
                    break

        if inquiry:
            inquiry.answers.update(answers)
            inquiry.status = "answered"
            inquiry.answered_at = datetime.now(timezone.utc).isoformat()
            self._save()
        return inquiry

    def mark_applied(self, job_id: str) -> None:
        if job_id in self.inquiries:
            self.inquiries[job_id].status = "applied"
            self._save()
