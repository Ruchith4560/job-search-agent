"""Job discovery aggregator orchestrating multiple legal job boards."""

import logging
from typing import Dict, List, Optional, Tuple
from agent.config import AppConfig
from agent.jobs.db import JobDatabase
from agent.jobs.dedupe import deduplicate_jobs
from agent.jobs.fetchers.adzuna import AdzunaFetcher
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.greenhouse import GreenhouseFetcher
from agent.jobs.fetchers.lever import LeverFetcher
from agent.jobs.fetchers.remotive import RemotiveFetcher
from agent.jobs.fetchers.remoteok import RemoteOKFetcher
from agent.jobs.filters import apply_hard_filters
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class JobAggregator:
    """Coordinates fetching from Greenhouse, Lever, Remotive, RemoteOK, and Adzuna."""

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        """Initialize aggregator with fetchers configured according to settings."""
        self.config = config or AppConfig()
        self.fetchers: Dict[str, BaseJobFetcher] = {
            "remotive": RemotiveFetcher(),
            "remoteok": RemoteOKFetcher(),
            "greenhouse": GreenhouseFetcher(companies=self.config.jobs.greenhouse_companies),
            "lever": LeverFetcher(companies=self.config.jobs.lever_companies),
            "adzuna": AdzunaFetcher(),
        }

    def fetch_raw(
        self,
        sources: Optional[List[str]] = None,
        limit_per_source: Optional[int] = None,
    ) -> List[Job]:
        """Fetch raw job listings across chosen sources with isolated error handling.

        Args:
            sources: List of source names to fetch from (defaults to config.jobs.sources).
            limit_per_source: Max jobs per source.

        Returns:
            Consolidated list of raw Job objects.
        """
        target_sources = sources or self.config.jobs.sources
        limit = limit_per_source or self.config.jobs.max_jobs_per_source
        all_raw_jobs: List[Job] = []

        for src in target_sources:
            src_key = src.lower().strip()
            fetcher = self.fetchers.get(src_key)
            if not fetcher:
                logger.warning("Unknown job board source '%s'. Skipping.", src)
                continue

            try:
                logger.info("Executing fetcher for '%s' (limit: %d)...", src_key, limit)
                jobs = fetcher.fetch(limit=limit)
                all_raw_jobs.extend(jobs)
                logger.info("[%s] Ingested %d raw jobs.", src_key, len(jobs))
            except Exception as e:
                logger.error("Error executing fetcher for '%s': %s", src_key, e, exc_info=True)

        return all_raw_jobs

    def fetch_and_store(
        self,
        db: Optional[JobDatabase] = None,
        sources: Optional[List[str]] = None,
        limit_per_source: Optional[int] = None,
    ) -> Tuple[List[Job], List[Tuple[Job, str]], int, int]:
        """Full pipeline: Fetch -> De-duplicate -> Hard filter -> Store in SQLite.

        Args:
            db: Optional JobDatabase instance.
            sources: Optional source list override.
            limit_per_source: Max jobs per source.

        Returns:
            Tuple of (accepted_jobs, rejected_jobs_with_reasons, inserted_count, updated_count).
        """
        database = db or JobDatabase(self.config.paths.tracker_db_file)

        # 1. Fetch raw jobs
        raw_jobs = self.fetch_raw(sources=sources, limit_per_source=limit_per_source)

        # 2. De-duplicate by canonical ID and (company, title)
        deduped_jobs = deduplicate_jobs(raw_jobs)

        # 3. Apply Hard Filters
        accepted, rejected = apply_hard_filters(deduped_jobs, self.config)

        # 4. Store in SQLite
        inserted, updated = database.upsert_jobs(accepted)
        logger.info(
            "Database sync complete: %d newly inserted, %d updated. Total active: %d",
            inserted,
            updated,
            database.count_total(),
        )

        return accepted, rejected, inserted, updated
