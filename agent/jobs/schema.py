"""Job representation schema definitions for discovery and tracking."""

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def generate_job_id(company: str, title: str, url: str) -> str:
    """Generate a deterministic 16-character hex hash ID for a job posting.

    Args:
        company: Normalized company name.
        title: Normalized job title.
        url: Clean job URL.

    Returns:
        16-character unique identifier.
    """
    norm_c = re.sub(r"[^a-z0-9]", "", company.lower())
    norm_t = re.sub(r"[^a-z0-9]", "", title.lower())
    clean_url = url.split("?")[0].rstrip("/").lower()
    content = f"{norm_c}:{norm_t}:{clean_url}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def detect_job_type(title: str, description: str = "") -> str:
    """Classify role as internship vs full_time."""
    combined = f"{title} {description[:400]}".lower()
    if any(k in combined for k in ("intern", "internship", "trainee", "co-op", "fellow", "summer")):
        return "internship"
    return "full_time"


def extract_stipend_or_salary(
    description: str,
    salary_min: Optional[float] = None,
    salary_max: Optional[float] = None,
    salary_currency: Optional[str] = None,
) -> Optional[str]:
    """Extract human-readable stipend or salary string from fields or text."""
    if salary_min or salary_max:
        curr = salary_currency or "USD"
        if salary_min and salary_max:
            return f"{curr} {int(salary_min):,} - {int(salary_max):,}"
        elif salary_min:
            return f"{curr} {int(salary_min):,}+"
        elif salary_max:
            return f"Up to {curr} {int(salary_max):,}"

    # Search text for Indian stipend formats (e.g. ₹25,000/month or 25k/mo or 8-12 LPA)
    stipend_match = re.search(
        r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})+|\d+[kK])\s*(?:-|to|\/|per)?\s*(?:month|mo|pm|stipend)",
        description,
        re.I,
    )
    if stipend_match:
        return f"₹{stipend_match.group(1).strip()}/month"

    lpa_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+(?:\.\d+)?)?\s*(?:LPA|lpa|lakhs?)", description)
    if lpa_match:
        val1 = lpa_match.group(1)
        val2 = lpa_match.group(2)
        return f"{val1}{f' - {val2}' if val2 else ''} LPA"

    return None


def extract_duration(text: str) -> Optional[str]:
    """Extract internship duration if mentioned."""
    m = re.search(r"\b([1-6])\s*(?:-|to)?\s*([1-6])?\s*(?:months?|mos?)\b", text, re.I)
    if m:
        if m.group(2):
            return f"{m.group(1)}-{m.group(2)} months"
        return f"{m.group(1)} months"
    return None


class Job(BaseModel):
    """Normalized schema for a single job opening across all sources."""
    id: str
    title: str
    company: str
    url: str
    source: str
    location: Optional[str] = None
    is_remote: bool = False
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    posted_at: Optional[str] = None
    status: str = "found"  # found, shortlisted, emailed, approved, prefilled, applied, interview, rejected, offer
    job_type: str = "internship"  # internship or full_time
    duration: Optional[str] = None
    stipend_or_salary: Optional[str] = None
    match_score: Optional[int] = None
    ats_score: Optional[int] = None
    is_top_pick: bool = False
    emailed_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        title: str,
        company: str,
        url: str,
        source: str,
        location: Optional[str] = None,
        is_remote: bool = False,
        description: str = "",
        tags: Optional[List[str]] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        salary_currency: Optional[str] = None,
        posted_at: Optional[str] = None,
        status: str = "found",
        job_type: Optional[str] = None,
        duration: Optional[str] = None,
        stipend_or_salary: Optional[str] = None,
        match_score: Optional[int] = None,
        ats_score: Optional[int] = None,
        is_top_pick: bool = False,
    ) -> "Job":
        """Factory method that automatically generates the deterministic ID and extracts metadata."""
        job_id = generate_job_id(company, title, url)
        computed_type = job_type or detect_job_type(title, description)
        computed_stipend = stipend_or_salary or extract_stipend_or_salary(
            description, salary_min, salary_max, salary_currency
        )
        computed_duration = duration or (extract_duration(f"{title} {description}") if computed_type == "internship" else None)

        return cls(
            id=job_id,
            title=title.strip(),
            company=company.strip(),
            url=url.strip(),
            source=source.lower(),
            location=location.strip() if location else None,
            is_remote=is_remote,
            description=description.strip(),
            tags=tags or [],
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            posted_at=posted_at,
            status=status,
            job_type=computed_type,
            duration=computed_duration,
            stipend_or_salary=computed_stipend,
            match_score=match_score,
            ats_score=ats_score,
            is_top_pick=is_top_pick,
        )
