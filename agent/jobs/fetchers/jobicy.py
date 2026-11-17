"""Jobicy public API job fetcher for remote tech opportunities."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class JobicyFetcher(BaseJobFetcher):
    """Fetches remote software development and tech jobs from the public Jobicy API."""

    API_URL = "https://jobicy.com/api/v2/remote-jobs"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="jobicy", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch remote engineering jobs from Jobicy.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[jobicy] Fetching jobs from Jobicy API...")
        params = {"count": limit or 50, "industry": "tech"}
        data = self._get_json(self.API_URL, params=params)

        if not data or not isinstance(data, dict):
            # Fallback without industry parameter if empty
            data = self._get_json(self.API_URL, params={"count": limit or 50})

        if not data or not isinstance(data, dict):
            logger.warning("[jobicy] Empty response from Jobicy API.")
            return []

        raw_jobs = data.get("jobs", [])
        jobs: List[Job] = []

        for item in raw_jobs:
            if limit and len(jobs) >= limit:
                break

            title = item.get("jobTitle", "").strip()
            company = item.get("companyName", "").strip()
            url = item.get("url", "").strip()

            if not title or not company or not url:
                continue

            location = item.get("jobGeo") or "Remote"
            job_types = item.get("jobType") or []
            if isinstance(job_types, str):
                job_types = [job_types]
            industry = item.get("jobIndustry") or []
            if isinstance(industry, str):
                industry = [industry]
            tags = list(set(job_types + industry))

            raw_desc = item.get("jobDescription", "")
            clean_desc = strip_html_tags(raw_desc)[:4000]

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="jobicy",
                location=location,
                is_remote=True,
                description=clean_desc,
                tags=tags,
                posted_at=item.get("pubDate"),
            )
            jobs.append(job)

        logger.info("[jobicy] Successfully retrieved %d jobs.", len(jobs))
        return jobs
