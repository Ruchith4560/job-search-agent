"""Resume presentation data schemas for rendering and verification."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ResumeExperience(BaseModel):
    """Experience item formatted for single-page resume."""
    company: str
    title: str
    dates: str
    location: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)


class ResumeProject(BaseModel):
    """Project item formatted for single-page resume."""
    name: str
    url: Optional[str] = None
    stack: List[str] = Field(default_factory=list)
    bullets: List[str] = Field(default_factory=list)


class ResumeEducation(BaseModel):
    """Education item formatted for single-page resume."""
    school: str
    degree: str
    dates: str
    notes: Optional[str] = None


class ResumeData(BaseModel):
    """Normalized data structure ready for ATS-friendly templating and verification."""
    name: str
    headline: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    summary: Optional[str] = None
    skills_by_category: Dict[str, List[str]] = Field(default_factory=dict)
    experience: List[ResumeExperience] = Field(default_factory=list)
    projects: List[ResumeProject] = Field(default_factory=list)
    education: List[ResumeEducation] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
