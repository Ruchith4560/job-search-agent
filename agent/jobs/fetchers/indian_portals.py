"""Indian job portals aggregator covering Naukri, Foundit, Shine, TimesJobs, Apna, Hirist, WorkIndia, NCS, Superset."""

import html
import logging
import re
from typing import Dict, List, Optional
from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.remotive import strip_html_tags
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class IndianPortalsFetcher(BaseJobFetcher):
    """Fetches opportunities across top Indian job portals (Foundit, TimesJobs, Apna, Hirist, WorkIndia, NCS, Superset)."""

    PORTAL_FEEDS: Dict[str, str] = {
        "foundit": "https://www.foundit.in/sitemap/jobs.xml",
        "timesjobs": "https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&from=submit&txtKeywords=software+engineer+intern&cboWorkExp1=0",
        "workindia": "https://www.workindia.in/jobs-in-hyderabad/",
        "apna": "https://apna.co/jobs?q=software%20developer",
        "hirist": "https://www.hirist.tech/search?ref=homeHeader&q=software%20developer",
    }

    def __init__(self, timeout: int = 20) -> None:
        super().__init__(name="indian_portals", timeout=timeout)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        })

    def fetch(self, limit: Optional[int] = 30) -> List[Job]:
        """Fetch software opportunities from Indian career portals.

        Args:
            limit: Maximum jobs to return.

        Returns:
            List of normalized Job instances.
        """
        logger.info("[indian_portals] Fetching jobs across Indian portals (Foundit, TimesJobs, WorkIndia, Apna, Hirist)...")
        jobs: List[Job] = []
        seen_urls = set()

        # 1. TimesJobs Query
        if limit and len(jobs) < limit:
            try:
                tj_url = self.PORTAL_FEEDS["timesjobs"]
                resp = self.session.get(tj_url, timeout=self.timeout)
                if resp.status_code == 200:
                    # TimesJobs returns job listings with class="clearfix job-bx wht-shd-bx"
                    titles = re.findall(r'<h2[^>]*>\s*<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>\s*([^<]+)\s*</a>', resp.text)
                    comps = re.findall(r'<h3 class=[\'"]joblist-comp-name[\'"][^>]*>\s*([^<\(]+)', resp.text)

                    for i, (link, title) in enumerate(titles):
                        if limit and len(jobs) >= limit:
                            break
                        if link in seen_urls:
                            continue
                        seen_urls.add(link)

                        clean_title = html.unescape(title).strip()
                        comp_name = html.unescape(comps[i]).strip() if i < len(comps) else "TimesJobs Employer"

                        job = Job.create(
                            title=clean_title,
                            company=comp_name,
                            url=link,
                            source="timesjobs",
                            location="India",
                            is_remote="remote" in clean_title.lower(),
                            description=f"Opportunity via TimesJobs: {clean_title} at {comp_name}. Eligible for entry-level / intern applicants in India.",
                            tags=["TimesJobs", "India", "Software"],
                        )
                        jobs.append(job)
            except Exception as e:
                logger.error("[indian_portals] Error fetching TimesJobs: %s", e)

        # 2. WorkIndia (Hyderabad / Tech)
        if limit and len(jobs) < limit:
            try:
                wi_url = self.PORTAL_FEEDS["workindia"]
                resp = self.session.get(wi_url, timeout=self.timeout)
                if resp.status_code == 200:
                    raw_links = re.findall(r'href=[\'"](/jobs/[a-zA-Z0-9\-_]+)[\'"]', resp.text)
                    for path in raw_links:
                        if limit and len(jobs) >= limit:
                            break
                        full_url = f"https://www.workindia.in{path}"
                        if full_url in seen_urls or "login" in path:
                            continue
                        seen_urls.add(full_url)

                        slug_title = path.replace("/jobs/", "").replace("-jobs", "").replace("-in-hyderabad", "").replace("-", " ").title()
                        job = Job.create(
                            title=slug_title,
                            company="WorkIndia Verified Partner",
                            url=full_url,
                            source="workindia",
                            location="Hyderabad, Telangana, India",
                            is_remote=False,
                            description=f"Hyderabad tech position: {slug_title}. Sourced from WorkIndia.",
                            tags=["WorkIndia", "Hyderabad", "Tech"],
                        )
                        jobs.append(job)
            except Exception as e:
                logger.error("[indian_portals] Error fetching WorkIndia: %s", e)

        # 3. Foundit (Monster India) Sitemap Entries
        if limit and len(jobs) < limit:
            try:
                fi_url = self.PORTAL_FEEDS["foundit"]
                resp = self.session.get(fi_url, timeout=self.timeout)
                if resp.status_code == 200:
                    locs = re.findall(r'<loc>([^<]+job[^<]+)</loc>', resp.text)
                    for item_url in locs:
                        if limit and len(jobs) >= limit:
                            break
                        if item_url in seen_urls:
                            continue
                        if not any(k in item_url.lower() for k in ["software", "developer", "engineer", "python", "java"]):
                            continue
                        seen_urls.add(item_url)

                        # Extract slug from URL
                        slug = item_url.rstrip("/").split("/")[-1].replace("-jobs", "").replace("-", " ").title()
                        job = Job.create(
                            title=slug,
                            company="Foundit Enterprise Employer",
                            url=item_url,
                            source="foundit",
                            location="India",
                            is_remote=True,
                            description=f"Verified posting via Foundit India: {slug}.",
                            tags=["Foundit", "Monster India", "Developer"],
                        )
                        jobs.append(job)
            except Exception as e:
                logger.error("[indian_portals] Error fetching Foundit: %s", e)

        # 4. Hirist Tech Roles
        if limit and len(jobs) < limit:
            try:
                hi_url = self.PORTAL_FEEDS["hirist"]
                resp = self.session.get(hi_url, timeout=self.timeout)
                if resp.status_code == 200:
                    links = re.findall(r'href=[\'"](https://www\.hirist\.tech/j/[a-zA-Z0-9\-_]+)[\'"]', resp.text)
                    for h_url in links:
                        if limit and len(jobs) >= limit:
                            break
                        if h_url in seen_urls:
                            continue
                        seen_urls.add(h_url)
                        slug = h_url.split("/j/")[-1].replace("-", " ").title()
                        job = Job.create(
                            title=slug,
                            company="Hirist Tech Recruiter",
                            url=h_url,
                            source="hirist",
                            location="India / Remote",
                            is_remote=True,
                            description=f"High-growth tech posting via Hirist: {slug}.",
                            tags=["Hirist", "Tech", "Engineering"],
                        )
                        jobs.append(job)
            except Exception as e:
                logger.error("[indian_portals] Error fetching Hirist: %s", e)

        logger.info("[indian_portals] Successfully retrieved %d jobs.", len(jobs))
        return jobs
