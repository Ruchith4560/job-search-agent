"""Freshersworld job fetcher for entry-level and fresher engineering roles in India."""

import logging
import re
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class FreshersworldFetcher(BaseJobFetcher):
    """Fetches fresher B.Tech / entry-level developer jobs from Freshersworld."""

    SEARCH_URLS = [
        "https://www.freshersworld.com/jobs/jobsearch/software-developer-jobs-for-be-btech",
        "https://www.freshersworld.com/jobs/jobsearch/software-developer-jobs-in-hyderabad",
    ]

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="freshersworld", timeout=timeout)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        })

    def fetch(self, limit: Optional[int] = 30) -> List[Job]:
        """Fetch fresher engineering jobs from Freshersworld.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[freshersworld] Fetching fresher jobs from Freshersworld...")
        jobs: List[Job] = []
        seen_urls = set()

        for s_url in self.SEARCH_URLS:
            if limit and len(jobs) >= limit:
                break

            try:
                resp = self.session.get(s_url, timeout=self.timeout)
                if resp.status_code != 200:
                    continue

                html_text = resp.text
                links = re.findall(r'href=[\'"](https://www\.freshersworld\.com/jobs/([a-zA-Z0-9\-_]+-\d+))[\'"]', html_text)

                for full_url, slug in links:
                    if limit and len(jobs) >= limit:
                        break

                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    # Slug parsing: e.g. 'software-developer-in-hyderabad-for-zoetis-india-capability-center-2953955'
                    slug_no_id = re.sub(r'-\d+$', '', slug)

                    company = "Freshersworld Partner"
                    loc = "Hyderabad, India"
                    role = "Software Developer"

                    if "-for-" in slug_no_id:
                        left, comp_part = slug_no_id.split("-for-", 1)
                        company = comp_part.replace("-", " ").title().strip()
                        if "-in-" in left:
                            role_part, loc_part = left.split("-in-", 1)
                            role = role_part.replace("-", " ").title().strip()
                            loc = loc_part.replace("-", " ").title().strip() + ", India"
                        else:
                            role = left.replace("-", " ").title().strip()
                    elif "-in-" in slug_no_id:
                        role_part, loc_part = slug_no_id.split("-in-", 1)
                        role = role_part.replace("-", " ").title().strip()
                        loc = loc_part.replace("-", " ").title().strip() + ", India"
                    else:
                        role = slug_no_id.replace("-", " ").title().strip()

                    job = Job.create(
                        title=role,
                        company=company,
                        url=full_url,
                        source="freshersworld",
                        location=loc,
                        is_remote="remote" in loc.lower() or "remote" in role.lower(),
                        description=f"Fresher engineering role at {company}: {role}. Location: {loc}. Suitable for B.Tech graduates/students.",
                        tags=["Fresher", "B.Tech", "Entry Level", "Freshersworld"],
                    )
                    jobs.append(job)

            except Exception as e:
                logger.error("[freshersworld] Error querying %s: %s", s_url, e)

        logger.info("[freshersworld] Successfully retrieved %d jobs.", len(jobs))
        return jobs
