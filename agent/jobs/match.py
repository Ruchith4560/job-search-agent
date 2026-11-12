"""High-level job matching pipeline coordinating vector shortlisting and student fit scoring."""

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
    """End-to-end matching pipeline: Vector shortlist -> Scoring -> Threshold filtering -> SQLite update."""

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
        top_n: int = 20,
        threshold: int = 70,
        use_llm: bool = False,
        db: Optional[JobDatabase] = None,
    ) -> List[MatchScore]:
        """Execute full matching pipeline.

        Args:
            profile: Candidate MasterProfile ground truth.
            jobs: Pool of candidate Job postings.
            top_n: Number of candidates to shortlist via vector similarity.
            threshold: Minimum score (0-100) to qualify as a match (default: 70 per requirements).
            use_llm: Whether to invoke Claude for scoring.
            db: Optional JobDatabase to persist scores and 'shortlisted' state.

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
            score = self.scorer.score(
                job=job,
                similarity=sim,
                profile=profile,
                use_llm=use_llm,
            )
            scored.append(score)

        # 3. Sort by score descending
        scored.sort(key=lambda s: s.llm_score, reverse=True)

        # 4. Filter by threshold (default: 70+)
        qualified = [s for s in scored if s.llm_score >= threshold]

        # 5. Update SQLite database with scores and status for qualified jobs
        if db:
            for s in scored:
                db.update_scores(
                    job_id=s.job_id,
                    match_score=s.llm_score,
                    ats_score=s.ats_score,
                    is_top_pick=s.is_top_pick,
                )
            for q in qualified:
                db.update_status(q.job_id, "shortlisted")

            logger.info("Updated %d qualified jobs to 'shortlisted' status in database.", len(qualified))

        logger.info(
            "Matching complete: %d evaluated, %d qualified above threshold %d.",
            len(scored),
            len(qualified),
            threshold,
        )
        return qualified
