"""Job deduplication logic based on company, title, and normalized URLs."""

import logging
import re
from typing import List, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from agent.jobs.schema import Job

logger = logging.getLogger(__name__)

# Common tracking parameters to strip for canonical URL matching
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "gh_src", "lever-source", "mode", "sid", "src"
}


def clean_url(url: str) -> str:
    """Normalize a job URL by stripping tracking parameters and standardizing trailing slashes.

    Args:
        url: Raw URL string.

    Returns:
        Cleaned, canonical URL string.
    """
    if not url:
        return ""

    parsed = urlparse(url)
    # Filter out tracking query parameters
    filtered_query = [
        (k, v) for k, v in parse_qsl(parsed.query)
        if k.lower() not in TRACKING_PARAMS
    ]
    cleaned = parsed._replace(
        query=urlencode(filtered_query),
        fragment="",
    )
    res = urlunparse(cleaned).rstrip("/")
    return res


def deduplicate_jobs(jobs: List[Job]) -> List[Job]:
    """De-duplicate a list of jobs by deterministic ID and normalized (company, title).

    Args:
        jobs: List of raw or fetched Job objects.

    Returns:
        List of unique Job objects.
    """
    unique_jobs: List[Job] = []
    seen_ids: Set[str] = set()
    seen_combos: Set[str] = set()

    for job in jobs:
        if job.id in seen_ids:
            continue

        # Also check simplified (company, title) combo
        norm_company = re.sub(r"[^a-z0-9]", "", job.company.lower())
        norm_title = re.sub(r"[^a-z0-9]", "", job.title.lower())
        combo = f"{norm_company}:{norm_title}"

        if combo in seen_combos:
            continue

        seen_ids.add(job.id)
        seen_combos.add(combo)
        unique_jobs.append(job)

    logger.info("Deduplicated %d raw jobs down to %d unique postings.", len(jobs), len(unique_jobs))
    return unique_jobs
