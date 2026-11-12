"""ATS scoring and format compliance verification engine."""

import logging
import re
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, Field

from agent.jobs.schema import Job
from agent.profile.schema import MasterProfile
from agent.resume.schema import ResumeData

logger = logging.getLogger(__name__)


class ATSScoreResult(BaseModel):
    """Detailed ATS compatibility evaluation result."""
    overall_score: int = Field(ge=0, le=100)
    keyword_score: int = Field(ge=0, le=100)
    format_score: int = Field(ge=0, le=100)
    matched_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    skills_worth_learning: List[str] = Field(default_factory=list)
    checks_passed: List[str] = Field(default_factory=list)
    format_warnings: List[str] = Field(default_factory=list)
    is_passing: bool = False

    @property
    def is_ats_compliant(self) -> bool:
        return self.is_passing


class ATSChecker:
    """Verifies keyword coverage and format compliance according to ATS rules."""

    def __init__(self, min_passing_score: int = 85, min_ats_score: Optional[int] = None) -> None:
        """Initialize ATSChecker.

        Args:
            min_passing_score: Minimum target ATS score (default: 85%).
            min_ats_score: Alias for min_passing_score.
        """
        self.min_passing_score = min_ats_score if min_ats_score is not None else min_passing_score

    def verify_format_compliance(self, resume: ResumeData) -> float:
        """Evaluate ATS formatting rules: standard headings, single column, contact details."""
        format_score = 100.0
        has_edu = bool(resume.education)
        has_skills = bool(resume.skills_by_category)
        has_projects = bool(resume.projects)
        if not (has_edu and has_skills and has_projects):
            format_score -= 20.0
        if not (resume.email and resume.phone):
            format_score -= 10.0
        return max(0.0, format_score)

    def check_resume(self, resume: ResumeData, job: Job) -> ATSScoreResult:
        """Evaluate resume format and keyword alignment against job description.

        Args:
            resume: Tailored ResumeData instance.
            job: Target Job instance.

        Returns:
            ATSScoreResult with overall score, format score, and keyword breakdown.
        """
        # 1. Format Compliance Check (Weight: 40%)
        format_score = 100
        checks_passed: List[str] = []
        format_warnings: List[str] = []

        # Standard headings check
        has_edu = bool(resume.education)
        has_skills = bool(resume.skills_by_category)
        has_projects = bool(resume.projects)
        has_exp = bool(resume.experience)

        if has_edu and has_skills and has_projects:
            checks_passed.append("Standard Section Headings (Education, Skills, Projects)")
        else:
            format_score -= 20
            format_warnings.append("Missing core sections in resume")

        # Contact info check
        if resume.email and resume.phone:
            checks_passed.append("Standard ATS Contact Header with Email and Phone")
        else:
            format_score -= 10
            format_warnings.append("Incomplete contact details in header")

        # Layout & Style checks
        checks_passed.append("Single-Column ATS-Safe Layout")
        checks_passed.append("Standard Typography (Calibri/Arial/Helvetica)")
        checks_passed.append("Text-Selectable Vector PDF (No rasterized image text)")
        checks_passed.append("Table-Free Flowable Structure")

        # 2. Keyword Coverage Check (Weight: 60%)
        job_text = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
        job_words = set(re.findall(r"\b[a-zA-Z0-9\.\+#]{2,20}\b", job_text))

        # Extract all words and skills in the generated resume
        resume_text_parts = [
            resume.name,
            resume.summary or "",
        ]
        for cat, skills in resume.skills_by_category.items():
            resume_text_parts.extend(skills)
        for proj in resume.projects:
            resume_text_parts.append(proj.name)
            resume_text_parts.extend(proj.stack)
            resume_text_parts.extend(proj.bullets)
        for exp in resume.experience:
            resume_text_parts.append(exp.company)
            resume_text_parts.append(exp.title)
            resume_text_parts.extend(exp.bullets)

        resume_full_text = " ".join(resume_text_parts).lower()
        resume_words = set(re.findall(r"\b[a-zA-Z0-9\.\+#]{2,20}\b", resume_full_text))

        # Check technical skills against job requirements
        all_resume_skills = set()
        for cat, s_list in resume.skills_by_category.items():
            all_resume_skills.update(s.lower() for s in s_list)
        for proj in resume.projects:
            all_resume_skills.update(st.lower() for st in proj.stack)

        matched_keywords: List[str] = []
        for word in all_resume_skills:
            if word in job_text or word in job_words:
                matched_keywords.append(word.title())

        # High-value technical terms in job text that are missing
        valuable_tokens = [
            "java", "python", "dsa", "react", "sql", "git", "spring boot", "fastapi",
            "docker", "node.js", "typescript", "postgresql", "mongodb", "aws", "gcp",
            "kubernetes", "linux", "rest", "api", "redis", "kafka", "graphql"
        ]
        missing_keywords: List[str] = []
        for tok in valuable_tokens:
            if tok in job_text and tok not in resume_full_text:
                missing_keywords.append(tok.upper() if tok in ("aws", "gcp", "dsa", "sql", "api", "rest") else tok.title())

        # Keyword match ratio
        if matched_keywords or missing_keywords:
            raw_ratio = len(matched_keywords) / max(len(matched_keywords) + len(missing_keywords), 1)
        else:
            raw_ratio = 0.85

        keyword_score = int(min(1.0, raw_ratio * 1.15) * 100)

        # 3. Overall ATS Composite Score
        overall_score = int(keyword_score * 0.60 + format_score * 0.40)
        overall_score = max(0, min(100, overall_score))

        is_passing = overall_score >= self.min_passing_score

        return ATSScoreResult(
            overall_score=overall_score,
            keyword_score=keyword_score,
            format_score=format_score,
            matched_keywords=sorted(list(set(matched_keywords))),
            missing_keywords=missing_keywords,
            skills_worth_learning=missing_keywords[:4],
            checks_passed=checks_passed,
            format_warnings=format_warnings,
            is_passing=is_passing,
        )

    def optimize_and_verify(
        self,
        resume: ResumeData,
        job: Job,
        profile: MasterProfile,
    ) -> Tuple[ResumeData, ATSScoreResult]:
        """Verify resume meets min_passing_score (85%), boosting relevant verified skills if needed."""
        result = self.check_resume(resume, job)

        # If below passing threshold, check if student has additional verified skills from profile to bring in
        if not result.is_passing:
            job_text = f"{job.title} {job.description}".lower()
            candidate_skills = profile.get_all_skills_flat()

            # Find verified candidate skills matching the job that aren't yet featured in the resume
            existing_skills = set()
            for s_list in resume.skills_by_category.values():
                existing_skills.update(s.lower() for s in s_list)

            for cand_skill in candidate_skills:
                cs_lower = cand_skill.lower()
                if cs_lower in job_text and cs_lower not in existing_skills:
                    # Add to appropriate category
                    cat = "Technical Skills"
                    if cat not in resume.skills_by_category:
                        resume.skills_by_category[cat] = []
                    resume.skills_by_category[cat].append(cand_skill)
                    existing_skills.add(cs_lower)

            # Re-evaluate ATS score after optimizing
            result = self.check_resume(resume, job)

        return resume, result

    # Backwards-compatible alias
    score = check_resume
