"""Mandatory Human-in-the-Loop Approval Gate for job application submission."""

from enum import Enum
import logging
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()


class ApprovalDecision(str, Enum):
    """User decision outcome at the terminal approval gate."""
    APPROVE = "approve"  # Proceed with automated submission
    MANUAL = "manual"    # Open/keep browser open for manual review and submission by human
    CANCEL = "cancel"    # Abort without submitting (save prefilled state)


class FieldDiff(BaseModel):
    """Record of a pre-filled or answered form field."""
    field_name: str
    value: str
    field_type: str = "text"  # text, file, textarea, select


class PreFillSummary(BaseModel):
    """Comprehensive snapshot of pre-filled form fields before submission."""
    job_id: str
    company: str
    title: str
    application_url: str
    resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None
    filled_fields: List[FieldDiff] = Field(default_factory=list)
    custom_answers: List[FieldDiff] = Field(default_factory=list)
    sensitive_skipped: List[str] = Field(default_factory=list)
    unanswered_questions: List[Dict[str, str]] = Field(default_factory=list)
    screenshot_path: Optional[str] = None


class ApprovalGate:
    """Enforces Hard Rule 3: Zero automatic blind submissions.

    Presents a complete diff of the application form and requires explicit
    terminal confirmation before any submission action is taken.
    """

    def __init__(self, interactive: bool = True) -> None:
        """Initialize ApprovalGate.

        Args:
            interactive: If True, blocks on terminal input. If False, defaults to manual review.
        """
        self.interactive = interactive

    def request_approval(
        self,
        summary: PreFillSummary,
        auto_decision: Optional[ApprovalDecision] = None,
    ) -> ApprovalDecision:
        """Display full pre-fill review and wait for user terminal approval.

        Args:
            summary: PreFillSummary containing all prefilled field details.
            auto_decision: Optional programmatic decision (for testing/CI only).

        Returns:
            ApprovalDecision chosen by the user.
        """
        self.render_review(summary)

        if auto_decision is not None:
            logger.info(f"ApprovalGate programmatic decision: {auto_decision.value}")
            return auto_decision

        if not self.interactive:
            console.print(
                "[yellow]Non-interactive environment detected. Defaulting to 'manual' review mode.[/yellow]"
            )
            return ApprovalDecision.MANUAL

        console.print(
            "\n[bold yellow]-----------------------------------------------------------------[/bold yellow]"
        )
        console.print(
            "[bold white]HUMAN-IN-THE-LOOP APPROVAL REQUIRED (Hard Rule 3):[/bold white]\n"
            "  [bold green][A][/bold green] - Approve and submit application automatically\n"
            "  [bold cyan][M][/bold cyan] - Keep browser open to review and submit manually\n"
            "  [bold red][C][/bold red] - Cancel application and discard pre-fill\n"
        )

        while True:
            try:
                choice = input("Enter decision [A / M / C]: ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Approval cancelled by user interruption.[/yellow]")
                return ApprovalDecision.CANCEL

            if choice in ("A", "APPROVE"):
                console.print("[bold green]User approved submission. Finalizing application...[/bold green]")
                return ApprovalDecision.APPROVE
            elif choice in ("M", "MANUAL"):
                console.print("[bold cyan]Leaving browser active for user manual review and completion.[/bold cyan]")
                return ApprovalDecision.MANUAL
            elif choice in ("C", "CANCEL"):
                console.print("[bold red]Submission cancelled by user. No action taken.[/bold red]")
                return ApprovalDecision.CANCEL
            else:
                console.print("[yellow]Invalid option. Please enter 'A' (Approve), 'M' (Manual), or 'C' (Cancel).[/yellow]")

    def render_review(self, summary: PreFillSummary) -> None:
        """Render a rich, clear terminal review table and panels."""
        console.print("\n")
        title_panel = Panel(
            f"[bold cyan]{summary.company}[/bold cyan] - [bold white]{summary.title}[/bold white]\n"
            f"[dim]URL:[/dim] {summary.application_url}",
            title="[bold green]Application Pre-Fill Review[/bold green]",
            subtitle="[yellow]Hard Rule 3: Zero Blind Submissions[/yellow]",
            expand=False,
        )
        console.print(title_panel)

        # 1. Standard Fields Table
        if summary.filled_fields:
            fields_table = Table(title="Pre-filled Form Fields", expand=False)
            fields_table.add_column("Field", style="cyan", no_wrap=True)
            fields_table.add_column("Type", style="dim magenta")
            fields_table.add_column("Value Filled", style="white")

            for f in summary.filled_fields:
                val_display = f.value
                if len(val_display) > 75:
                    val_display = val_display[:72] + "..."
                fields_table.add_row(f.field_name, f.field_type, val_display)

            console.print(fields_table)

        # 2. Custom Questions Table
        if summary.custom_answers:
            custom_table = Table(title="Answered Custom Screening Questions", expand=False)
            custom_table.add_column("Question / Prompt", style="yellow")
            custom_table.add_column("Synthesized Answer (Grounded)", style="white")

            for ca in summary.custom_answers:
                custom_table.add_row(ca.field_name, ca.value)

            console.print(custom_table)

        # 3. Sensitive Questions Skipped
        if summary.sensitive_skipped:
            sensitive_table = Table(
                title="[bold yellow]Compliance / Sensitive Fields Skipped for Human Attention[/bold yellow]",
                expand=False,
            )
            sensitive_table.add_column("Field Name / Prompt", style="bold yellow")
            sensitive_table.add_column("Reason Skipped", style="dim")

            for sk in summary.sensitive_skipped:
                sensitive_table.add_row(
                    sk, "Left blank: requires explicit personal authorization / compliance decision"
                )

            console.print(sensitive_table)

        # 4. Attachments & Screenshot
        attach_lines = []
        if summary.resume_path:
            attach_lines.append(f"[bold cyan]Attached Resume:[/bold cyan] {summary.resume_path}")
        if summary.cover_letter_path:
            attach_lines.append(f"[bold cyan]Attached Cover Letter:[/bold cyan] {summary.cover_letter_path}")
        if summary.screenshot_path:
            attach_lines.append(f"[bold green]Form Screenshot:[/bold green] {summary.screenshot_path}")

        if attach_lines:
            console.print(
                Panel(
                    "\n".join(attach_lines),
                    title="[bold blue]Documents & Verification Snapshot[/bold blue]",
                    expand=False,
                )
            )
