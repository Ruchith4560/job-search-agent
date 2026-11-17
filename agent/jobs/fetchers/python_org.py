"""Python Software Foundation official jobs RSS fetcher."""

import logging
import xml.etree.ElementTree as ET
from typing import List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class PythonOrgFetcher(BaseJobFetcher):
    """Fetches Python development and software engineering jobs from official python.org RSS."""

    RSS_URL = "https://www.python.org/jobs/feed/rss/"

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="python_org", timeout=timeout)

    def fetch(self, limit: Optional[int] = 50) -> List[Job]:
        """Fetch Python engineering jobs from python.org.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[python_org] Fetching jobs from python.org RSS feed...")
        try:
            resp = self.session.get(self.RSS_URL, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning("[python_org] Non-200 status code: %d", resp.status_code)
                return []
            content = resp.text
        except Exception as e:
            logger.error("[python_org] Error fetching RSS feed: %s", e)
            return []

        try:
            root = ET.fromstring(content)
        except Exception as e:
            logger.error("[python_org] XML parsing error: %s", e)
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

            # Title format often: 'Job Title, Company' or 'Job Title at Company'
            if ", " in raw_title:
                parts = raw_title.rsplit(", ", 1)
                title = parts[0].strip()
                company = parts[1].strip()
            elif " at " in raw_title:
                parts = raw_title.rsplit(" at ", 1)
                title = parts[0].strip()
                company = parts[1].strip()
            else:
                title = raw_title
                company = "Python Ecosystem"

            raw_desc = item.findtext("description") or ""
            clean_desc = strip_html_tags(raw_desc)[:4000]
            pub_date = item.findtext("pubDate")

            job = Job.create(
                title=title,
                company=company,
                url=url,
                source="python_org",
                location="Remote / Hybrid",
                is_remote=True,
                description=clean_desc,
                tags=["Python", "Software Engineering", "Backend"],
                posted_at=pub_date,
            )
            jobs.append(job)

        logger.info("[python_org] Successfully retrieved %d jobs.", len(jobs))
        return jobs
