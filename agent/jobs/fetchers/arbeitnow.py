"""Arbeitnow public API job fetcher for remote and engineering positions."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class ArbeitnowFetcher(BaseJobFetcher):
    """Fetches remote and developer jobs from the free, public Arbeitnow API."""

    API_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="arbeitnow", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch jobs from Arbeitnow.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[arbeitnow] Fetching jobs from Arbeitnow API...")
        data = self._get_json(self.API_URL)

        if not data or not isinstance(data, dict):
            logger.warning("[arbeitnow] Empty or invalid response from Arbeitnow API.")
            return []

        raw_jobs = data.get("data", [])
        jobs: List[Job] = []

        for item in raw_jobs:
            if limit and len(jobs) >= limit:
                break

            title = item.get("title", "").strip()
            company = item.get("company_name", "").strip()
            url = item.get("url", "").strip()

            if not title or not company or not url:
                continue

            location = item.get("location") or "Remote"
            is_remote = bool(item.get("remote", True))
            tags = item.get("tags") or []
            job_types = item.get("job_types") or []
            all_tags = list(set(tags + job_types))
            raw_desc = item.get("description", "")
            clean_desc = strip_html_tags(raw_desc)[:4000]

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="arbeitnow",
                location=location,
                is_remote=is_remote,
                description=clean_desc,
                tags=all_tags,
                posted_at=str(item.get("created_at")),
            )
            jobs.append(job)

        logger.info("[arbeitnow] Successfully retrieved %d jobs.", len(jobs))
        return jobs
