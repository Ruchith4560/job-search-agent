"""SQLite database manager for persisting and tracking discovered jobs."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional, Tuple

from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class JobDatabase:
    """Manages SQLite storage and lifecycle states for job opportunities."""

    def __init__(self, db_path: str = "data/tracker.db") -> None:
        """Initialize database manager and ensure tables are created.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and return a database connection with Row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the jobs schema and performance indexes if not already present."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    location TEXT,
                    is_remote INTEGER NOT NULL DEFAULT 0,
                    description TEXT,
                    tags TEXT,
                    salary_min REAL,
                    salary_max REAL,
                    salary_currency TEXT,
                    posted_at TEXT,
                    status TEXT NOT NULL DEFAULT 'found',
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs (company)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source)")
            conn.commit()

    def upsert_job(self, job: Job) -> bool:
        """Insert or update a job record, preserving user status (e.g. applied/shortlisted).

        Args:
            job: Job model instance.

        Returns:
            True if inserted as a new record, False if updated.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs WHERE id = ?", (job.id,))
            existing = cursor.fetchone()

            tags_json = json.dumps(job.tags)

            if existing is None:
                cursor.execute("""
                    INSERT INTO jobs (
                        id, title, company, url, source, location, is_remote,
                        description, tags, salary_min, salary_max, salary_currency,
                        posted_at, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.title, job.company, job.url, job.source,
                    job.location, 1 if job.is_remote else 0, job.description,
                    tags_json, job.salary_min, job.salary_max, job.salary_currency,
                    job.posted_at, job.status, job.created_at,
                ))
                conn.commit()
                return True
            else:
                # Update job fields while preserving existing status
                cursor.execute("""
                    UPDATE jobs SET
                        title = ?, company = ?, url = ?, source = ?,
                        location = ?, is_remote = ?, description = ?,
                        tags = ?, salary_min = ?, salary_max = ?,
                        salary_currency = ?, posted_at = ?
                    WHERE id = ?
                """, (
                    job.title, job.company, job.url, job.source,
                    job.location, 1 if job.is_remote else 0, job.description,
                    tags_json, job.salary_min, job.salary_max,
                    job.salary_currency, job.posted_at, job.id,
                ))
                conn.commit()
                return False

    def upsert_jobs(self, jobs: List[Job]) -> Tuple[int, int]:
        """Batch upsert a list of jobs.

        Args:
            jobs: List of Job instances.

        Returns:
            Tuple of (newly_inserted_count, updated_count).
        """
        inserted = 0
        updated = 0
        for job in jobs:
            is_new = self.upsert_job(job)
            if is_new:
                inserted += 1
            else:
                updated += 1
        return inserted, updated

    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        """Retrieve a single job by its unique ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def get_jobs(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        source: Optional[str] = None,
    ) -> List[Job]:
        """Retrieve jobs matching filters, ordered by creation date desc."""
        query = "SELECT * FROM jobs WHERE 1=1"
        params: List[object] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)

        query += " ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_job(r) for r in rows]

    def update_status(self, job_id: str, new_status: str) -> bool:
        """Update the workflow status for a specific job."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
            conn.commit()
            return cursor.rowcount > 0

    def count_by_status(self) -> Dict[str, int]:
        """Count jobs grouped by status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status")
            return {row["status"]: row["count"] for row in cursor.fetchall()}

    def count_by_source(self) -> Dict[str, int]:
        """Count jobs grouped by discovery source."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT source, COUNT(*) as count FROM jobs GROUP BY source")
            return {row["source"]: row["count"] for row in cursor.fetchall()}

    def count_total(self) -> int:
        """Return total number of jobs stored."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs")
            return cursor.fetchone()[0]

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert a SQLite Row into a typed Job instance."""
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except Exception:
                tags = []

        return Job(
            id=row["id"],
            title=row["title"],
            company=row["company"],
            url=row["url"],
            source=row["source"],
            location=row["location"],
            is_remote=bool(row["is_remote"]),
            description=row["description"] or "",
            tags=tags,
            salary_min=row["salary_min"],
            salary_max=row["salary_max"],
            salary_currency=row["salary_currency"],
            posted_at=row["posted_at"],
            status=row["status"],
            created_at=row["created_at"],
        )
