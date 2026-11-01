"""Adzuna public API job fetcher (optional API key support)."""

import logging
import os
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class AdzunaFetcher(BaseJobFetcher):
    """Fetches jobs from the Adzuna API when ADZUNA_APP_ID and ADZUNA_APP_KEY are present."""

    BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

    def __init__(self, country: str = "in", timeout: int = 15) -> None:
        super().__init__(name="adzuna", timeout=timeout)
        self.country = country.lower()
        self.app_id = os.getenv("ADZUNA_APP_ID")
        self.app_key = os.getenv("ADZUNA_APP_KEY")

    def fetch(self, limit: Optional[int] = 20) -> List[Job]:
        """Fetch software jobs from Adzuna if credentials are provided."""
        if not self.app_id or not self.app_key:
            logger.debug("[adzuna] ADZUNA_APP_ID or ADZUNA_APP_KEY not set. Skipping Adzuna.")
            return []

        url = self.BASE_URL.format(country=self.country)
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": limit or 20,
            "what": "software engineer python",
            "content-type": "application/json",
        }

        data = self._get_json(url, params=params)
        if not data or "results" not in data:
            return []

        jobs: List[Job] = []
        for item in data.get("results", []):
            title = item.get("title", "")
            company = (item.get("company") or {}).get("display_name", "Unknown")
            url = item.get("redirect_url", "")
            if not title or not url:
                continue

            loc_name = (item.get("location") or {}).get("display_name", "")
            desc = strip_html_tags(item.get("description", ""))

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="adzuna",
                location=loc_name,
                is_remote="remote" in loc_name.lower() or "remote" in title.lower(),
                description=desc,
                salary_min=item.get("salary_min"),
                salary_max=item.get("salary_max"),
                posted_at=item.get("created"),
            )
            jobs.append(job)

        return jobs
