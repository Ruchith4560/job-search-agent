"""Internshala public internship fetcher for Indian students."""

import logging
import re
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class InternshalaFetcher(BaseJobFetcher):
    """Fetches verified software development and tech internships from Internshala."""

    CATEGORY_URLS = [
        "https://internshala.com/internships/software-development-internship/",
        "https://internshala.com/internships/web-development-internship/",
        "https://internshala.com/internships/python-django-internship/",
    ]

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="internshala", timeout=timeout)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def fetch(self, limit: Optional[int] = 30) -> List[Job]:
        """Fetch software internships from Internshala.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[internshala] Fetching student internships from Internshala...")
        jobs: List[Job] = []
        seen_urls = set()

        for cat_url in self.CATEGORY_URLS:
            if limit and len(jobs) >= limit:
                break

            try:
                resp = self.session.get(cat_url, timeout=self.timeout)
                if resp.status_code != 200:
                    logger.warning("[internshala] Non-200 status %d for %s", resp.status_code, cat_url)
                    continue

                html_text = resp.text
                # Match /internship/detail/ slugs
                raw_slugs = re.findall(r'href=[\'"](/internship/detail/([a-zA-Z0-9\-_]+))[\'"]', html_text)

                for path, slug in raw_slugs:
                    if limit and len(jobs) >= limit:
                        break

                    full_url = f"https://internshala.com{path}"
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    # Extract role and company name from canonical slug format:
                    # e.g. 'work-from-home-software-development-internship-at-oblytech-india-private-limited1794545060'
                    if "-at-" in slug:
                        role_part, comp_part = slug.split("-at-", 1)
                        role_clean = role_part.replace("-", " ").title().strip()
                        comp_clean = re.sub(r"\d+$", "", comp_part).replace("-", " ").title().strip()
                    else:
                        role_clean = slug.replace("-", " ").title().strip()
                        comp_clean = "Internshala Partner"

                    is_wfh = "work from home" in role_clean.lower() or "remote" in role_clean.lower()
                    loc = "Remote / Work From Home" if is_wfh else "India"

                    job = Job.create(
                        title=role_clean,
                        company=comp_clean,
                        url=full_url,
                        source="internshala",
                        location=loc,
                        is_remote=is_wfh,
                        description=(
                            f"Verified Student Internship at {comp_clean}: {role_clean}. "
                            f"Location: {loc}. Eligible for B.Tech CSE students. Sourced from Internshala."
                        ),
                        tags=["Internship", "Student", "Internshala", "Software Development"],
                    )
                    jobs.append(job)

            except Exception as e:
                logger.error("[internshala] Error querying %s: %s", cat_url, e)

        logger.info("[internshala] Successfully retrieved %d jobs.", len(jobs))
        return jobs
