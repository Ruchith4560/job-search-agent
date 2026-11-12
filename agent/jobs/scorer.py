"""Job scoring engine evaluating student fit, stipend/package, learning value, and PPO chance."""

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.jobs.match_schema import MatchScore
from agent.jobs.schema import Job
from agent.llm import ClaudeClient, LLMError
from agent.profile.schema import MasterProfile

logger = logging.getLogger(__name__)

TOP_COMPANIES = {
    "canonical", "cloudflare", "gitlab", "discord", "stripe", "palantir",
    "netflix", "spotify", "google", "microsoft", "amazon", "uber", "atlassian",
    "adobe", "oracle", "salesforce", "cisco", "intel", "nvidia", "qualcomm",
    "razorpay", "cred", "swiggy", "zomato", "zerodha", "postman", "browserstack"
}


def extract_keywords_from_text(text: str) -> Set[str]:
    """Extract normalized lowercase technical tokens from job text."""
    tokens = set(re.findall(r"\b[a-zA-Z0-9\.\+#]{2,20}\b", text.lower()))
    return tokens


class JobScorer:
    """Scores student fitness (0-100) using Claude LLM or deterministic fallback with cost-saving caching."""

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        cache_path: str = "data/match_cache.json",
    ) -> None:
        """Initialize scorer."""
        self.claude_client = claude_client
        self.cache_path = Path(cache_path)
        self.cache: Dict[str, Dict[str, Any]] = self._load_cache()

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        """Load disk cache."""
        if self.cache_path.is_file():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Could not read match cache from %s: %s", self.cache_path, e)
        return {}

    def _save_cache(self) -> None:
        """Save disk cache."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            logger.warning("Could not save match cache to %s: %s", self.cache_path, e)

    def _heuristic_score(
        self,
        job: Job,
        similarity: float,
        profile: MasterProfile,
    ) -> MatchScore:
        """Deterministic student-focused scorer (0-100) factoring skills, stipend, role, and PPO potential."""
        job_text = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
        job_tokens = extract_keywords_from_text(job_text)

        verified_skills = profile.get_all_skills_flat()
        matched: List[str] = []
        for s in verified_skills:
            s_lower = s.lower()
            if s_lower in job_text or s_lower in job_tokens:
                matched.append(s)

        # Check for high-demand tech keywords in job text that student currently lacks
        valuable_industry_tech = [
            "aws", "gcp", "azure", "kubernetes", "go", "golang", "rust",
            "c++", "c#", "ruby", "rails", "graphql", "kafka", "redis",
            "terraform", "angular", "vue", "next.js", "spark", "hadoop"
        ]
        missing: List[str] = []
        verified_lower = {s.lower() for s in verified_skills}
        for tech in valuable_industry_tech:
            if tech in job_tokens and tech not in verified_lower:
                missing.append(tech.upper() if tech in ("aws", "gcp") else tech.title())

        # Base skill coverage calculation
        coverage_ratio = min(len(matched) / max(len(matched) + len(missing), 1), 1.0)
        score = int(coverage_ratio * 65.0 + min(similarity * 300.0, 15.0))

        # Role Bonus: prioritize internships & entry-level student roles
        is_intern = job.job_type == "internship" or any(k in job.title.lower() for k in ("intern", "trainee", "associate", "graduate", "sde"))
        if is_intern:
            score += 10

        # Core Stack Bonus: Java, Python, React, Spring Boot, FastAPI, SQL, Docker
        core_matches = sum(
            1 for c in ("java", "python", "react", "spring boot", "fastapi", "docker", "sql", "git")
            if any(c == m.lower() for m in matched)
        )
        score += min(core_matches * 2, 8)

        # Brand / Learning Value Bonus
        c_clean = re.sub(r"[^a-z0-9]", "", job.company.lower())
        is_top_brand = any(top in c_clean for top in TOP_COMPANIES)
        if is_top_brand:
            score += 5

        # Cap score between 0 and 100
        score = max(0, min(100, score))

        # Top Pick: 90+ with strong company or high stipend or PPO potential
        is_top_pick = score >= 90 or (score >= 85 and is_top_brand)

        if is_top_pick:
            rec = "top_pick"
        elif score >= 75:
            rec = "strong_match"
        elif score >= 70:
            rec = "good_match"
        elif score >= 50:
            rec = "weak_match"
        else:
            rec = "not_recommended"

        # Three-line reason format (Section 7 requirement)
        matched_str = ", ".join(matched[:4]) if matched else "core software engineering"
        reason_lines = [
            f"1. Target Fit: Directly aligns with your profile as a {job.job_type.replace('_', ' ').title()} in software engineering.",
            f"2. Stack Alignment: Strong synergy with your verified projects in {matched_str}.",
            f"3. Career Growth: Excellent hands-on learning value{' with a recognized engineering team' if is_top_brand else ''} and potential PPO track.",
        ]
        reason = "\n".join(reason_lines)

        return MatchScore(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            similarity_score=round(similarity, 3),
            llm_score=score,
            matched_skills=matched,
            missing_skills=missing,
            skills_worth_learning=missing[:4],
            reason=reason,
            recommendation=rec,
            is_top_pick=is_top_pick,
            job_type=job.job_type,
            stipend_or_salary=job.stipend_or_salary,
        )

    def _llm_score(
        self,
        job: Job,
        similarity: float,
        profile: MasterProfile,
    ) -> MatchScore:
        """Prompt Claude to evaluate student candidate fit, stipend/package, learning value, and PPO potential."""
        if not self.claude_client:
            raise LLMError("Claude client is not initialized.")

        pi = profile.personal_info
        edu = profile.education[0] if profile.education else None
        edu_str = f"{edu.degree} at {edu.school} ({edu.start_date}-{edu.end_date})" if edu else "B.Tech CSE"

        prompt = f"""You are an elite technical recruiter evaluating an internship / entry-level job opening for a B.Tech 3rd-year student.

