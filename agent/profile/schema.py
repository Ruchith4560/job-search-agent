"""Master profile schema definitions enforcing strict source tracking."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

SourceType = Literal["github", "linkedin", "manual"]


class AchievementItem(BaseModel):
    """A single bullet point, achievement, or claim with verifiable source."""
    text: str
    metrics: Optional[str] = None
    source: SourceType


class SkillItem(BaseModel):
    """Technical or domain skill with categorical grouping and verifiable evidence."""
    name: str
    category: str = "General"
    evidence: Optional[str] = None
    source: SourceType


class ExperienceItem(BaseModel):
    """Work experience entry with sourced achievements."""
    company: str
    title: str
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: bool = False
    achievements: List[AchievementItem] = Field(default_factory=list)
    source: SourceType = "linkedin"


class ProjectItem(BaseModel):
    """Software project with repository URL, verified tech stack, and achievements."""
    name: str
    url: Optional[str] = None
    stack: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    highlights: List[AchievementItem] = Field(default_factory=list)
    stars: int = 0
    source: SourceType = "github"


class EducationItem(BaseModel):
    """Formal education entry."""
    school: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notes: Optional[str] = None
    source: SourceType = "linkedin"


class CertificationItem(BaseModel):
    """Verified professional certification."""
    name: str
    authority: Optional[str] = None
    url: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    license_number: Optional[str] = None
    source: SourceType = "linkedin"


class PersonalInfo(BaseModel):
    """Contact and online profile links."""
    name: str
    headline: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    links: Dict[str, str] = Field(default_factory=dict)


class ConflictItem(BaseModel):
    """Discrepancy identified between multiple sources for human resolution."""
    field: str
    description: str
    values: Dict[str, Any] = Field(default_factory=dict)


class MasterProfile(BaseModel):
    """Canonical, schema-validated master profile used as ground truth for resume generation."""
    personal_info: PersonalInfo
    summary: Optional[AchievementItem] = None
    skills: List[SkillItem] = Field(default_factory=list)
    experience: List[ExperienceItem] = Field(default_factory=list)
    projects: List[ProjectItem] = Field(default_factory=list)
    education: List[EducationItem] = Field(default_factory=list)
    certifications: List[CertificationItem] = Field(default_factory=list)
    conflicts: List[ConflictItem] = Field(default_factory=list)
    version: str = "1.0"
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_all_skills_flat(self) -> List[str]:
        """Return distinct list of all verified skill names."""
        return sorted(list({s.name for s in self.skills}))

    def get_skills_by_category(self) -> Dict[str, List[SkillItem]]:
        """Return skills grouped by category."""
        grouped: Dict[str, List[SkillItem]] = {}
        for skill in self.skills:
            grouped.setdefault(skill.category, []).append(skill)
        return grouped
