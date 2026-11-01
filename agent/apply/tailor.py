"""Application tailoring engine that specializes ResumeData for a specific target job."""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile, ProjectItem
from agent.resume.schema import (
    ResumeData,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
)
from agent.resume.verifier import ResumeVerifier, VerificationError

logger = logging.getLogger(__name__)


def extract_keywords_from_job(job: Job) -> Set[str]:
    """Extract normalized technical and domain keywords from a job posting.

    Args:
        job: Target Job instance.

    Returns:
        Set of lowercase alphanumeric keyword strings.
    """
    raw_text = f"{job.title} {job.description} {' '.join(job.tags)}"
    # Tokenize words, keeping plus signs and hashes (e.g. c++, c#, .net)
    tokens = re.findall(r"\b[A-Za-z0-9+#.-]+\b", raw_text.lower())
    clean_set: Set[str] = set()
    for t in tokens:
        cleaned = re.sub(r"^[^a-z0-9]+|[^a-z0-9+#]+$", "", t)
        if len(cleaned) >= 2:
            clean_set.add(cleaned)
    return clean_set


def calculate_project_match_score(
    project: ProjectItem,
    job_keywords: Set[str],
    job: Job,
) -> float:
    """Calculate job-specific relevance score for a profile project.

    Args:
        project: Candidate ProjectItem.
        job_keywords: Set of extracted job keywords.
        job: Target Job instance.

    Returns:
        Relevance score (higher is more relevant).
    """
    score = 0.0

    # 1. Tech stack overlap (strongest signal: 10 pts per matching technology)
    for tech in project.stack:
        norm_tech = re.sub(r"[^a-z0-9]", "", tech.lower())
        for kw in job_keywords:
            norm_kw = re.sub(r"[^a-z0-9]", "", kw)
            if norm_tech == norm_kw and len(norm_tech) > 1:
                score += 10.0
                break
            elif norm_tech in norm_kw or norm_kw in norm_tech:
                if len(norm_tech) >= 4 and len(norm_kw) >= 4:
                    score += 5.0
                    break

    # 2. Textual relevance in highlights and description (3 pts per keyword match)
    proj_text = f"{project.name} {project.description or ''} " + " ".join(
        h.text for h in project.highlights
    )
    proj_tokens = set(re.findall(r"\b[a-z0-9]+\b", proj_text.lower()))
    overlap = proj_tokens.intersection(job_keywords)
    score += min(len(overlap) * 2.5, 20.0)

    # 3. Base quality signal (stars, rich bullet points)
    score += min(project.stars * 2.0, 6.0)
    score += min(len(project.highlights) * 2.0, 8.0)

    return score


