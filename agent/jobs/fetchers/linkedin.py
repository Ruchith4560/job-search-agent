"""LinkedIn public guest API job fetcher for internships and software roles in India."""

import logging
import re
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class LinkedInFetcher(BaseJobFetcher):
    """Fetches software and engineering internships from LinkedIn's public guest search."""

    BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="linkedin", timeout=timeout)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch(self, limit: Optional[int] = 30) -> List[Job]:
        """Fetch software internship and entry-level positions in India from LinkedIn.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[linkedin] Fetching jobs from LinkedIn public search...")
        queries = [
            ("Software Engineer Intern", "India"),
            ("SDE Intern", "Hyderabad"),
            ("Full Stack Developer Intern", "India"),
        ]

        jobs: List[Job] = []
        seen_urls = set()

        for keyword, location in queries:
            if limit and len(jobs) >= limit:
                break

            params = {
                "keywords": keyword,
                "location": location,
                "f_TPR": "r604800",  # past week
                "position": 1,
                "pageNum": 0,
            }

            try:
                resp = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
                if resp.status_code != 200:
                    logger.warning("[linkedin] HTTP %d for query %s", resp.status_code, keyword)
                    continue

                html_content = resp.text

                # Parse card titles, companies, links, and locations
                titles = [t.strip() for t in re.findall(r'base-search-card__title[^>]*>([^<]+)<', html_content)]
                comps = [c.strip() for c in re.findall(r'base-search-card__subtitle[^>]*>.*?<a[^>]*>([^<]+)<', html_content, re.DOTALL)]
                raw_links = re.findall(r'base-card__full-link[^>]*href=[\'"]([^\'\"?]+)', html_content)
                locs = [l.strip() for l in re.findall(r'job-search-card__location[^>]*>([^<]+)<', html_content)]

                # If subtitle anchor not present, extract text directly
                if len(comps) < len(titles):
                    alt_comps = [c.strip() for c in re.findall(r'base-search-card__subtitle[^>]*>([^<]+)<', html_content)]
                    if len(alt_comps) >= len(titles):
                        comps = alt_comps

                count = min(len(titles), len(raw_links))
                for i in range(count):
                    if limit and len(jobs) >= limit:
                        break

                    url = raw_links[i]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title = titles[i]
                    company = comps[i] if i < len(comps) and comps[i] else "LinkedIn Employer"
                    loc = locs[i] if i < len(locs) and locs[i] else location

                    job = Job.create(
                        title=title,
                        company=company,
                        url=url,
                        source="linkedin",
                        location=loc,
                        is_remote="remote" in loc.lower() or "remote" in title.lower(),
                        description=f"Software opportunity at {company}: {title}. Location: {loc}. Sourced from LinkedIn Jobs.",
                        tags=["Software Engineering", "Internship", "LinkedIn"],
                    )
                    jobs.append(job)

            except Exception as e:
                logger.error("[linkedin] Error querying LinkedIn for '%s': %s", keyword, e)

        logger.info("[linkedin] Successfully retrieved %d jobs.", len(jobs))
        return jobs
