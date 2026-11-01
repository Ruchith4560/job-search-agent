"""Daily digest compilation engine for job discovery and application tracking."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List

from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job
from agent.tracker.dashboard import TrackerDashboard

logger = logging.getLogger(__name__)


class DailyDigestGenerator:
    """Compiles daily job search status summaries and action items into markdown and data reports."""

    def __init__(self, db: JobDatabase) -> None:
        """Initialize with JobDatabase."""
        self.db = db
        self.dashboard = TrackerDashboard(db)

    def generate_digest(self, candidate_name: str = "Candidate") -> Dict[str, Any]:
        """Synthesize daily status metrics, pending actions, and active applications.

        Args:
            candidate_name: Candidate's display name.

        Returns:
            Dictionary containing metrics, action items, and formatted markdown report.
        """
        metrics = self.dashboard.get_summary_metrics()

        # 1. Action Items (Shortlisted or Tailored requiring human review / prefill)
        shortlisted = self.db.get_jobs(status="shortlisted", limit=10)
        tailored = self.db.get_jobs(status="tailored", limit=10)
        applied = self.db.get_jobs(status="applied", limit=10)
        interviews = self.db.get_jobs(status="interview", limit=10)

        now_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

        md_lines = [
            f"# Daily Job Search Digest - {now_str}",
            f"**Candidate:** {candidate_name}",
            "",
            "## [PIPELINE] Pipeline Overview",
            f"- **Total Opportunities Tracked:** {metrics['total_jobs']}",
            f"- **In Progress (Shortlisted/Tailored):** {metrics['in_progress']}",
            f"- **Submitted Applications:** {metrics['applied']}",
            f"- **Active Interviews/Offers:** {metrics['active_conversations']}",
            "",
            "## [ACTIONS] Action Items (Next Steps)",
        ]

        if shortlisted:
            md_lines.append("### Ready for Tailoring:")
            for j in shortlisted:
                md_lines.append(f"- **{j.company}** - {j.title} (`{j.id[:8]}`) -> Run `python main.py tailor {j.id[:8]}`")
        else:
            md_lines.append("- *No un-tailored shortlisted jobs pending.*")

        if tailored:
            md_lines.append("\n### Tailored & Ready for Pre-fill / Review:")
            for j in tailored:
                md_lines.append(f"- **{j.company}** - {j.title} (`{j.id[:8]}`) -> Run `python main.py prefill {j.id[:8]}`")

        md_lines.append("\n## [APPLICATIONS] Active Submitted Applications")
        if applied:
            for j in applied:
                md_lines.append(f"- **{j.company}** - {j.title} (Source: {j.source}) [Portal Link]({j.url})")
        else:
            md_lines.append("- *No submitted applications recorded yet.*")

        if interviews:
            md_lines.append("\n## [INTERVIEWS] Active Interviews")
            for j in interviews:
                md_lines.append(f"- **{j.company}** - {j.title} ({j.location or 'Remote'})")

        md_report = "\n".join(md_lines) + "\n"

        return {
            "date": now_str,
            "metrics": metrics,
            "shortlisted_count": len(shortlisted),
            "tailored_count": len(tailored),
            "applied_count": len(applied),
            "interviews_count": len(interviews),
            "markdown": md_report,
        }

    def save_markdown_report(
        self,
        digest: Dict[str, Any],
        output_path: str = "data/daily_digest.md",
    ) -> Path:
        """Save formatted digest report to disk."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(digest["markdown"], encoding="utf-8")
        logger.info(f"Daily digest report saved to: {out}")
        return out
