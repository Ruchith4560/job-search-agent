"""Hard filtering and anti-scam engine for student internship & entry-level job discovery."""

import logging
import re
from typing import List, Optional, Tuple
from agent.config import AppConfig
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)

SCAM_PATTERNS = [
    r"registration\s+fee",
    r"security\s+deposit",
    r"training\s+fee",
    r"placement\s+fee",
    r"pay\s+(?:us|a\s+fee|money)\s+to\s+apply",
    r"bank\s+account\s+details",
    r"credit\s+card\s+number",
    r"send\s+money",
    r"charges?\s+a\s+fee",
]

EXPERIENCE_DISQUALIFIERS = [
    r"\b([2-9]|\d{2,})\+?\s*(?:-\s*\d+\s*)?years?(?:\s+of\b[^,\.\n]{0,50})?\s+experience\b",
    r"\bminimum\s+([2-9]|\d{2,})\s+years\b",
    r"\bat\s+least\s+([2-9]|\d{2,})\s+years\b",
]

UNPAID_PATTERNS = [
    r"\bunpaid\b",
    r"\bno\s+stipend\b",
    r"\bwithout\s+stipend\b",
    r"\b0\s*(?:inr|rs|usd|\/|\s*per\s*month)\b",
]


def check_for_scam(job: Job) -> Optional[str]:
    """Identify scam signs like fee charging or bank detail requests."""
    combined = f"{job.title} {job.description}".lower()

    for pat in SCAM_PATTERNS:
        if re.search(pat, combined, re.I):
            return f"Flagged potential scam pattern: '{pat}'"

    # Check for recruiter email using free public domains
    free_email_match = re.search(
        r"(?:send\s+resume\s+to|contact\s+us\s+at|reach\s+out\s+at)\s+([a-zA-Z0-9_.+-]+@(gmail|yahoo|hotmail|outlook)\.com)",
        combined,
        re.I,
    )
    if free_email_match:
        return f"Suspicious recruiter contact using free webmail: {free_email_match.group(1)}"

    return None


def is_title_relevant(title: str, target_roles: List[str]) -> bool:
    """Check if the title matches target student roles (Intern, SDE, Graduate, Associate)."""
    if not target_roles:
        return True

    title_lower = title.lower()
    for role in target_roles:
        if role.lower() in title_lower:
            return True

    core_tech_terms = [
        "intern", "internship", "sde", "software", "engineer", "developer",
        "backend", "full stack", "fullstack", "frontend", "python", "java",
        "web", "ml", "ai", "cloud", "devops", "associate", "graduate", "trainee"
    ]
    words = set(re.findall(r"\w+", title_lower))
    return any(term in words or term in title_lower for term in core_tech_terms)


def is_experience_eligible(job: Job, max_years: int = 1) -> Tuple[bool, Optional[str]]:
    """Check if the job requires more experience than the student possesses."""
    desc_lower = job.description.lower()
    title_lower = job.title.lower()

    # If title says intern / trainee / associate, it's generally student friendly
    if any(k in title_lower for k in ("intern", "internship", "trainee", "student", "co-op", "graduate")):
        return True, None

    # Check for 2+ years disqualifiers
    for pat in EXPERIENCE_DISQUALIFIERS:
        m = re.search(pat, desc_lower, re.I)
        if m:
            years_str = m.group(1)
            try:
                if int(years_str) > max_years:
                    return False, f"Requires {years_str}+ years experience"
            except Exception:
                pass

    return True, None


def is_location_acceptable(job: Job, preferred_locations: List[str], allow_remote: bool) -> bool:
    """Check if the job matches remote preferences or target Indian tech hubs."""
    loc = (job.location or "").lower()

    if allow_remote and (job.is_remote or any(k in loc for k in ("remote", "anywhere", "worldwide", "work from home", "wfh"))):
        return True

    if not preferred_locations:
        return True

    for pref in preferred_locations:
        p_lower = pref.lower()
        if p_lower in loc:
            return True
        if p_lower in ("bengaluru", "bangalore") and ("bengaluru" in loc or "bangalore" in loc):
            return True

    return False


def is_unpaid_role(job: Job) -> bool:
    """Detect if the role is explicitly unpaid."""
    combined = f"{job.title} {job.description}".lower()
    return any(re.search(pat, combined, re.I) for pat in UNPAID_PATTERNS)


def apply_hard_filters(
    jobs: List[Job],
    config: AppConfig,
) -> Tuple[List[Job], List[Tuple[Job, str]]]:
    """Filter out non-matching jobs according to student preferences and guardrails."""
    accepted: List[Job] = []
    rejected: List[Tuple[Job, str]] = []

    excluded_companies = [c.lower() for c in config.preferences.exclude_companies]
    excluded_keywords = [k.lower() for k in config.jobs.exclude_keywords]
    target_roles = config.preferences.target_roles
    locations = config.preferences.locations
    allow_remote = config.jobs.allow_remote
    max_exp = config.preferences.deal_breakers.max_experience_years
    exclude_unpaid = config.preferences.deal_breakers.exclude_unpaid

    for job in jobs:
        # 1. Anti-scam check
        scam_reason = check_for_scam(job)
        if scam_reason:
            rejected.append((job, scam_reason))
            continue

        # 2. Excluded Company check
        c_lower = job.company.lower()
        if any(exc in c_lower for exc in excluded_companies):
            rejected.append((job, f"Excluded company '{job.company}'"))
            continue

        # 3. Excluded Seniority / Keywords check
        t_lower = job.title.lower()
        found_negative = None
        for neg in excluded_keywords:
            if re.search(r"\b" + re.escape(neg) + r"\b", t_lower):
                found_negative = neg
                break

        if found_negative:
            rejected.append((job, f"Negative title keyword '{found_negative}'"))
            continue

        # 4. Experience eligibility check (max 1 year for student)
        exp_eligible, exp_reason = is_experience_eligible(job, max_years=max_exp)
        if not exp_eligible:
            rejected.append((job, exp_reason or "Requires too much experience"))
            continue

        # 5. Unpaid role check
        if exclude_unpaid and is_unpaid_role(job):
            rejected.append((job, "Excluded unpaid role"))
            continue

        # 6. Role / Engineering relevance check
        if not is_title_relevant(job.title, target_roles):
            rejected.append((job, f"Title '{job.title}' does not match target roles"))
            continue

        # 7. Location & Remote check
        if not is_location_acceptable(job, locations, allow_remote):
            rejected.append((job, f"Location '{job.location}' outside target locations"))
            continue

        accepted.append(job)

    logger.info(
        f"Hard filtering: {len(accepted)} accepted, {len(rejected)} rejected out of {len(jobs)} jobs."
    )
    return accepted, rejected
