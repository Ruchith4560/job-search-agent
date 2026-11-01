"""Resume compilation engine that synthesizes and verifies ResumeData from MasterProfile."""

import logging
from typing import Dict, List, Optional
from agent.llm import ClaudeClient, LLMError
from agent.profile.schema import MasterProfile, ProjectItem
from agent.resume.schema import (
    ResumeData,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
)
from agent.resume.verifier import ResumeVerifier, VerificationError

logger = logging.getLogger(__name__)


def score_project_relevance(project: ProjectItem) -> int:
    """Heuristic score to rank the most production-ready/impactful projects for a 1-page resume."""
    score = 0
    # Favor projects with detailed highlights/metrics
    score += len(project.highlights) * 5
    # Favor projects with diverse tech stacks (e.g. full-stack React + Spring Boot or FastAPI)
    score += min(len(project.stack) * 2, 10)
    # Stars
    score += project.stars * 3
    # Key modern frameworks
    stack_lower = " ".join(project.stack).lower()
    for tech in ("fastapi", "spring boot", "react", "next.js", "mongodb", "postgresql"):
        if tech in stack_lower:
            score += 4
    return score


class ResumeGenerator:
    """Generates an ATS-compliant, strictly verified ResumeData model from a MasterProfile."""

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        verifier: Optional[ResumeVerifier] = None,
    ) -> None:
        """Initialize ResumeGenerator.

        Args:
            claude_client: Optional ClaudeClient for polishing achievement bullets.
            verifier: Optional ResumeVerifier instance (defaults to strict=True).
        """
        self.claude_client = claude_client
        self.verifier = verifier or ResumeVerifier(strict=True)

    def generate(
        self,
        profile: MasterProfile,
        max_projects: int = 4,
        max_bullets_per_item: int = 3,
        use_llm: bool = False,
    ) -> ResumeData:
        """Compile a single-page ATS resume from MasterProfile.

        Args:
            profile: Source MasterProfile instance.
            max_projects: Maximum number of projects to feature on 1-page resume.
            max_bullets_per_item: Max bullet points per experience/project.
            use_llm: Whether to use Claude to condense bullets into action verbs.

        Returns:
            Verified ResumeData ready for rendering.

        Raises:
            VerificationError: If any fact fails verification against the master profile.
        """
        # 1. Contact & Header
        pi = profile.personal_info
        github_url = pi.links.get("github")
        linkedin_url = pi.links.get("linkedin")

        # 2. Skills
        skills_by_category: Dict[str, List[str]] = {}
        for skill in profile.skills:
            # Group into clean categories
            cat = skill.category
            if cat not in skills_by_category:
                skills_by_category[cat] = []
            if skill.name not in skills_by_category[cat]:
                skills_by_category[cat].append(skill.name)

        # 3. Rank and Select Top Projects for 1-page layout
        sorted_projects = sorted(profile.projects, key=score_project_relevance, reverse=True)
        selected_projects = sorted_projects[:max_projects]

        resume_projects: List[ResumeProject] = []
        for p in selected_projects:
            bullets = [h.text for h in p.highlights[:max_bullets_per_item]]
            if not bullets and p.description:
                bullets = [p.description]

            resume_projects.append(
                ResumeProject(
                    name=p.name,
                    url=p.url,
                    stack=p.stack[:6],  # Top 6 stack tags
                    bullets=bullets,
                )
            )

        # 4. Experience & Leadership
        resume_experience: List[ResumeExperience] = []
        for exp in profile.experience:
            dates = f"{exp.start_date or ''} – {exp.end_date or ('Present' if exp.is_current else '')}".strip(" –")
            bullets = [ach.text for ach in exp.achievements[:max_bullets_per_item]]
            resume_experience.append(
                ResumeExperience(
                    company=exp.company,
                    title=exp.title,
                    dates=dates,
                    location=exp.location,
                    bullets=bullets,
                )
            )

        # 5. Education
        resume_education: List[ResumeEducation] = []
        for edu in profile.education:
            dates = f"{edu.start_date or ''} – {edu.end_date or ''}".strip(" –")
            resume_education.append(
                ResumeEducation(
                    school=edu.school,
                    degree=edu.degree or "Degree",
                    dates=dates,
                    notes=edu.notes,
                )
            )

        # 6. Certifications
        certifications: List[str] = []
        for cert in profile.certifications:
            line = cert.name
            if cert.authority:
                line += f" ({cert.authority})"
            certifications.append(line)

        # 7. Summary
        summary_text = profile.summary.text if profile.summary else None

        resume_data = ResumeData(
            name=pi.name,
            headline=pi.headline,
            email=pi.email,
            phone=pi.phone,
            location=pi.location,
            github_url=github_url,
            linkedin_url=linkedin_url,
            summary=summary_text,
            skills_by_category=skills_by_category,
            experience=resume_experience,
            projects=resume_projects,
            education=resume_education,
            certifications=certifications,
        )

        # 8. Strict Verification Pass (Enforce Hard Rule 2)
        self.verifier.verify(resume_data, profile)

        return resume_data
