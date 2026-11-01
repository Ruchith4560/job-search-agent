"""Hard filtering engine for newly fetched job listings."""

import logging
import re
from typing import List, Optional, Tuple
from agent.config import AppConfig
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


def is_title_relevant(title: str, target_roles: List[str]) -> bool:
    """Check if the job title matches any of the target roles or core engineering terms."""
    if not target_roles:
        return True

    title_lower = title.lower()
    # Check exact target roles first
    for role in target_roles:
        if role.lower() in title_lower:
            return True

    # Check common tech keywords if target roles were phrases
    core_tech_terms = [
        "software", "engineer", "developer", "backend", "full stack", "fullstack",
        "frontend", "python", "java", "web", "ml", "ai", "machine learning", "intern", "sde"
    ]
    words = set(re.findall(r"\w+", title_lower))
    return any(term in words or term in title_lower for term in core_tech_terms)


def is_location_acceptable(job: Job, preferred_locations: List[str], allow_remote: bool) -> bool:
    """Check if the job matches remote preferences or target cities/countries."""
    loc = (job.location or "").lower()

    if allow_remote and (job.is_remote or "remote" in loc or "anywhere" in loc or "worldwide" in loc):
        return True

    if not preferred_locations:
        return True

    for pref in preferred_locations:
        p_lower = pref.lower()
        if p_lower in loc:
            return True
        # Handle Bengaluru / Bangalore interchangeability
        if p_lower in ("bengaluru", "bangalore") and ("bengaluru" in loc or "bangalore" in loc):
            return True

    return False


def apply_hard_filters(
    jobs: List[Job],
    config: AppConfig,
) -> Tuple[List[Job], List[Tuple[Job, str]]]:
    """Filter out non-matching jobs according to preferences in config.yaml.

    Args:
        jobs: List of deduplicated Job instances.
        config: Application configuration with user preferences.

    Returns:
        Tuple of (accepted_jobs, rejected_jobs_with_reasons).
    """
    accepted: List[Job] = []
    rejected: List[Tuple[Job, str]] = []

    excluded_companies = [c.lower() for c in config.preferences.exclude_companies]
    excluded_keywords = [k.lower() for k in config.jobs.exclude_keywords]
    target_roles = config.preferences.target_roles
    locations = config.preferences.locations
    allow_remote = config.jobs.allow_remote

    for job in jobs:
        # 1. Excluded Company check
        c_lower = job.company.lower()
        if any(exc in c_lower for exc in excluded_companies):
            rejected.append((job, f"Excluded company '{job.company}'"))
            continue

        # 2. Excluded Keywords check (Title & Tags)
        t_lower = job.title.lower()
        found_negative = None
        for neg in excluded_keywords:
            # Word boundary search for negative keyword
            if re.search(r"\b" + re.escape(neg) + r"\b", t_lower):
                found_negative = neg
                break

        if found_negative:
            rejected.append((job, f"Negative title keyword '{found_negative}'"))
            continue

        # 3. Role / Engineering relevance check
        if not is_title_relevant(job.title, target_roles):
            rejected.append((job, f"Title '{job.title}' does not match target roles"))
            continue

        # 4. Location & Remote check
        if not is_location_acceptable(job, locations, allow_remote):
            rejected.append((job, f"Location '{job.location}' outside target locations"))
            continue

        accepted.append(job)

    logger.info(
        "Hard filters applied: %d accepted, %d filtered out.",
        len(accepted),
        len(rejected),
    )
    return accepted, rejected