CANDIDATE PROFILE:
Name: {pi.name}
Status: B.Tech 3rd-year student
Education: {edu_str}
Core Skills: {', '.join(profile.get_all_skills_flat()[:25])}
Verified Projects: {', '.join(p.name for p in profile.projects[:5])}

TARGET JOB OPENING:
Title: {job.title}
Company: {job.company}
Location: {job.location or 'Remote'}
Stipend/Salary: {job.stipend_or_salary or 'Not specified'}
Description: {job.description[:1200]}

EVALUATION CRITERIA:
1. Skills Match: Overlap between candidate's verified skills/projects and role requirements (0-50 pts).
2. Role Target & Eligibility: Perfect fit for a student/intern/new-grad vs requiring too much experience (0-20 pts).
3. Stipend / Compensation: Competitive stipend or package (0-15 pts).
4. Company Reputation, Learning Value & PPO Chance: (0-15 pts).

Total Score: 0 to 100.
If score >= 90 with strong company or high stipend, mark is_top_pick: true.

Respond strictly in valid JSON adhering to this schema:
{{
  "score": <int 0-100>,
  "matched_skills": [<string>, ...],
  "missing_skills": [<string>, ...],
  "skills_worth_learning": [<string>, ...],
  "is_top_pick": <boolean>,
  "three_line_reason": "1. Target Fit: ...\\n2. Stack Alignment: ...\\n3. Career Growth: ...",
  "recommendation": "top_pick" | "strong_match" | "good_match" | "weak_match" | "not_recommended"
}}"""

        response = self.claude_client.generate_json(
            prompt=prompt,
            system="You evaluate student tech internships and entry-level jobs with precision and realism.",
            temperature=0.1,
        )

        if hasattr(response, "model_dump"):
            response = response.model_dump()
        elif hasattr(response, "dict"):
            response = response.dict()

        score_val = int(response.get("score", response.get("llm_score", 50)))
        is_top = bool(response.get("is_top_pick", score_val >= 90))
        reason_val = response.get("three_line_reason", response.get("reason", "Strong alignment with candidate profile."))
        rec_val = response.get("recommendation", "top_pick" if is_top else "good_match")

        return MatchScore(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            similarity_score=round(similarity, 3),
            llm_score=score_val,
            matched_skills=response.get("matched_skills", []),
            missing_skills=response.get("missing_skills", []),
            skills_worth_learning=response.get("skills_worth_learning", []),
            reason=reason_val,
            recommendation=rec_val,
            is_top_pick=is_top,
            job_type=job.job_type,
            stipend_or_salary=job.stipend_or_salary,
        )

    def score(
        self,
        job: Job,
        similarity: float,
        profile: MasterProfile,
        use_llm: bool = False,
    ) -> MatchScore:
        """Score candidate fit against target opening with persistent caching."""
        cache_key = f"{job.id}:{profile.version}:{use_llm}"

        if cache_key in self.cache:
            data = self.cache[cache_key]
            return MatchScore(**data)

        if use_llm and self.claude_client:
            try:
                score = self._llm_score(job, similarity, profile)
            except Exception as e:
                logger.warning("LLM scoring failed (%s); falling back to heuristic engine.", e)
                score = self._heuristic_score(job, similarity, profile)
        else:
            score = self._heuristic_score(job, similarity, profile)

        # Cache result
        self.cache[cache_key] = score.model_dump()
        self._save_cache()
        return score

    # Backwards-compatible alias
    score_job = score
