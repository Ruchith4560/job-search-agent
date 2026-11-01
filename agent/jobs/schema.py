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
    status: str = "found"  # found, shortlisted, prefilled, applied, interview, rejected, offer
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
    ) -> "Job":
        """Factory method that automatically generates the deterministic ID."""
        job_id = generate_job_id(company, title, url)
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
        )
