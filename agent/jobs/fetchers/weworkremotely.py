"""We Work Remotely (WWR) programming RSS feed job fetcher."""

import logging
import xml.etree.ElementTree as ET
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class WeWorkRemotelyFetcher(BaseJobFetcher):
    """Fetches programming and software engineering jobs from We Work Remotely RSS."""

    RSS_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="weworkremotely", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch remote engineering jobs from We Work Remotely RSS.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[weworkremotely] Fetching jobs from We Work Remotely RSS...")
        try:
            resp = self.session.get(self.RSS_URL, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning("[weworkremotely] Non-200 status code: %d", resp.status_code)
                return []
            content = resp.text
        except Exception as e:
            logger.error("[weworkremotely] Error fetching RSS feed: %s", e)
            return []

        try:
            root = ET.fromstring(content)
        except Exception as e:
            logger.error("[weworkremotely] XML parsing error: %s", e)
            return []

        items = root.findall(".//item")
        jobs: List[Job] = []

        for item in items:
            if limit and len(jobs) >= limit:
                break

            raw_title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            if not raw_title or not url:
                continue

            # WWR title format is typically 'Company: Job Title'
            if ": " in raw_title:
                parts = raw_title.split(": ", 1)
                company = parts[0].strip()
                title = parts[1].strip()
            else:
                company = "WeWorkRemotely"
                title = raw_title

            raw_desc = item.findtext("description") or ""
            clean_desc = strip_html_tags(raw_desc)[:4000]
            pub_date = item.findtext("pubDate")

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="weworkremotely",
                location="Remote",
                is_remote=True,
                description=clean_desc,
                tags=["Engineering", "Programming", "Remote"],
                posted_at=pub_date,
            )
            jobs.append(job)

        logger.info("[weworkremotely] Successfully retrieved %d jobs.", len(jobs))
        return jobs
