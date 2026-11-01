"""Job scoring engine utilizing Claude LLM with persistent evaluation caching."""

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


def extract_keywords_from_text(text: str) -> Set[str]:
    """Extract normalized lowercase technical tokens from job text."""
    tokens = set(re.findall(r"\b[a-zA-Z0-9\.\+#]{2,20}\b", text.lower()))
    return tokens


class JobScorer:
    """Scores candidate-job fitness using Claude LLM or deterministic fallback with cost-saving caching."""

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        cache_path: str = "data/match_cache.json",
    ) -> None:
        """Initialize scorer.

        Args:
            claude_client: Optional ClaudeClient instance for LLM scoring.
            cache_path: Path to disk cache file storing previously scored jobs.
        """
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
        """Deterministic heuristic scorer when LLM is unavailable or disabled."""
        job_text = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
        job_tokens = extract_keywords_from_text(job_text)

        verified_skills = profile.get_all_skills_flat()
        matched: List[str] = []
        for s in verified_skills:
            s_lower = s.lower()
            if s_lower in job_text or s_lower in job_tokens:
                matched.append(s)

        # Check for common tech keywords in job text that candidate lacks
        common_tech = [
            "aws", "gcp", "azure", "kubernetes", "go", "golang", "rust",
            "c++", "c#", "ruby", "rails", "graphql", "kafka", "redis",
            "terraform", "angular", "vue", "spark", "hadoop", "spring boot"
        ]
        missing: List[str] = []
        verified_lower = {s.lower() for s in verified_skills}
        for tech in common_tech:
            if tech in job_tokens and tech not in verified_lower:
                missing.append(tech.title() if tech != "aws" else "AWS")

        # Score calculation: 30% vector similarity + 70% skill coverage
        coverage_ratio = min(len(matched) / max(len(matched) + len(missing), 1), 1.0)
        composite = int((similarity * 35) + (coverage_ratio * 65))
        composite = max(10, min(98, composite))

        if composite >= 80:
            rec = "strong_match"
        elif composite >= 65:
            rec = "good_match"
        elif composite >= 50:
            rec = "weak_match"
        else:
            rec = "not_recommended"

        sample_skills = ", ".join(matched[:4]) if matched else "core engineering skills"
        reason = (
            f"Strong alignment with {sample_skills}. "
            f"Candidate satisfies key backend/development competencies with a vector affinity of {similarity:.2f}."
        )
        if missing:
            reason += f" Identified potential growth areas in {', '.join(missing[:3])}."

        return MatchScore(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            similarity_score=round(similarity, 3),
            llm_score=composite,
            matched_skills=matched[:8],
            missing_skills=missing[:6],
            reason=reason,
            recommendation=rec,
        )

    def score_job(
        self,
        job: Job,
        similarity: float,
        profile: MasterProfile,
        use_llm: bool = True,
    ) -> MatchScore:
        """Score candidate fitness against a job posting, leveraging cache to minimize LLM spend.

        Args:
            job: The target Job opening.
            similarity: Cosine similarity score (0.0 to 1.0).
            profile: Candidate MasterProfile.
            use_llm: Whether to invoke Claude for deep reasoning.

        Returns:
            MatchScore instance.
        """
        cache_key = f"{job.id}:{profile.version}"
        if cache_key in self.cache:
            logger.debug("Returning cached match score for job '%s' (%s)", job.title, job.id)
            return MatchScore.model_validate(self.cache[cache_key])

        # Attempt Claude scoring if enabled and client is present
        if use_llm and self.claude_client:
            try:
                system_prompt = (
                    "You are a principal technical recruiter and hiring director. "
                    "Evaluate candidate fit against the job posting strictly using the verifiable facts "
                    "in the master profile. NEVER assume unlisted skills. "
                    "Output valid JSON conforming to the MatchScore schema."
                )

                skills_summary = ", ".join(profile.get_all_skills_flat())
                projects_summary = "\n".join(
                    f"- {p.name}: Stack: {', '.join(p.stack)}. {p.description or ''}"
                    for p in profile.projects[:5]
                )

                prompt = (
                    f"Please score the candidate profile against this job opening.\n\n"
                    f"CANDIDATE MASTER PROFILE:\n"
                    f"Name: {profile.personal_info.name}\n"
                    f"Headline: {profile.personal_info.headline}\n"
                    f"Verified Skills: {skills_summary}\n"
                    f"Key Projects:\n{projects_summary}\n\n"
                    f"JOB OPENING:\n"
                    f"Title: {job.title}\n"
                    f"Company: {job.company}\n"
                    f"Location: {job.location or 'Remote'}\n"
                    f"Tags: {', '.join(job.tags)}\n"
                    f"Description:\n{job.description[:2500]}\n\n"
                    f"Vector Similarity Score: {similarity:.2f}\n\n"
                    f"Instructions:\n"
                    f"- Provide 'llm_score' as an integer between 0 and 100.\n"
                    f"- List 'matched_skills' present in both profile and job.\n"
                    f"- List 'missing_skills' required by job that candidate lacks.\n"
                    f"- Provide a one-paragraph 'reason' evaluating candidate readiness.\n"
                    f"- Assign 'recommendation': 'strong_match' (80+), 'good_match' (65-79), 'weak_match' (50-64), or 'not_recommended' (<50)."
                )

                score = self.claude_client.generate_json(
                    prompt=prompt,
                    schema=MatchScore,
                    system=system_prompt,
                    temperature=0.0,
                )
                score.job_id = job.id
                score.job_title = job.title
                score.company = job.company
                score.similarity_score = round(similarity, 3)

                # Persist to cache
                self.cache[cache_key] = score.model_dump()
                self._save_cache()
                return score

            except (LLMError, Exception) as e:
                logger.warning(
                    "Claude scoring failed for job '%s' (%s). Falling back to heuristic scorer.",
                    job.title,
                    e,
                )

        # Heuristic scoring fallback
        score = self._heuristic_score(job, similarity, profile)
        self.cache[cache_key] = score.model_dump()
        self._save_cache()
        return score
