"""Job discovery, fetching, deduplication, filtering, database management, and scoring."""

from agent.jobs.db import JobDatabase
from agent.jobs.dedupe import clean_url, deduplicate_jobs
from agent.jobs.embed import EmbeddingMatcher, job_to_text, profile_to_text
from agent.jobs.fetchers.aggregator import JobAggregator
from agent.jobs.filters import apply_hard_filters, is_location_acceptable, is_title_relevant
from agent.jobs.match import MatchPipeline
from agent.jobs.match_schema import MatchScore
from agent.jobs.schema import Job, generate_job_id
from agent.jobs.scorer import JobScorer

__all__ = [
    "Job",
    "generate_job_id",
    "JobDatabase",
    "JobAggregator",
    "deduplicate_jobs",
    "clean_url",
    "apply_hard_filters",
    "is_title_relevant",
    "is_location_acceptable",
    "MatchScore",
    "EmbeddingMatcher",
    "JobScorer",
    "MatchPipeline",
    "profile_to_text",
    "job_to_text",
]
