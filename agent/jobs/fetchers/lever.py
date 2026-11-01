"""Lever public postings API job fetcher."""

from datetime import datetime, timezone
import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class LeverFetcher(BaseJobFetcher):
    """Fetches public job postings from Lever job boards."""

    BASE_URL = "https://api.lever.co/v0/postings/{company}"

    def __init__(self, companies: Optional[List[str]] = None, timeout: int = 15) -> None:
        super().__init__(name="lever", timeout=timeout)
        self.companies = companies or ["palantir", "netflix", "spotify"]

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch jobs from configured Lever company boards.

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
            logger.info("[lever] Fetching jobs for company '%s'...", company)

            data = self._get_json(url, params={"mode": "json"})
            if not data or not isinstance(data, list):
                continue

            for item in data:
                if limit and len(all_jobs) >= limit:
                    break

                if not isinstance(item, dict):
                    continue

                title = item.get("text", "")
                hosted_url = item.get("hostedUrl", "")
                if not title or not hosted_url:
                    continue

                categories = item.get("categories") or {}
                location_name = categories.get("location") or "Remote"
                workplace_type = (item.get("workplaceType") or "").lower()
                is_remote = workplace_type == "remote" or "remote" in location_name.lower() or "remote" in title.lower()

                tags = []
                team = categories.get("team")
                if team:
                    tags.append(team)
                commitment = categories.get("commitment")
                if commitment:
                    tags.append(commitment)

                description = (item.get("descriptionPlain") or "")[:4000]

                # Convert createdAt (ms epoch) to ISO string
                posted_at = None
                created_at_ms = item.get("createdAt")
                if isinstance(created_at_ms, (int, float)):
                    try:
                        posted_at = datetime.fromtimestamp(created_at_ms / 1000.0, tz=timezone.utc).isoformat()
                    except Exception:
                        posted_at = None

                job = Job.create(
                    title=title,
                    company=company.title(),
                    url=hosted_url,
                    source="lever",
                    location=location_name,
                    is_remote=is_remote,
                    description=description,
                    tags=tags,
                    posted_at=posted_at,
                )
                all_jobs.append(job)

        logger.info("[lever] Successfully retrieved %d jobs.", len(all_jobs))
        return all_jobs