class ResumeTailorer:
    """Tailors ResumeData to mirror job description keywords and prioritize relevant experience."""

    def __init__(self, verifier: Optional[ResumeVerifier] = None) -> None:
        """Initialize the ResumeTailorer.

        Args:
            verifier: ResumeVerifier to validate tailored resume (defaults to strict=True).
        """
        self.verifier = verifier or ResumeVerifier(strict=True)

    def tailor(
        self,
        profile: MasterProfile,
        job: Job,
        max_projects: int = 4,
        max_bullets_per_item: int = 3,
    ) -> Tuple[ResumeData, Dict[str, object]]:
        """Synthesize and tailor a verified ResumeData instance for the given Job.

        Args:
            profile: Source MasterProfile (ground truth).
            job: Target Job posting.
            max_projects: Number of top matching projects to select.
            max_bullets_per_item: Maximum bullets per project/experience.

        Returns:
            Tuple of (tailored ResumeData, tailoring metadata summary).

        Raises:
            VerificationError: If any fact fails verification against the master profile.
        """
        job_keywords = extract_keywords_from_job(job)

        # 1. Contact & Header
        pi = profile.personal_info
        github_url = pi.links.get("github")
        linkedin_url = pi.links.get("linkedin")

        # 2. Re-order Skills by Job Relevance
        raw_job_text = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
        norm_job_text = " " + re.sub(r"[^a-z0-9]+", " ", raw_job_text) + " "
        title_lower = " " + re.sub(r"[^a-z0-9]+", " ", job.title.lower()) + " "
        tags_lower = " " + " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower()) for t in job.tags) + " "

        matched_skills_set: Set[str] = set()
        skills_by_category: Dict[str, List[str]] = {}

        for skill in profile.skills:
            cat = skill.category
            if cat not in skills_by_category:
                skills_by_category[cat] = []
            if skill.name not in skills_by_category[cat]:
                skills_by_category[cat].append(skill.name)

            norm_s = " " + re.sub(r"[^a-z0-9]+", " ", skill.name.lower()).strip() + " "
            # Check for exact phrase match or token match
            if norm_s.strip() and norm_s in norm_job_text:
                matched_skills_set.add(skill.name)
            else:
                skill_tokens = norm_s.strip().split()
                if any(tok in job_keywords and len(tok) >= 3 for tok in skill_tokens):
                    matched_skills_set.add(skill.name)

        def skill_job_priority(skill_name: str) -> float:
            norm_s = " " + re.sub(r"[^a-z0-9]+", " ", skill_name.lower()).strip() + " "
            score = 0.0
            if norm_s in title_lower:
                score += 10.0
            if norm_s in tags_lower:
                score += 5.0
            if norm_s in norm_job_text:
                score += 2.0
            return score

        # Sort skills within each category: matching skills first (sorted by priority), then rest
        for cat, skills_list in list(skills_by_category.items()):
            priority = [s for s in skills_list if s in matched_skills_set]
            priority.sort(key=skill_job_priority, reverse=True)
            non_priority = [s for s in skills_list if s not in matched_skills_set]
            skills_by_category[cat] = priority + non_priority

        # 3. Score and Prioritize Projects
        scored_projects: List[Tuple[float, ProjectItem]] = []
        for p in profile.projects:
            relevance = calculate_project_match_score(p, job_keywords, job)
            scored_projects.append((relevance, p))

        # Sort descending by relevance
        scored_projects.sort(key=lambda x: x[0], reverse=True)
        selected_projects = [p for _, p in scored_projects[:max_projects]]

        resume_projects: List[ResumeProject] = []
        for p in selected_projects:
            # Sort highlights by relevance to job keywords
            def bullet_relevance(text: str) -> int:
                b_words = set(re.findall(r"\b[a-z0-9]+\b", text.lower()))
                return len(b_words.intersection(job_keywords))

            sorted_highlights = sorted(
                p.highlights, key=lambda h: bullet_relevance(h.text), reverse=True
            )
            bullets = [h.text for h in sorted_highlights[:max_bullets_per_item]]
            if not bullets and p.description:
                bullets = [p.description]

            resume_projects.append(
                ResumeProject(
                    name=p.name,
                    url=p.url,
                    stack=p.stack[:6],
                    bullets=bullets,
                )
            )

        # 4. Experience & Leadership
        resume_experience: List[ResumeExperience] = []
        for exp in profile.experience:
            dates = f"{exp.start_date or ''} – {exp.end_date or ('Present' if exp.is_current else '')}".strip(" –")

            def exp_bullet_relevance(text: str) -> int:
                b_words = set(re.findall(r"\b[a-z0-9]+\b", text.lower()))
                return len(b_words.intersection(job_keywords))

            sorted_achievements = sorted(
                exp.achievements, key=lambda a: exp_bullet_relevance(a.text), reverse=True
            )
            bullets = [ach.text for ach in sorted_achievements[:max_bullets_per_item]]
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

        tailored_resume = ResumeData(
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

        # 8. Mandatory Verification Pass (Hard Rule 2: Zero hallucination)
        self.verifier.verify(tailored_resume, profile)

        metadata: Dict[str, object] = {
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "matched_skills": sorted(list(matched_skills_set)),
            "selected_projects": [p.name for p in selected_projects],
            "total_profile_projects": len(profile.projects),
        }

        logger.info(
            f"Tailored resume generated for {job.company} - {job.title} "
            f"({len(matched_skills_set)} matched skills, {len(selected_projects)} featured projects)."
        )
        return tailored_resume, metadata
