"""Unstop public API student internship and job fetcher."""

import logging
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class UnstopFetcher(BaseJobFetcher):
    """Fetches student internships and fresher roles from Unstop API."""

    API_URL = "https://unstop.com/api/public/opportunity/search-result"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="unstop", timeout=timeout)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        })

    def fetch(self, limit: Optional[int] = 30) -> List[Job]:
        """Fetch student software internships from Unstop.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[unstop] Fetching student internships from Unstop...")
        queries = ["developer", "software", "web"]
        jobs: List[Job] = []
        seen_ids = set()

        for q in queries:
            if limit and len(jobs) >= limit:
                break

            params = {
                "opportunity": "internships",
                "keyword": q,
                "per_page": 20,
            }

            try:
                data = self._get_json(self.API_URL, params=params)
                if not data or not isinstance(data, dict):
                    continue

                items = data.get("data", {}).get("data", [])
                for item in items:
                    if limit and len(jobs) >= limit:
                        break

                    item_id = item.get("id")
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    title = item.get("title", "").strip()
                    org = item.get("organisation") or {}
                    company = org.get("name") if isinstance(org, dict) else str(org)
                    company = company.strip() or "Unstop Partner"

                    public_path = item.get("public_url", "")
                    url = f"https://unstop.com/{public_path.lstrip('/')}" if public_path else f"https://unstop.com/opportunity/{item_id}"

                    filters = item.get("filters") or []
                    tags = [f.get("name") for f in filters if isinstance(f, dict) and f.get("name")]
                    tags.extend(["Unstop", "Student", "Internship"])

                    job = Job.create(
                        title=title,
                        company=company,
                        url=url,
                        source="unstop",
                        location="India / Hybrid / Remote",
                        is_remote=True,
                        description=(
                            f"Student Opportunity at {company}: {title}. "
                            f"Targeted for undergraduate students and freshers. Sourced from Unstop."
                        ),
                        tags=list(set(tags)),
                        posted_at=str(item.get("start_date") or ""),
                    )
                    jobs.append(job)

            except Exception as e:
                logger.error("[unstop] Error querying Unstop for '%s': %s", q, e)

        logger.info("[unstop] Successfully retrieved %d jobs.", len(jobs))
        return jobs
