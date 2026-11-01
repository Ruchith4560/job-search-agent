"""RemoteOK public API job fetcher."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class RemoteOKFetcher(BaseJobFetcher):
    """Fetches remote software development jobs from RemoteOK public JSON API."""

    API_URL = "https://remoteok.com/api"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="remoteok", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch remote engineering jobs from RemoteOK.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[remoteok] Fetching jobs from RemoteOK API...")
        data = self._get_json(self.API_URL)

        if not data or not isinstance(data, list):
            logger.warning("[remoteok] Invalid or empty response from RemoteOK API.")
            return []

        jobs: List[Job] = []

        for item in data:
            if limit and len(jobs) >= limit:
                break

            if not isinstance(item, dict):
                continue

            # First element is usually legal disclaimer metadata without 'position'
            title = item.get("position")
            company = item.get("company")
            if not title or not company:
                continue

            job_id = str(item.get("id", ""))
            url = item.get("url") or f"https://remoteok.com/remote-jobs/{job_id}"
            location = item.get("location") or "Remote"
            tags = item.get("tags") or []
            raw_desc = item.get("description", "")
            clean_desc = strip_html_tags(raw_desc)[:4000]

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="remoteok",
                location=location,
                is_remote=True,
                description=clean_desc,
                tags=tags,
                posted_at=item.get("date"),
            )
            jobs.append(job)

        logger.info("[remoteok] Successfully retrieved %d jobs.", len(jobs))
        return jobs
