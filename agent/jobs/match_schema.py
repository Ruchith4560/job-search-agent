"""Schemas for job-profile matching and evaluation scoring."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class MatchScore(BaseModel):
    """Detailed fitness evaluation of a candidate profile against a job opening."""
    job_id: str
    job_title: str
    company: str
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_score: int = Field(default=0, ge=0, le=100)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    skills_worth_learning: List[str] = Field(default_factory=list)
    reason: str
    recommendation: Literal["top_pick", "strong_match", "good_match", "weak_match", "not_recommended"] = "good_match"
    is_top_pick: bool = False
    job_type: str = "internship"
    stipend_or_salary: Optional[str] = None
    ats_score: Optional[int] = None
