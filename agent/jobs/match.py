"""High-level job matching pipeline coordinating vector shortlisting and Claude scoring."""

import logging
from typing import List, Optional
from agent.config import AppConfig
from agent.jobs.db import JobDatabase
from agent.jobs.embed import EmbeddingMatcher
from agent.jobs.match_schema import MatchScore
from agent.jobs.schema import Job
from agent.jobs.scorer import JobScorer
from agent.llm import ClaudeClient
from agent.profile.schema import MasterProfile

logger = logging.getLogger(__name__)


class MatchPipeline:
    """End-to-end matching pipeline: Vector shortlist -> Claude scoring -> Threshold filtering -> SQLite update."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        claude_client: Optional[ClaudeClient] = None,
    ) -> None:
        """Initialize pipeline."""
        self.config = config or AppConfig()
        self.claude_client = claude_client
        self.matcher = EmbeddingMatcher()
        self.scorer = JobScorer(claude_client=self.claude_client)

    def match_jobs(
        self,
        profile: MasterProfile,
        jobs: List[Job],
        top_n: int = 15,
        threshold: int = 65,
        use_llm: bool = True,
        db: Optional[JobDatabase] = None,
    ) -> List[MatchScore]:
        """Execute full matching pipeline.

        Args:
            profile: Candidate MasterProfile ground truth.
            jobs: Pool of candidate Job postings.
            top_n: Number of candidates to shortlist via vector similarity.
            threshold: Minimum score (0-100) to qualify as a match.
            use_llm: Whether to invoke Claude for scoring.
            db: Optional JobDatabase to persist 'shortlisted' state.

        Returns:
            Ranked list of MatchScore objects meeting the score threshold.
        """
        if not jobs:
            logger.warning("No jobs provided for matching.")
            return []

        # 1. Cheap vector similarity filter
        shortlisted = self.matcher.shortlist(profile, jobs, top_n=top_n)

        # 2. Score shortlisted jobs
        scored: List[MatchScore] = []
        for job, sim in shortlisted:
            score = self.scorer.score_job(
                job=job,
                similarity=sim,
                profile=profile,
                use_llm=use_llm,
            )
            scored.append(score)

        # 3. Sort by score descending
        scored.sort(key=lambda s: s.llm_score, reverse=True)

        # 4. Filter by threshold
        qualified = [s for s in scored if s.llm_score >= threshold]

        # 5. Update SQLite database status to 'shortlisted' for qualified jobs
        if db:
            for q in qualified:
                db.update_status(q.job_id, "shortlisted")
            logger.info("Updated %d jobs to 'shortlisted' status in database.", len(qualified))

        logger.info(
            "Matching complete: %d shortlisted, %d qualified above threshold %d.",
            len(scored),
            len(qualified),
            threshold,
        )
        return qualified
