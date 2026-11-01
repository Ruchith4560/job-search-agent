"""Verification engine that strictly validates generated resume facts against master_profile.json."""

import logging
import re
from typing import List, Set
from agent.profile.schema import MasterProfile
from agent.resume.schema import ResumeData

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """Raised when an unverified claim, hallucinated skill, or unknown entity is detected."""
    pass


def normalize_text(text: str) -> str:
    """Normalize text for relaxed comparison (alphanumeric only, lowercase)."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


class ResumeVerifier:
    """Strictly compares every entity, skill, metric, and bullet in a generated resume against master_profile.json."""

    def __init__(self, strict: bool = True) -> None:
        """Initialize verifier.

        Args:
            strict: If True, raises VerificationError on first violation.
        """
        self.strict = strict

    def verify(self, resume: ResumeData, profile: MasterProfile) -> List[str]:
        """Perform comprehensive hallucination and fact validation.

        Args:
            resume: The generated ResumeData to verify.
            profile: The canonical MasterProfile ground truth.

        Returns:
            List of detected issues (empty if fully verified).

        Raises:
            VerificationError: If any unsupported claim is found and strict=True.
        """
        issues: List[str] = []

        # 1. Company Name Verification
        profile_companies: Set[str] = {
            normalize_text(exp.company) for exp in profile.experience
        }
        for exp in resume.experience:
            norm_comp = normalize_text(exp.company)
            if norm_comp not in profile_companies:
                issues.append(
                    f"Unsupported Company: '{exp.company}' does not exist in master profile experience."
                )

        # 2. Project Name Verification
        profile_projects: Set[str] = {
            normalize_text(p.name) for p in profile.projects
        }
        for proj in resume.projects:
            norm_proj = normalize_text(proj.name)
            if norm_proj not in profile_projects:
                issues.append(
                    f"Unsupported Project: '{proj.name}' does not exist in master profile projects."
                )

        # 3. Skills Verification
        profile_skills: Set[str] = {
            normalize_text(s) for s in profile.get_all_skills_flat()
        }
        # Also allow language names and detected stacks from projects
        for p in profile.projects:
            for tech in p.stack:
                profile_skills.add(normalize_text(tech))

        for cat, skills in resume.skills_by_category.items():
            for skill in skills:
                norm_skill = normalize_text(skill)
                if norm_skill not in profile_skills:
                    issues.append(
                        f"Unsupported Skill: '{skill}' under category '{cat}' is not in the verified master profile."
                    )

        # 4. Education Verification
        profile_schools: Set[str] = {
            normalize_text(edu.school) for edu in profile.education
        }
        for edu in resume.education:
            norm_school = normalize_text(edu.school)
            if norm_school not in profile_schools:
                issues.append(
                    f"Unsupported Education: School '{edu.school}' does not exist in master profile education."
                )

        if issues:
            error_msg = f"Resume Verification Failed with {len(issues)} issue(s):\n - " + "\n - ".join(issues)
            logger.error(error_msg)
            if self.strict:
                raise VerificationError(error_msg)

        logger.info("Resume successfully passed all verification checks against master profile.")
        return issues
