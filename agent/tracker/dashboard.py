"""Interactive pipeline status dashboard and analytics display."""

import logging
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.jobs.db import JobDatabase
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)
console = Console()

STATUS_COLORS = {
    "found": "blue",
    "shortlisted": "cyan",
    "tailored": "magenta",
    "prefilled": "yellow",
    "applied": "bold green",
    "interview": "bold magenta",
    "offer": "bold yellow",
    "rejected": "dim red",
}

PIPELINE_ORDER = [
    "found",
    "shortlisted",
    "tailored",
    "prefilled",
    "applied",
    "interview",
    "offer",
    "rejected",
]


def format_status_badge(status: str) -> str:
    """Return colorized status badge for Rich display."""
    color = STATUS_COLORS.get(status.lower(), "white")
    return f"[{color}]{status.upper()}[/{color}]"


class TrackerDashboard:
    """Renders interactive status dashboards, metrics, and application lifecycle tables."""

    def __init__(self, db: JobDatabase) -> None:
        """Initialize with JobDatabase instance."""
        self.db = db

    def get_summary_metrics(self) -> Dict[str, Any]:
        """Aggregate high-level pipeline counts and conversion metrics."""
        total = self.db.count_total()
        status_counts = self.db.count_by_status()
        source_counts = self.db.count_by_source()

        active_conversations = (
            status_counts.get("interview", 0) + status_counts.get("offer", 0)
        )
        in_progress = (
            status_counts.get("shortlisted", 0)
            + status_counts.get("tailored", 0)
            + status_counts.get("prefilled", 0)
        )
        applied = status_counts.get("applied", 0)

        return {
            "total_jobs": total,
            "status_counts": status_counts,
            "source_counts": source_counts,
            "in_progress": in_progress,
            "applied": applied,
            "active_conversations": active_conversations,
        }

    def render_dashboard(
        self,
        status_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
        limit: int = 25,
    ) -> None:
        """Render complete terminal dashboard including pipeline stats and job table."""
        metrics = self.get_summary_metrics()
        status_counts = metrics["status_counts"]
        total = metrics["total_jobs"]

        # 1. Pipeline Funnel Bar
        funnel_segments = []
        for s in PIPELINE_ORDER:
            cnt = status_counts.get(s, 0)
            color = STATUS_COLORS.get(s, "white")
            funnel_segments.append(f"[{color}]{s.title()}: {cnt}[/{color}]")

        funnel_text = " -> ".join(funnel_segments)

        overview_panel = Panel(
            f"[bold white]Total Opportunities Tracked:[/bold white] [bold cyan]{total}[/bold cyan]   |   "
            f"[bold white]In Progress:[/bold white] [bold yellow]{metrics['in_progress']}[/bold yellow]   |   "
            f"[bold white]Applied:[/bold white] [bold green]{metrics['applied']}[/bold green]   |   "
            f"[bold white]Interviews/Offers:[/bold white] [bold magenta]{metrics['active_conversations']}[/bold magenta]\n\n"
            f"[dim]Pipeline Flow:[/dim]  {funnel_text}",
            title="[bold green]AI Resume & Job Application Pipeline Dashboard[/bold green]",
            expand=False,
        )
        console.print("\n")
        console.print(overview_panel)

        # 2. Filtered Job Table
        jobs = self.db.get_jobs(status=status_filter, source=source_filter, limit=limit)

        table_title = f"Application Records (Showing {len(jobs)} of {total})"
        if status_filter:
            table_title += f" [Filter: status='{status_filter}']"
        if source_filter:
            table_title += f" [Filter: source='{source_filter}']"

        table = Table(title=table_title, expand=False)
        table.add_column("ID", style="dim cyan", no_wrap=True)
        table.add_column("Status", justify="center", no_wrap=True)
        table.add_column("Job Title", style="bold white")
        table.add_column("Company", style="cyan")
        table.add_column("Location", style="dim")
        table.add_column("Source", style="magenta")
        table.add_column("Discovered", style="dim white")

        for job in jobs:
            badge = format_status_badge(job.status)
            loc = job.location or ("Remote" if job.is_remote else "Unknown")
            if len(loc) > 22:
                loc = loc[:20] + ".."
            created_str = job.created_at[:10] if job.created_at else "N/A"
            table.add_row(
                job.id[:8],
                badge,
                job.title[:32],
                job.company[:22],
                loc,
                job.source,
                created_str,
            )

        console.print(table)
