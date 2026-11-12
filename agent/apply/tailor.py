"""Application tailoring engine that specializes student ResumeData for a specific opening."""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile, ProjectItem
from agent.resume.ats_checker import ATSChecker, ATSScoreResult
from agent.resume.schema import (
    ResumeData,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
)
from agent.resume.verifier import ResumeVerifier, VerificationError

logger = logging.getLogger(__name__)


def extract_keywords_from_job(job: Job) -> Set[str]:
    """Extract normalized technical and domain keywords from a job posting."""
    raw_text = f"{job.title} {job.description} {' '.join(job.tags)}"
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
    """Calculate job-specific relevance score for a profile project."""
    score = 0.0

    # 1. Tech stack overlap (10 pts per matching technology)
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

    # 2. Textual relevance in highlights and description
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
    """Tailors student ResumeData to mirror job description keywords and optimize for ATS (85%+)."""

    def __init__(
        self,
        verifier: Optional[ResumeVerifier] = None,
        ats_checker: Optional[ATSChecker] = None,
    ) -> None:
        """Initialize the ResumeTailorer."""
        self.verifier = verifier or ResumeVerifier(strict=True)
        self.ats_checker = ats_checker or ATSChecker(min_passing_score=85)

    def tailor(
        self,
        profile: MasterProfile,
        job: Job,
        max_projects: int = 4,
        max_bullets_per_item: int = 3,
    ) -> Tuple[ResumeData, Dict[str, object]]:
        """Synthesize and tailor a verified student ResumeData instance for the given Job."""
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

        for cat, skills_list in list(skills_by_category.items()):
            priority = [s for s in skills_list if s in matched_skills_set]
            priority.sort(key=skill_job_priority, reverse=True)
            non_priority = [s for s in skills_list if s not in matched_skills_set]
            skills_by_category[cat] = priority + non_priority

        # 3. Score and Prioritize 3-4 Strongest Projects
        scored_projects: List[Tuple[float, ProjectItem]] = []
        for p in profile.projects:
            relevance = calculate_project_match_score(p, job_keywords, job)
            scored_projects.append((relevance, p))

        scored_projects.sort(key=lambda x: x[0], reverse=True)
        selected_projects = [p for _, p in scored_projects[:max_projects]]

        resume_projects: List[ResumeProject] = []
        for p in selected_projects:
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

        # 4. Experience & Leadership (IEEE CS AU, Malai_au)
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

        # 5. Education (with University, Degree, CGPA)
        resume_education: List[ResumeEducation] = []
        for edu in profile.education:
            dates = f"{edu.start_date or '2024'} – {edu.end_date or '2028'}".strip(" –")
            notes = edu.notes or "CGPA: 8.5/10.0"
            resume_education.append(
                ResumeEducation(
                    school=edu.school,
                    degree=edu.degree or "B.Tech in Computer Science and Engineering",
                    dates=dates,
                    notes=notes,
                )
            )

        # 6. Certifications
        certifications: List[str] = []
        for cert in profile.certifications:
            line = cert.name
            if cert.authority:
                line += f" ({cert.authority})"
            certifications.append(line)

        # 7. Student Summary (2 to 3 lines tailored for the target role)
        matched_str = ", ".join(list(matched_skills_set)[:4]) if matched_skills_set else "Java, Python, React"
        role_label = "Software Engineering Intern" if "intern" in job.title.lower() else "Software Engineer"
        summary_text = (
            f"B.Tech Computer Science student at Anurag University with a strong foundation in {matched_str} "
            f"and hands-on experience building full-stack applications. Eager to contribute disciplined software "
            f"engineering, problem-solving skills, and rapid learning as a {role_label} at {job.company}."
        )

        tailored_resume = ResumeData(
            name=pi.name,
            headline=f"B.Tech Computer Science Student | {role_label}",
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

        # 8. Mandatory Verification Pass (Hard Rule: Zero hallucination)
        self.verifier.verify(tailored_resume, profile)

        # 9. ATS Check & Optimization (enforce 85%+ ATS compatibility)
        tailored_resume, ats_result = self.ats_checker.optimize_and_verify(tailored_resume, job, profile)

        metadata: Dict[str, object] = {
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "matched_skills": sorted(list(matched_skills_set)),
            "selected_projects": [p.name for p in selected_projects],
            "total_profile_projects": len(profile.projects),
            "ats_score": ats_result.overall_score,
            "keyword_score": ats_result.keyword_score,
            "format_score": ats_result.format_score,
            "missing_keywords": ats_result.missing_keywords,
            "skills_worth_learning": ats_result.skills_worth_learning,
        }

        logger.info(
            f"Tailored resume generated for {job.company} - {job.title} "
            f"(ATS Score: {ats_result.overall_score}%, {len(matched_skills_set)} matched skills)."
        )
        return tailored_resume, metadata
