"""Himalayas public API job fetcher for remote software engineering roles."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class HimalayasFetcher(BaseJobFetcher):
    """Fetches remote software engineering and developer jobs from the public Himalayas API."""

    API_URL = "https://himalayas.app/jobs/api"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="himalayas", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch remote engineering jobs from Himalayas.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[himalayas] Fetching jobs from Himalayas API...")
        params = {"limit": limit or 50}
        data = self._get_json(self.API_URL, params=params)

        if not data or not isinstance(data, dict):
            logger.warning("[himalayas] Empty response from Himalayas API.")
            return []

        raw_jobs = data.get("jobs", [])
        jobs: List[Job] = []

        for item in raw_jobs:
            if limit and len(jobs) >= limit:
                break

            title = item.get("title", "").strip()
            company = item.get("companyName", "").strip()
            url = item.get("applicationLink") or item.get("url") or ""

            if not title or not company or not url:
                continue

            restrictions = item.get("locationRestrictions") or []
            location = ", ".join(str(r) for r in restrictions) if restrictions else "Remote / Worldwide"

            tags = []
            categories = item.get("categories") or []
            for cat in categories:
                if isinstance(cat, str):
                    tags.append(cat)
                elif isinstance(cat, dict):
                    tags.append(str(cat.get("name") or ""))

            seniority = item.get("seniority") or ""
            if isinstance(seniority, str) and seniority:
                tags.append(seniority)

            tags = list(set(t for t in tags if t))

            raw_desc = item.get("description", "")
            clean_desc = strip_html_tags(raw_desc)[:4000]

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="himalayas",
                location=location,
                is_remote=True,
                description=clean_desc,
                tags=tags,
                posted_at=str(item.get("pubDate")),
            )
            jobs.append(job)

        logger.info("[himalayas] Successfully retrieved %d jobs.", len(jobs))
        return jobs
