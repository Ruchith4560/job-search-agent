"""Export utilities for tracker records to CSV and JSON formats."""

import csv
import json
import logging
from pathlib import Path
from typing import List, Optional

from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


def export_jobs_to_csv(
    db: JobDatabase,
    output_path: str = "data/tracker_export.csv",
    status_filter: Optional[str] = None,
) -> Path:
    """Export stored job records to a clean CSV file.

    Args:
        db: Source JobDatabase instance.
        output_path: Target CSV file path.
        status_filter: Optional status filter.

    Returns:
        Path to written CSV file.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    jobs: List[Job] = db.get_jobs(status=status_filter)

    headers = [
        "id",
        "title",
        "company",
        "status",
        "location",
        "is_remote",
        "source",
        "url",
        "tags",
        "salary_min",
        "salary_max",
        "salary_currency",
        "posted_at",
        "created_at",
    ]

    with open(out, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for j in jobs:
            writer.writerow([
                j.id,
                j.title,
                j.company,
                j.status,
                j.location or "",
                1 if j.is_remote else 0,
                j.source,
                j.url,
                "; ".join(j.tags),
                j.salary_min or "",
                j.salary_max or "",
                j.salary_currency or "",
                j.posted_at or "",
                j.created_at,
            ])

    logger.info(f"Exported {len(jobs)} jobs to CSV: {out}")
    return out


def export_jobs_to_json(
    db: JobDatabase,
    output_path: str = "data/tracker_export.json",
    status_filter: Optional[str] = None,
) -> Path:
    """Export stored job records to formatted JSON.

    Args:
        db: Source JobDatabase instance.
        output_path: Target JSON file path.
        status_filter: Optional status filter.

    Returns:
        Path to written JSON file.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    jobs: List[Job] = db.get_jobs(status=status_filter)
    data = [j.model_dump() for j in jobs]

    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info(f"Exported {len(jobs)} jobs to JSON: {out}")
    return out
