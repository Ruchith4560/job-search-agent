"""Greenhouse public board API job fetcher."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class GreenhouseFetcher(BaseJobFetcher):
    """Fetches public job postings from Greenhouse job boards."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"

    def __init__(self, companies: Optional[List[str]] = None, timeout: int = 15) -> None:
        super().__init__(name="greenhouse", timeout=timeout)
        self.companies = companies or ["canonical", "cloudflare", "gitlab", "discord"]

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch jobs from configured Greenhouse company boards.

        Args:
            limit: Maximum jobs to return overall.

        Returns:
            List of normalized Job instances.
        """
        all_jobs: List[Job] = []

        for company in self.companies:
            if limit and len(all_jobs) >= limit:
                break

            url = self.BASE_URL.format(company=company)
            logger.info("[greenhouse] Fetching jobs for company '%s'...", company)

            data = self._get_json(url, params={"content": "true"})
            if not data or "jobs" not in data:
                continue

            raw_jobs = data.get("jobs", [])
            for item in raw_jobs:
                if limit and len(all_jobs) >= limit:
                    break

                title = item.get("title", "")
                job_url = item.get("absolute_url", "")
                if not title or not job_url:
                    continue

                loc_dict = item.get("location") or {}
                location_name = loc_dict.get("name") or "Remote"
                is_remote = "remote" in location_name.lower() or "remote" in title.lower()

                raw_desc = item.get("content", "")
                clean_desc = strip_html_tags(raw_desc)[:4000]

                job = Job.create(
                    title=title,
                    company=company.title(),
                    url=job_url,
                    source="greenhouse",
                    location=location_name,
                    is_remote=is_remote,
                    description=clean_desc,
                    posted_at=item.get("updated_at"),
                )
                all_jobs.append(job)

        logger.info("[greenhouse] Successfully retrieved %d jobs.", len(all_jobs))
        return all_jobs
