"""SmartRecruiters public API fetcher for top global and Indian tech enterprise career pages."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class SmartRecruitersFetcher(BaseJobFetcher):
    """Fetches job postings from top tech companies utilizing SmartRecruiters ATS."""

    DEFAULT_COMPANIES = [
        "visa",
        "bosch",
        "square",
        "ubisoft",
        "epicgames",
        "accenture",
        "ikea",
        "publicissapient",
    ]

    API_BASE = "https://api.smartrecruiters.com/v1/companies/{company}/postings"

    def __init__(self, companies: Optional[List[str]] = None, timeout: int = 20) -> None:
        super().__init__(name="smartrecruiters", timeout=timeout)
        self.companies = companies or self.DEFAULT_COMPANIES

    def fetch(self, limit: Optional[int] = 30) -> List[Job]:
        """Fetch engineering postings from configured company career portals.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[smartrecruiters] Fetching from %d company career portals...", len(self.companies))
        jobs: List[Job] = []

        for comp in self.companies:
            if limit and len(jobs) >= limit:
                break

            url = self.API_BASE.format(company=comp.strip().lower())
            data = self._get_json(url, params={"limit": 20})

            if not data or not isinstance(data, dict):
                continue

            content = data.get("content", [])
            for item in content:
                if limit and len(jobs) >= limit:
                    break

                title = item.get("name", "").strip()
                if not any(k in title.lower() for k in ["engineer", "developer", "intern", "software", "analyst", "data", "cloud", "tech"]):
                    continue

                loc_data = item.get("location") or {}
                city = loc_data.get("city") or ""
                country = loc_data.get("country") or ""
                loc = f"{city}, {country}".strip(", ") or "Global / Remote"

                job_id = item.get("id") or item.get("uuid") or ""
                job_url = f"https://jobs.smartrecruiters.com/{comp}/{job_id}"

                job = Job.create(
                    title=title,
                    company=comp.title(),
                    url=job_url,
                    source="smartrecruiters",
                    location=loc,
                    is_remote="remote" in loc.lower() or "remote" in title.lower(),
                    description=f"Official career posting at {comp.title()}: {title}. Location: {loc}.",
                    tags=["Enterprise", "Official Career Page", "SmartRecruiters"],
                    posted_at=item.get("releasedDate"),
                )
                jobs.append(job)

        logger.info("[smartrecruiters] Successfully retrieved %d jobs.", len(jobs))
        return jobs
