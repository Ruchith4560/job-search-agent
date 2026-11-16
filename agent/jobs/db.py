"""SQLite database manager for persisting and tracking discovered jobs."""

from datetime import datetime, timezone
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
        """Create the jobs schema, add new columns if migrating, and build indexes."""
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
                    job_type TEXT DEFAULT 'internship',
                    duration TEXT,
                    stipend_or_salary TEXT,
                    match_score INTEGER,
                    ats_score INTEGER,
                    is_top_pick INTEGER DEFAULT 0,
                    emailed_at TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Run safe migrations for any existing databases
            columns_to_add = [
                ("job_type", "TEXT DEFAULT 'internship'"),
                ("duration", "TEXT"),
                ("stipend_or_salary", "TEXT"),
                ("match_score", "INTEGER"),
                ("ats_score", "INTEGER"),
                ("is_top_pick", "INTEGER DEFAULT 0"),
                ("emailed_at", "TEXT"),
                ("applied_at", "TEXT"),
            ]
            for col_name, col_def in columns_to_add:
                try:
                    cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs (company)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (match_score)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_emailed ON jobs (emailed_at)")
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
            cursor.execute("SELECT status, emailed_at FROM jobs WHERE id = ?", (job.id,))
            existing = cursor.fetchone()

            tags_json = json.dumps(job.tags)

            if existing is None:
                cursor.execute("""
                    INSERT INTO jobs (
                        id, title, company, url, source, location, is_remote,
                        description, tags, salary_min, salary_max, salary_currency,
                        posted_at, status, job_type, duration, stipend_or_salary,
                        match_score, ats_score, is_top_pick, emailed_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.title, job.company, job.url, job.source,
                    job.location, 1 if job.is_remote else 0, job.description,
                    tags_json, job.salary_min, job.salary_max, job.salary_currency,
                    job.posted_at, job.status, job.job_type, job.duration, job.stipend_or_salary,
                    job.match_score, job.ats_score, 1 if job.is_top_pick else 0,
                    job.emailed_at, job.created_at,
                ))
                conn.commit()
                return True
            else:
                cursor.execute("""
                    UPDATE jobs SET
                        title = ?, company = ?, url = ?, source = ?,
                        location = ?, is_remote = ?, description = ?,
                        tags = ?, salary_min = ?, salary_max = ?,
                        salary_currency = ?, posted_at = ?, job_type = ?,
                        duration = COALESCE(?, duration),
                        stipend_or_salary = COALESCE(?, stipend_or_salary)
                    WHERE id = ?
                """, (
                    job.title, job.company, job.url, job.source,
                    job.location, 1 if job.is_remote else 0, job.description,
                    tags_json, job.salary_min, job.salary_max,
                    job.salary_currency, job.posted_at, job.job_type,
                    job.duration, job.stipend_or_salary, job.id,
                ))
                conn.commit()
                return False

    def upsert_jobs(self, jobs: List[Job]) -> Tuple[int, int]:
        """Batch upsert a list of jobs."""
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
        min_score: Optional[int] = None,
        min_match_score: Optional[int] = None,
        unemailed_only: bool = False,
    ) -> List[Job]:
        """Retrieve jobs matching filters, ordered by match_score desc, creation date desc."""
        effective_min_score = min_match_score if min_match_score is not None else min_score
        query = "SELECT * FROM jobs WHERE 1=1"
        params: List[object] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)
        if effective_min_score is not None:
            query += " AND match_score >= ?"
            params.append(effective_min_score)
        if unemailed_only:
            query += " AND emailed_at IS NULL"

        query += " ORDER BY COALESCE(match_score, 0) DESC, created_at DESC"
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
            if new_status.lower() == "applied":
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    "UPDATE jobs SET status = ?, applied_at = COALESCE(applied_at, ?) WHERE id = ?",
                    (new_status, now_iso, job_id),
                )
            else:
                cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
            conn.commit()
            return cursor.rowcount > 0

    def update_scores(
        self,
        job_id: str,
        match_score: Optional[float] = None,
        ats_score: Optional[float] = None,
        is_top_pick: Optional[bool] = None,
    ) -> bool:
        """Update match and ATS scores for a job."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs SET
                    match_score = COALESCE(?, match_score),
                    ats_score = COALESCE(?, ats_score),
                    is_top_pick = CASE WHEN ? IS NOT NULL THEN ? ELSE is_top_pick END
                WHERE id = ?
            """, (
                int(round(match_score)) if match_score is not None else None,
                int(round(ats_score)) if ats_score is not None else None,
                1 if is_top_pick is not None else None,
                1 if is_top_pick else 0,
                job_id,
            ))
            conn.commit()
            return cursor.rowcount > 0

    def mark_as_emailed(self, job_ids: List[str]) -> int:
        """Mark jobs as emailed with timestamp and status to ensure they are never emailed twice."""
        if not job_ids:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in job_ids)
            cursor.execute(f"""
                UPDATE jobs SET
                    emailed_at = ?,
                    status = CASE WHEN status = 'found' OR status = 'shortlisted' THEN 'emailed' ELSE status END
                WHERE id IN ({placeholders})
            """, [now_iso] + job_ids)
            conn.commit()
            return cursor.rowcount

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

        keys = row.keys()
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
            job_type=row["job_type"] if "job_type" in keys and row["job_type"] else "internship",
            duration=row["duration"] if "duration" in keys else None,
            stipend_or_salary=row["stipend_or_salary"] if "stipend_or_salary" in keys else None,
            match_score=row["match_score"] if "match_score" in keys else None,
            ats_score=row["ats_score"] if "ats_score" in keys else None,
            is_top_pick=bool(row["is_top_pick"]) if "is_top_pick" in keys and row["is_top_pick"] else False,
            emailed_at=row["emailed_at"] if "emailed_at" in keys else None,
            applied_at=row["applied_at"] if "applied_at" in keys else None,
            created_at=row["created_at"],
        )
