"""Remotive public API job fetcher (Disabled: Remotive now requires payment)."""

import html
import logging
import re
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher, strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class RemotiveFetcher(BaseJobFetcher):
    """Fetches software development jobs from Remotive (Disabled due to paid access wall)."""

    API_URL = "https://remotive.com/api/remote-jobs"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="remotive", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch remote software engineering jobs from Remotive.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[remotive] Fetching jobs from Remotive API...")
        params = {"category": "software-dev"}
        data = self._get_json(self.API_URL, params=params)

        if not data or "jobs" not in data:
            logger.warning("[remotive] No jobs payload received.")
            return []

        raw_jobs = data.get("jobs", [])
        jobs: List[Job] = []

        for item in raw_jobs:
            if limit and len(jobs) >= limit:
                break

            title = item.get("title", "")
            company = item.get("company_name", "")
            url = item.get("url", "")
            if not title or not company or not url:
                continue

            location = item.get("candidate_required_location") or "Remote / Worldwide"
            tags = item.get("tags", [])
            raw_desc = item.get("description", "")
            clean_desc = strip_html_tags(raw_desc)[:4000]

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="remotive",
                location=location,
                is_remote=True,
                description=clean_desc,
                tags=tags,
                posted_at=item.get("publication_date"),
            )
            jobs.append(job)

        logger.info("[remotive] Successfully retrieved %d jobs.", len(jobs))
        return jobs
