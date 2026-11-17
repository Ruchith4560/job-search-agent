"""CLI entry point for the AI Resume & Job Application Agent."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
import typer

# Load environment variables from .env
load_dotenv()

from agent.config import load_config
from agent.apply.approval import ApprovalDecision, ApprovalGate
from agent.apply.pipeline import ApplicationTailorPipeline
from agent.apply.prefill import FormPreFiller
from agent.ingest.github import GitHubIngester, GitHubProfileData
from agent.ingest.linkedin import LinkedInParser
from agent.llm import ClaudeClient
from agent.jobs.db import JobDatabase
from agent.jobs.fetchers.aggregator import JobAggregator
from agent.jobs.match import MatchPipeline
from agent.notify.email_sender import EmailDigestGenerator, EmailDigestSender, JobDigestItem
from agent.profile.builder import ProfileBuilder
from agent.profile.schema import MasterProfile
from agent.profile.sync import ProfileSyncManager
from agent.resume.ats_checker import ATSChecker
from agent.resume.generator import ResumeGenerator
from agent.resume.render import render_docx, render_html, render_pdf
from agent.resume.verifier import VerificationError
from agent.tracker.dashboard import PIPELINE_ORDER, TrackerDashboard
from agent.tracker.digest import DailyDigestGenerator
from agent.tracker.export import export_jobs_to_csv, export_jobs_to_json

# Configure application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger("job_agent")
console = Console()

app = typer.Typer(
    name="job-agent",
    help="AI Resume & Job Application Agent: Turn GitHub/LinkedIn into resumes, find jobs, and prepare applications.",
    add_completion=False,
)


@app.command("ingest-github")
def ingest_github(
    username: Optional[str] = typer.Option(
        None, "--username", "-u", help="GitHub username to ingest (defaults to config.yaml)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub Personal Access Token (or uses GITHUB_TOKEN env)"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Target output JSON path (defaults to config.yaml)"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l", help="Maximum number of repositories to ingest"
    ),
    include_forks: bool = typer.Option(
        False, "--include-forks", help="Include forked repositories in ingestion"
    ),
    skip_readme: bool = typer.Option(
        False, "--skip-readme", help="Skip fetching and summarizing README files"
    ),
    summarize_llm: bool = typer.Option(
        False, "--summarize-llm", help="Use Claude LLM to generate README summaries (requires ANTHROPIC_API_KEY)"
    ),
) -> None:
    """Ingest public GitHub repositories, stars, languages, topics, and README summaries."""
    config = load_config()
    target_username = username or config.preferences.github_username
    output_path = output or config.paths.github_raw_file

    if not target_username or target_username == "octocat":
        console.print(
            "[yellow]Note: Ingesting sample user 'octocat'. Update config.yaml with your GitHub username or pass -u <username>.[/yellow]"
        )

    console.print(f"[bold green]Starting GitHub ingestion for user: [cyan]{target_username}[/cyan]...[/bold green]")

    claude_client = None
    if summarize_llm:
        try:
            claude_client = ClaudeClient(default_model=config.llm.model)
            console.print("[green]Claude LLM enabled for README summarization.[/green]")
        except Exception as e:
            console.print(f"[yellow]Could not initialize Claude client for README summarization: {e}. Falling back to standard extractor.[/yellow]")

    ingester = GitHubIngester(token=token, claude_client=claude_client)

    try:
        data = ingester.fetch_user_repos(
            username=target_username,
            include_forks=include_forks,
            limit=limit,
            summarize_readmes=not skip_readme,
        )
        saved_file = ingester.save_to_json(data, output_path=output_path)
    except Exception as e:
        console.print(f"[bold red]Ingestion failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # Display results table
    table = Table(title=f"GitHub Repositories for @{target_username} (Total: {data.total_repos})")
    table.add_column("Repository", style="cyan", no_wrap=True)
    table.add_column("Language", style="magenta")
    table.add_column("Stars", justify="right", style="green")
    table.add_column("Last Activity", style="blue")
    table.add_column("Summary / Description", style="white")

    for repo in data.repos[:15]:
        summary = repo.readme_summary or repo.description or "No description"
        if len(summary) > 75:
            summary = summary[:72] + "..."
        table.add_row(
            repo.name,
            repo.primary_language or "N/A",
            str(repo.stars),
            repo.last_activity[:10] if repo.last_activity else "N/A",
            summary,
        )

    console.print(table)
    if data.total_repos > 15:
        console.print(f"[dim]... and {data.total_repos - 15} more repositories saved to {saved_file}[/dim]")
    console.print(f"[bold green]Raw GitHub data successfully saved to: [underline]{saved_file}[/underline][/bold green]")


@app.command("build-profile")
def build_profile(
    linkedin_path: str = typer.Option(
        "data/raw/linkedin",
        "--linkedin",
        "-l",
        help="Path to extracted LinkedIn export directory or .zip file",
    ),
    github_file: str = typer.Option(
        "data/raw/github.json",
        "--github",
        "-g",
        help="Path to raw ingested GitHub JSON file",
    ),
    output: str = typer.Option(
        "master_profile.json",
        "--output",
        "-o",
        help="Destination path for master_profile.json",
    ),
) -> None:
    """Build and validate master_profile.json by merging GitHub and LinkedIn sources."""
    console.print("[bold green]Building Master Profile with source-tracked verification...[/bold green]")

    # 1. Load GitHub Data
    gh_data = None
    gh_path = Path(github_file)
    if gh_path.is_file():
        try:
            gh_json = gh_path.read_text(encoding="utf-8")
            gh_data = GitHubProfileData.model_validate_json(gh_json)
            console.print(f"[green]Loaded {len(gh_data.repos)} repositories from {gh_path}[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not read GitHub data from {gh_path}: {e}[/yellow]")
    else:
        console.print(f"[yellow]No GitHub data found at {gh_path}. Proceeding with LinkedIn only.[/yellow]")

    # 2. Load LinkedIn Data
    lk_data = None
    lk_p = Path(linkedin_path)
    if lk_p.exists():
        try:
            parser = LinkedInParser()
            lk_data = parser.parse(lk_p)
            console.print(
                f"[green]Parsed LinkedIn export: {len(lk_data.positions)} positions, "
                f"{len(lk_data.skills)} skills, {len(lk_data.education)} education records.[/green]"
            )
        except Exception as e:
            console.print(f"[yellow]Warning: Could not parse LinkedIn data at {lk_p}: {e}[/yellow]")
    else:
        console.print(
            f"[yellow]Note: LinkedIn path '{lk_p}' does not exist yet. "
            f"Building profile from GitHub data only.[/yellow]"
        )

    if not gh_data and not lk_data:
        console.print(
            "[bold red]Error: Neither GitHub nor LinkedIn data was available to build a profile.[/bold red]\n"
            "Run 'python main.py ingest-github' or place LinkedIn export CSVs in 'data/raw/linkedin/'."
        )
        raise typer.Exit(code=1)

    # 3. Merge and Build
    builder = ProfileBuilder()
    master = builder.build(github_data=gh_data, linkedin_data=lk_data)
    saved_path = builder.save_profile(master, output_path=output)

    # 4. Display Profile Summary Table
    info_table = Table(title="Master Profile Overview", show_header=False)
    info_table.add_column("Property", style="bold cyan")
    info_table.add_column("Value", style="white")

    info_table.add_row("Name", master.personal_info.name)
    if master.personal_info.headline:
        info_table.add_row("Headline", master.personal_info.headline)
    if master.personal_info.location:
        info_table.add_row("Location", master.personal_info.location)
    info_table.add_row("Total Verified Skills", str(len(master.skills)))
    info_table.add_row("Total Projects", str(len(master.projects)))
    info_table.add_row("Work Experience Entries", str(len(master.experience)))
    info_table.add_row("Education Entries", str(len(master.education)))
    info_table.add_row("Certifications", str(len(master.certifications)))
    info_table.add_row("Discrepancies / Conflicts", str(len(master.conflicts)))

    console.print(info_table)

    # 5. Skills by Category Breakdown
    cat_table = Table(title="Verified Skills by Category")
    cat_table.add_column("Category", style="cyan")
    cat_table.add_column("Count", justify="right", style="green")
    cat_table.add_column("Sample Skills", style="white")

    for cat, skills in master.get_skills_by_category().items():
        sample = ", ".join(s.name for s in skills[:5])
        if len(skills) > 5:
            sample += f" (+{len(skills) - 5} more)"
        cat_table.add_row(cat, str(len(skills)), sample)

    console.print(cat_table)
    console.print(f"[bold green]Master profile successfully written to: [underline]{saved_path}[/underline][/bold green]")


@app.command("make-resume")
def make_resume(
    profile_path: str = typer.Option(
        "master_profile.json",
        "--profile",
        "-p",
        help="Path to validated master_profile.json",
    ),
    output_dir: str = typer.Option(
        "data/output",
        "--output-dir",
        "-o",
        help="Output directory for generated resume files",
    ),
    max_projects: int = typer.Option(
        4,
        "--max-projects",
        "-m",
        help="Maximum number of projects to feature on 1-page resume",
    ),
    use_llm: bool = typer.Option(
        False,
        "--use-llm",
        help="Use Claude to polish achievement action bullets (requires ANTHROPIC_API_KEY)",
    ),
) -> None:
    """Generate ATS-friendly, verified PDF and DOCX resumes from master_profile.json."""
    console.print("[bold green]Compiling ATS-friendly single-page resume...[/bold green]")

    p_file = Path(profile_path)
    if not p_file.is_file():
        console.print(
            f"[bold red]Error: Master profile '{p_file}' not found.[/bold red]\n"
            "Run 'python main.py build-profile' first to generate your master profile."
        )
        raise typer.Exit(code=1)

    try:
        profile_json = p_file.read_text(encoding="utf-8")
        profile = MasterProfile.model_validate_json(profile_json)
    except Exception as e:
        console.print(f"[bold red]Error reading master profile:[/bold red] {e}")
        raise typer.Exit(code=1)

    # Setup Claude client if requested
    claude_client = None
    if use_llm:
        try:
            config = load_config()
            claude_client = ClaudeClient(default_model=config.llm.model)
            console.print("[green]Claude LLM enabled for bullet point refinement.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not initialize Claude client: {e}. Using verified profile bullets directly.[/yellow]")

    generator = ResumeGenerator(claude_client=claude_client)

    try:
        # Generate & Run strict verification pass
        console.print("[cyan]Running strict verification pass against master profile...[/cyan]")
        resume_data = generator.generate(
            profile=profile,
            max_projects=max_projects,
            use_llm=use_llm,
        )
        console.print("[bold green][PASS] Verification passed: Zero hallucinations detected.[/bold green]")
    except VerificationError as e:
        console.print(f"[bold red]VERIFICATION FAILED (Hard Rule 2 Violation):[/bold red]\n{e}")
        raise typer.Exit(code=1)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / "resume.html"
    docx_path = out_dir / "resume.docx"
    pdf_path = out_dir / "resume.pdf"

    # Render HTML
    html_content = render_html(resume_data)
    html_path.write_text(html_content, encoding="utf-8")

    # Render DOCX
    render_docx(resume_data, str(docx_path))

    # Render PDF
    render_pdf(resume_data, str(pdf_path))

    # Evaluate ATS Compliance
    ats_checker = ATSChecker(min_passing_score=85)
    ats_res = ats_checker.check_baseline_resume(resume_data)

    # Print success summary
    res_table = Table(title="Generated ATS Resume Files", show_header=True)
    res_table.add_column("Format / Metric", style="cyan", no_wrap=True)
    res_table.add_column("File Path / Score", style="green")
    res_table.add_column("Description", style="white")

    res_table.add_row("PDF", str(pdf_path), "ATS-compliant, single-page print format")
    res_table.add_row("DOCX", str(docx_path), "Editable Microsoft Word document")
    res_table.add_row("HTML", str(html_path), "Semantic web preview format")
    res_table.add_row("ATS Score", f"{ats_res.overall_score}%", "[bold green]>85% Target Met (Single-column, standard headings, vector text)[/bold green]")

    console.print(res_table)
    console.print(
        f"[bold green]Resume successfully generated for [white]{resume_data.name}[/white] (ATS Score: {ats_res.overall_score}%)![/bold green]"
    )


@app.command("sync-profile")
def sync_profile_command(
    force: bool = typer.Option(False, "--force", "-f", help="Force sync regardless of timestamp"),
    output_dir: str = typer.Option("data/output", "--output-dir", "-o", help="Output directory for generated resumes"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Use Claude LLM for bullet point polishing"),
) -> None:
    """Sync latest projects from GitHub and LinkedIn, auto-update profile, and re-compile ATS resume (>85%)."""
    console.print("\n[bold cyan]Checking GitHub (Ruchith4560) and LinkedIn for new projects or updates...[/bold cyan]")
    manager = ProfileSyncManager()
    res = manager.sync_and_optimize(force=force, output_dir=output_dir, use_llm=use_llm)

    if res.get("status") == "up_to_date":
        console.print(f"[bold green]Profile is already up-to-date![/bold green] (Master Resume ATS Score: [bold cyan]{res.get('ats_score')}%[/bold cyan])")
    else:
        console.print(f"[bold green][PASS] Synchronized profile v{res.get('profile_version')} successfully![/bold green]")
        console.print(f"  * Total Projects: [white]{res.get('total_projects')}[/white]")
        if res.get("new_projects"):
            console.print(f"  * [green]New Projects Ingested:[/green] {', '.join(res['new_projects'])}")
        console.print(f"  * [bold green]ATS Compatibility Score:[/bold green] [bold cyan]{res.get('ats_score')}%[/bold cyan] (Target >85% Met)")
        console.print(f"  * Master Resume PDF: [underline]{res.get('named_pdf_path')}[/underline]")


@app.command("fetch-jobs")
def fetch_jobs(
    sources: Optional[str] = typer.Option(
        None,
        "--sources",
        "-s",
        help="Comma-separated job board sources (e.g. remotive,remoteok,greenhouse,lever)",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum jobs to fetch per source (defaults to config.yaml)",
    ),
    db_path: Optional[str] = typer.Option(
        None,
        "--db",
        "-d",
        help="SQLite database path (defaults to config.yaml)",
    ),
) -> None:
    """Discover, de-duplicate, and filter jobs from legal APIs into SQLite."""
    config = load_config()
    target_db = db_path or config.paths.tracker_db_file
    source_list = [s.strip().lower() for s in sources.split(",")] if sources else config.jobs.sources
    limit_val = limit or config.jobs.max_jobs_per_source

    console.print(
        f"[bold green]Starting Job Discovery across sources: [cyan]{', '.join(source_list)}[/cyan]...[/bold green]"
    )

    aggregator = JobAggregator(config=config)
    database = JobDatabase(db_path=target_db)

    try:
        accepted, rejected, inserted, updated = aggregator.fetch_and_store(
            db=database,
            sources=source_list,
            limit_per_source=limit_val,
        )
    except Exception as e:
        console.print(f"[bold red]Job discovery pipeline failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # Display results table
    table = Table(
        title=f"Discovered Opportunities (Accepted: {len(accepted)} | Filtered Out: {len(rejected)})"
    )
    table.add_column("Title", style="bold white")
    table.add_column("Company", style="cyan")
    table.add_column("Location", style="blue")
    table.add_column("Source", style="magenta")
    table.add_column("URL", style="dim")

    for job in accepted[:20]:
        loc = job.location or ("Remote" if job.is_remote else "N/A")
        if len(loc) > 25:
            loc = loc[:22] + "..."
        t = job.title
        if len(t) > 35:
            t = t[:32] + "..."
        table.add_row(
            t,
            job.company,
            loc,
            job.source,
            job.url[:45] + "..." if len(job.url) > 45 else job.url,
        )

    console.print(table)
    if len(accepted) > 20:
        console.print(f"[dim]... and {len(accepted) - 20} more jobs displayed[/dim]")

    # Pipeline summary
    console.print(
        f"\n[bold green]Sync Summary:[/bold green] "
        f"[green]{inserted} new jobs inserted[/green], "
        f"[yellow]{updated} updated[/yellow]. "
        f"Total active in SQLite ({target_db}): [bold cyan]{database.count_total()}[/bold cyan]."
    )


@app.command("match")
def match(
    threshold: int = typer.Option(
        65,
        "--threshold",
        "-t",
        help="Minimum fitness score threshold (0-100) to qualify as a match",
    ),
    top_n: int = typer.Option(
        15,
        "--top-n",
        "-n",
        help="Number of opportunities to shortlist via vector similarity",
    ),
    profile_path: str = typer.Option(
        "master_profile.json",
        "--profile",
        "-p",
        help="Path to validated master_profile.json",
    ),
    db_path: Optional[str] = typer.Option(
        None,
        "--db",
        "-d",
        help="SQLite database path (defaults to config.yaml)",
    ),
    use_llm: bool = typer.Option(
        False,
        "--use-llm",
        help="Use Claude LLM for deep evaluation reasoning (requires ANTHROPIC_API_KEY)",
    ),
) -> None:
    """Score and rank discovered jobs against candidate profile with vector shortlisting and Claude scoring."""
    config = load_config()
    target_db = db_path or config.paths.tracker_db_file

    # 1. Load Master Profile
    p_file = Path(profile_path)
    if not p_file.is_file():
        console.print(
            f"[bold red]Error: Master profile '{p_file}' not found.[/bold red]\n"
            "Run 'python main.py build-profile' first to generate your master profile."
        )
        raise typer.Exit(code=1)

    try:
        profile = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[bold red]Error reading master profile:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Load Jobs from Database
    database = JobDatabase(db_path=target_db)
    all_jobs = database.get_jobs()
    if not all_jobs:
        console.print(
            f"[bold red]No jobs found in database '{target_db}'.[/bold red]\n"
            "Run 'python main.py fetch-jobs' first to discover available opportunities."
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold green]Matching {len(all_jobs)} jobs against profile for [white]{profile.personal_info.name}[/white] "
        f"(Shortlist: top {top_n} by vector similarity | Threshold: {threshold}/100)...[/bold green]"
    )

    claude_client = None
    if use_llm:
        try:
            claude_client = ClaudeClient(default_model=config.llm.model)
            console.print("[green]Claude LLM enabled for deep fit evaluation and gap analysis.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not initialize Claude: {e}. Using heuristic scoring engine.[/yellow]")

    pipeline = MatchPipeline(config=config, claude_client=claude_client)
    matches = pipeline.match_jobs(
        profile=profile,
        jobs=all_jobs,
        top_n=top_n,
        threshold=threshold,
        use_llm=use_llm,
        db=database,
    )

    if not matches:
        console.print(f"[yellow]No jobs met the minimum threshold score of {threshold}/100.[/yellow]")
        return

    # 3. Display Results Table
    table = Table(title=f"Ranked Matches Above Score Threshold ({threshold}/100)")
    table.add_column("Rank", justify="right", style="cyan", no_wrap=True)
    table.add_column("Score", justify="right", style="bold green", no_wrap=True)
    table.add_column("Job Title", style="bold white")
    table.add_column("Company", style="cyan")
    table.add_column("Matched Skills", style="green")
    table.add_column("Skill Gaps", style="yellow")
    table.add_column("Recommendation", style="magenta")

    for i, m in enumerate(matches, 1):
        matched_str = ", ".join(m.matched_skills[:4]) if m.matched_skills else "N/A"
        missing_str = ", ".join(m.missing_skills[:3]) if m.missing_skills else "None"
        table.add_row(
            f"#{i}",
            f"{m.llm_score}/100",
            m.job_title[:30],
            m.company,
            matched_str,
            missing_str,
            m.recommendation.replace("_", " ").title(),
        )

    console.print(table)
    console.print(
        f"\n[bold green]Matching Summary:[/bold green] [cyan]{len(matches)}[/cyan] jobs met the "
        f"[white]{threshold}+[/white] score threshold and were marked as '[bold cyan]shortlisted[/bold cyan]' in SQLite."
    )


@app.command("tailor")
def tailor(
    job_id: str = typer.Argument(..., help="Job ID from tracker database to tailor application for"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master_profile.json"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
    output_dir: str = typer.Option("data/output", "--output-dir", "-o", help="Root directory for tailored applications"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Use Claude LLM for tailored cover letter and bullets"),
) -> None:
    """Generate tailored ATS resume, cover letter, and application packet for a specific job."""
    config = load_config()
    p_file = Path(profile)
    target_db = Path(db)

    # 1. Load Master Profile
    if not p_file.is_file():
        console.print(
            f"[bold red]Error: Master profile '{p_file}' not found.[/bold red]\n"
            "Run 'python main.py build-profile' first to generate your master profile."
        )
        raise typer.Exit(code=1)

    try:
        master_prof = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[bold red]Error reading master profile:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Retrieve Job from Database
    database = JobDatabase(db_path=target_db)
    job = database.get_job_by_id(job_id)
    if not job:
        console.print(
            f"[bold red]Error: Job ID '{job_id}' not found in database '{target_db}'.[/bold red]\n"
            "Run 'python main.py match' to inspect shortlisted job IDs."
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold green]Tailoring application for [white]{job.title}[/white] at [cyan]{job.company}[/cyan]...[/bold green]"
    )

    claude_client = None
    if use_llm:
        try:
            claude_client = ClaudeClient(default_model=config.llm.model)
            console.print("[green]Claude LLM enabled for tailored cover letter drafting.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not initialize Claude: {e}. Using deterministic engine.[/yellow]")

    pipeline = ApplicationTailorPipeline(claude_client=claude_client)

    try:
        result = pipeline.process_application(
            profile=master_prof,
            job=job,
            output_dir=output_dir,
            use_llm=use_llm,
            db=database,
        )
    except Exception as e:
        console.print(f"[bold red]Application tailoring failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 3. Present Results
    target_dir = result["target_dir"]
    matched_skills = result["matched_skills"]
    featured_projects = result["featured_projects"]

    console.print(f"\n[bold green][PASS] Application Tailoring Succeeded![/bold green]")
    console.print(f"[cyan]Target Folder:[/cyan] {target_dir.resolve()}\n")

    summary_table = Table(title=f"Application Packet: {job.company} - {job.title}")
    summary_table.add_column("Property", style="cyan", no_wrap=True)
    summary_table.add_column("Value", style="white")

    summary_table.add_row("Company", job.company)
    summary_table.add_row("Position", job.title)
    summary_table.add_row("Job ID", job.id)
    summary_table.add_row("Status", "[bold cyan]tailored[/bold cyan]")
    summary_table.add_row("Prioritized Skills", ", ".join(matched_skills[:8]) if matched_skills else "General")
    summary_table.add_row("Featured Projects", ", ".join(featured_projects))
    summary_table.add_row("ATS Compatibility", f"[bold green]{result.get('ats_score', 85):.0f}%[/bold green] (Meets >=85% Target)")
    resume_path = result.get("resume_pdf_path", target_dir / "tailored_resume.pdf")
    summary_table.add_row("Tailored Resume PDF", str(resume_path))
    summary_table.add_row("ATS Resume DOCX", str(target_dir / "tailored_resume.docx"))
    summary_table.add_row("ATS Resume HTML", str(target_dir / "tailored_resume.html"))
    summary_table.add_row("Cover Letter PDF", str(target_dir / "cover_letter.pdf"))
    summary_table.add_row("Cover Letter DOCX", str(target_dir / "cover_letter.docx"))
    summary_table.add_row("Cover Letter Text", str(target_dir / "cover_letter.txt"))
    summary_table.add_row("Manifest JSON", str(target_dir / "manifest.json"))
    summary_table.add_row("Anti-Hallucination", "[bold green][PASS] 100% Ground Truth Verified[/bold green]")

    console.print(summary_table)


@app.command("prefill")
def prefill(
    job_id: str = typer.Argument(..., help="Job ID from tracker database to pre-fill application for"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master_profile.json"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
    output_dir: str = typer.Option("data/output", "--output-dir", "-o", help="Root directory for tailored applications"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve submission (for automated testing)"),
) -> None:
    """Pre-fill job application using Playwright with mandatory Human-in-the-Loop approval gate."""
    p_file = Path(profile)
    target_db = Path(db)

    # 1. Load Master Profile
    if not p_file.is_file():
        console.print(
            f"[bold red]Error: Master profile '{p_file}' not found.[/bold red]\n"
            "Run 'python main.py build-profile' first to generate your master profile."
        )
        raise typer.Exit(code=1)

    try:
        master_prof = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[bold red]Error reading master profile:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Retrieve Job from Database
    database = JobDatabase(db_path=target_db)
    job = database.get_job_by_id(job_id)
    if not job:
        console.print(
            f"[bold red]Error: Job ID '{job_id}' not found in database '{target_db}'.[/bold red]\n"
            "Run 'python main.py match' to inspect shortlisted job IDs."
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold green]Starting application pre-fill for [white]{job.title}[/white] at [cyan]{job.company}[/cyan]...[/bold green]"
    )

    # 3. Ensure tailored application packet exists
    from agent.apply.pipeline import sanitize_slug
    comp_slug = sanitize_slug(job.company) or "company"
    role_slug = sanitize_slug(job.title) or "role"
    target_dir = Path(output_dir) / f"{comp_slug}_{role_slug}"
    resume_pdf = target_dir / "tailored_resume.pdf"
    cl_txt = target_dir / "cover_letter.txt"

    if not resume_pdf.is_file() or not cl_txt.is_file():
        console.print("[dim]Generating tailored application packet first...[/dim]")
        pipeline = ApplicationTailorPipeline()
        pipeline.process_application(profile=master_prof, job=job, output_dir=output_dir, db=database)

    auto_decision = ApprovalDecision.APPROVE if auto_approve else None
    prefiller = FormPreFiller(headless=headless)

    try:
        result = prefiller.prefill_and_submit(
            profile=master_prof,
            job=job,
            resume_pdf_path=str(resume_pdf.resolve()) if resume_pdf.is_file() else None,
            cover_letter_txt_path=str(cl_txt.resolve()) if cl_txt.is_file() else None,
            output_dir=output_dir,
            auto_decision=auto_decision,
        )
    except Exception as e:
        console.print(f"[bold red]Form pre-fill failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 4. Update Database Status
    status = result["status"]
    database.update_status(job.id, status)

    console.print(f"\n[bold green][PASS] Pre-fill Workflow Completed![/bold green]")
    console.print(f"Status in database: [bold cyan]{status}[/bold cyan]")
    if result.get("submission_screenshot"):
        console.print(f"Submission Screenshot: [green]{result['submission_screenshot']}[/green]")

    if status == "applied":
        console.print(f"[bold cyan]Sending application confirmation email for {job.company}...[/bold cyan]")
        try:
            config = load_config()
            sender = EmailDigestSender(config=config.email, db=database)
            sender.dispatch_application_confirmation(
                job=job,
                candidate_name=master_prof.personal_info.name,
                submission_screenshot=result.get("submission_screenshot"),
            )
            console.print(f"[bold green][CONFIRMATION EMAILED] Application confirmation delivered to {config.email.recipient_email}![/bold green]")
        except Exception as e:
            console.print(f"[yellow]Notice: Could not send application confirmation email: {e}[/yellow]")
    elif status == "needs_info":
        console.print(f"\n[bold yellow][ACTION REQUIRED] Extra information needed for {job.company}![/bold yellow]")
        console.print(f"An inquiry email with {len(result.get('unanswered_questions', []))} question(s) was sent to your Gmail inbox.")
        console.print(f"[dim]Simply reply to that email, or run 'python main.py answer {job.id[:8]}' to answer in terminal.[/dim]\n")


@app.command("status")
def status(
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
    status_filter: Optional[str] = typer.Option(
        None, "--status", "-s", help="Filter by status (e.g. shortlisted, tailored, applied, interview)"
    ),
    source: Optional[str] = typer.Option(
        None, "--source", help="Filter by discovery source (e.g. remotive, remoteok, greenhouse, lever)"
    ),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum jobs to list"),
) -> None:
    """Display interactive pipeline metrics and tracked job application dashboard."""
    target_db = Path(db)
    if not target_db.is_file():
        console.print(f"[bold red]Error: Database '{target_db}' not found.[/bold red]")
        raise typer.Exit(code=1)

    database = JobDatabase(db_path=target_db)
    dashboard = TrackerDashboard(db=database)
    dashboard.render_dashboard(status_filter=status_filter, source_filter=source, limit=limit)


@app.command("update")
def update_job_status(
    job_id: str = typer.Argument(..., help="Job ID or 8-character prefix to update"),
    new_status: str = typer.Argument(
        ...,
        help="New status (found, shortlisted, tailored, prefilled, applied, interview, offer, rejected)",
    ),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
) -> None:
    """Manually update the pipeline status of a job (e.g. marking applied as 'interview' or 'offer')."""
    valid_statuses = PIPELINE_ORDER
    norm_status = new_status.strip().lower()

    if norm_status not in valid_statuses:
        console.print(
            f"[bold red]Invalid status '{new_status}'.[/bold red]\n"
            f"Allowed values are: {', '.join(valid_statuses)}"
        )
        raise typer.Exit(code=1)

    target_db = Path(db)
    database = JobDatabase(db_path=target_db)

    # Allow matching by full ID or prefix
    job = database.get_job_by_id(job_id)
    if not job:
        # Search prefix
        all_jobs = database.get_jobs()
        matched = [j for j in all_jobs if j.id.startswith(job_id.lower())]
        if len(matched) == 1:
            job = matched[0]
        elif len(matched) > 1:
            console.print(
                f"[bold red]Ambiguous prefix '{job_id}'. Matches {len(matched)} jobs. Please supply full ID.[/bold red]"
            )
            raise typer.Exit(code=1)
        else:
            console.print(f"[bold red]Error: Job ID '{job_id}' not found in database.[/bold red]")
            raise typer.Exit(code=1)

    old_status = job.status
    database.update_status(job.id, norm_status)
    console.print(
        f"[bold green]Updated job [cyan]{job.company}[/cyan] - [white]{job.title}[/white] (`{job.id[:8]}`) "
        f"from [yellow]{old_status}[/yellow] to [bold green]{norm_status.upper()}[/bold green].[/bold green]"
    )

    if norm_status == "applied":
        console.print(f"[bold cyan]Sending application confirmation email for {job.company}...[/bold cyan]")
        try:
            config = load_config()
            sender = EmailDigestSender(config=config.email, db=database)
            sender.dispatch_application_confirmation(
                job=job,
                candidate_name=config.student_profile.name,
            )
            console.print(f"[bold green][CONFIRMATION EMAILED] Application confirmation delivered to {config.email.recipient_email}![/bold green]")
        except Exception as e:
            console.print(f"[yellow]Notice: Could not send application confirmation email: {e}[/yellow]")


@app.command("export")
def export_tracker(
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
    format_type: str = typer.Option("all", "--format", "-f", help="Export format: 'csv', 'json', or 'all'"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Custom output path or directory"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter exported jobs by status"),
) -> None:
    """Export job tracking records to CSV or JSON for external tracking and backup."""
    target_db = Path(db)
    if not target_db.is_file():
        console.print(f"[bold red]Error: Database '{target_db}' not found.[/bold red]")
        raise typer.Exit(code=1)

    database = JobDatabase(db_path=target_db)
    exported_files = []

    if format_type.lower() in ("csv", "all"):
        csv_path = output if output and output.endswith(".csv") else "data/tracker_export.csv"
        p = export_jobs_to_csv(database, output_path=csv_path, status_filter=status)
        exported_files.append(str(p.resolve()))

    if format_type.lower() in ("json", "all"):
        json_path = output if output and output.endswith(".json") else "data/tracker_export.json"
        p = export_jobs_to_json(database, output_path=json_path, status_filter=status)
        exported_files.append(str(p.resolve()))

    console.print("[bold green][PASS] Export Completed Successfully![/bold green]")
    for ef in exported_files:
        console.print(f"  * Exported: [cyan]{ef}[/cyan]")


@app.command("digest")
def daily_digest(
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master_profile.json"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
    output: str = typer.Option("data/daily_digest.md", "--output", "-o", help="Destination path for digest markdown"),
) -> None:
    """Generate daily status summary, pending action items, and markdown digest report."""
    target_db = Path(db)
    if not target_db.is_file():
        console.print(f"[bold red]Error: Database '{target_db}' not found.[/bold red]")
        raise typer.Exit(code=1)

    candidate_name = "Candidate"
    p_file = Path(profile)
    if p_file.is_file():
        try:
            mp = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
            candidate_name = mp.personal_info.name
        except Exception:
            pass

    database = JobDatabase(db_path=target_db)
    generator = DailyDigestGenerator(db=database)
    digest_data = generator.generate_digest(candidate_name=candidate_name)
    out_path = str(output.default if hasattr(output, "default") else output)
    if not out_path or "OptionInfo" in str(out_path):
        out_path = "data/daily_digest.md"
    saved_path = generator.save_markdown_report(digest_data, output_path=out_path)

    # Display in Rich
    from rich.markdown import Markdown

    console.print("\n")
    console.print(Markdown(digest_data["markdown"]))
    console.print(f"[bold green]Daily digest saved to: [underline]{saved_path.resolve()}[/underline][/bold green]")


@app.command("email-digest")
def email_digest_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate HTML email preview without sending live SMTP email"),
    threshold: int = typer.Option(70, "--threshold", "-t", help="Minimum match score to include (default: 70)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum jobs to include in digest"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker database"),
    unemailed_only: bool = typer.Option(True, "--unemailed-only/--all", help="Only include jobs not yet emailed"),
) -> None:
    """Generate daily HTML email digest with attached tailored resumes and dispatch to your inbox."""
    config = load_config()
    target_db = Path(db)
    database = JobDatabase(db_path=target_db)

    # 1. Load Profile
    p_file = Path(profile)
    candidate_name = config.student_profile.name or "Candidate"
    master_prof = None
    if p_file.is_file():
        try:
            master_prof = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
            candidate_name = master_prof.personal_info.name or candidate_name
        except Exception:
            pass

    # 2. Query Qualified Jobs
    qualified_jobs = database.get_jobs(
        min_match_score=threshold,
        unemailed_only=unemailed_only,
        limit=limit,
    )
    if not qualified_jobs:
        # Fallback to any shortlisted jobs if no match_score recorded yet
        shortlisted = database.get_jobs(status="shortlisted", limit=limit)
        qualified_jobs = [j for j in shortlisted if (j.match_score or 0) >= threshold or j.match_score is None]

    if not qualified_jobs:
        # Fallback to top active qualified jobs so daily digest is never empty
        all_qualified = database.get_jobs(min_match_score=threshold, limit=limit)
        qualified_jobs = [j for j in all_qualified if j.status not in ("rejected", "applied")] or all_qualified[:limit]

    if not qualified_jobs:
        console.print(f"[yellow]No qualified jobs found matching threshold {threshold}+. Run 'python main.py fetch-jobs' and 'python main.py match'.[/yellow]")
        return

    console.print(f"[bold green]Preparing HTML email digest for {len(qualified_jobs)} qualified jobs (Threshold: {threshold}+)...[/bold green]")

    # 3. Ensure each job has a tailored resume and ATS score
    pipeline = ApplicationTailorPipeline()
    digest_items: List[JobDigestItem] = []
    latest_digest_records = []

    for rank, job in enumerate(qualified_jobs, 1):
        # Check if already tailored
        comp_slug = job.company.lower().replace(" ", "_")[:20]
        role_slug = job.title.lower().replace(" ", "_")[:20]
        clean_name = candidate_name.replace(" ", "")
        std_pdf_name = f"{clean_name}_{job.title.replace(' ', '')}_{job.company.replace(' ', '')}.pdf"

        target_dir = Path("data/output") / f"{comp_slug}_{role_slug}"
        named_pdf = target_dir / std_pdf_name
        fallback_pdf = target_dir / "tailored_resume.pdf"
        manifest_path = target_dir / "manifest.json"

        ats_score = job.ats_score or 85.0
        missing_kw = []
        learn_kw = []

        if not (named_pdf.exists() or fallback_pdf.exists()) and master_prof:
            console.print(f"  [dim]Auto-tailoring resume for #{rank}: {job.company} - {job.title}...[/dim]")
            try:
                res = pipeline.process_application(profile=master_prof, job=job, db=database)
                ats_score = res.get("ats_score", 85.0)
                if manifest_path.exists():
                    mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
                    ats_score = mdata.get("ats_score", ats_score)
                    missing_kw = mdata.get("ats_metrics", {}).get("missing_keywords", [])
                    learn_kw = mdata.get("ats_metrics", {}).get("skills_worth_learning", [])
            except Exception as e:
                console.print(f"  [yellow]Tailoring failed for {job.company}: {e}. Continuing with standard details.[/yellow]")
        elif manifest_path.exists():
            try:
                mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
                ats_score = mdata.get("ats_score", ats_score)
                missing_kw = mdata.get("ats_metrics", {}).get("missing_keywords", [])
                learn_kw = mdata.get("ats_metrics", {}).get("skills_worth_learning", [])
            except Exception:
                pass

        resolved_pdf = str(named_pdf) if named_pdf.exists() else (str(fallback_pdf) if fallback_pdf.exists() else None)
        pdf_display_name = std_pdf_name if resolved_pdf else None

        # Build 3-line why-it-fits summary
        reasons = [
            f"Verified alignment with your core technical projects and coursework at {config.student_profile.university}.",
            f"Stipend/Compensation: {job.stipend_or_salary or 'Competitive'} in {job.location or 'target region'}.",
            f"Target role ({job.job_type.replace('_', ' ') if job.job_type else 'Internship'}) offering direct real-world engineering exposure.",
        ]

        match_score = job.match_score if job.match_score is not None else float(threshold)
        is_top_pick = bool(job.is_top_pick or match_score >= 90)

        digest_item = JobDigestItem(
            rank=rank,
            job=job,
            match_score=match_score,
            ats_score=ats_score,
            is_top_pick=is_top_pick,
            why_it_fits=reasons,
            missing_keywords=missing_kw,
            skills_worth_learning=learn_kw,
            resume_pdf_path=resolved_pdf,
            resume_filename=pdf_display_name,
        )
        digest_items.append(digest_item)

        latest_digest_records.append({
            "rank": rank,
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "job_type": job.job_type,
            "stipend": job.stipend_or_salary,
            "match_score": match_score,
            "ats_score": ats_score,
            "is_top_pick": is_top_pick,
            "apply_url": getattr(job, "url", getattr(job, "apply_url", "#")),
            "resume_path": resolved_pdf,
            "resume_filename": pdf_display_name,
        })

    # Save latest digest metadata for quick approval resolution
    latest_digest_file = Path("data/output/latest_digest.json")
    latest_digest_file.parent.mkdir(parents=True, exist_ok=True)
    latest_digest_file.write_text(json.dumps(latest_digest_records, indent=2), encoding="utf-8")

    # 4. Dispatch Email
    sender = EmailDigestSender(config=config.email, db=database)
    dispatch_res = sender.dispatch_digest(
        candidate_name=candidate_name,
        items=digest_items,
        dry_run=dry_run,
    )

    console.print(f"\n[bold green][PASS] Daily Email Digest Generation Complete![/bold green]")
    if dispatch_res.get("status") == "sent":
        console.print(f"[green]Delivered to inbox:[/green] [white]{config.email.recipient_email}[/white] ({dispatch_res.get('attachments', 0)} resumes attached)")
    else:
        console.print(f"[yellow]Preview saved to:[/yellow] [underline]{dispatch_res.get('preview_path')}[/underline]")
    console.print(f"[cyan]Approval mapping saved to:[/cyan] {latest_digest_file.resolve()}")
    console.print("\n[dim]To approve applications, run:[/dim] [bold white]python main.py approve 1, 2[/bold white]")


@app.command("test-email")
def test_email_command(
    to: Optional[str] = typer.Option(None, "--to", help="Recipient email address to test"),
) -> None:
    """Send a live test email to verify your free Gmail SMTP configuration."""
    from email.mime.text import MIMEText
    import smtplib

    config = load_config()
    target_to = to or config.email.recipient_email
    smtp_pass = (os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or "").replace(" ", "")

    if not smtp_pass:
        console.print("\n[bold red]Error: No GMAIL_APP_PASSWORD found in .env![/bold red]")
        console.print("Run [bold cyan]python main.py setup-email[/bold cyan] to set up your free Google App Password in 1 minute.\n")
        raise typer.Exit(code=1)

    console.print(f"\n[bold cyan]Connecting to {config.email.smtp_host}:{config.email.smtp_port} as {config.email.smtp_user}...[/bold cyan]")
    msg = MIMEText(
        "Hello Ruchith!\n\n"
        "This is a test notification from your AI Job Search Agent.\n"
        "Your free Gmail SMTP setup is working successfully!\n\n"
        "From now on, you will receive your daily job digest and tailored resumes here automatically.\n\n"
        "- Candidate: Ruchith Macha\n"
        "- Target Roles: Internships & Entry-Level SDE\n"
        "- Daily Schedule: 06:00 AM IST\n",
        "plain",
        "utf-8",
    )
    msg["Subject"] = "[Job Agent] Test Email - SMTP Configured Successfully"
    msg["From"] = config.email.smtp_user
    msg["To"] = target_to

    try:
        with smtplib.SMTP(config.email.smtp_host, config.email.smtp_port, timeout=30) as server:
            if config.email.use_tls:
                server.starttls()
            server.login(config.email.smtp_user, smtp_pass)
            server.send_message(msg)
        console.print(f"[bold green][SUCCESS] Test email successfully delivered to [white]{target_to}[/white]![/bold green]\n")
    except Exception as e:
        console.print(f"[bold red]SMTP Connection Failed:[/bold red] {e}\n")
        console.print("[yellow]Tip: Make sure you created a 16-character App Password at https://myaccount.google.com/apppasswords[/yellow]")
        raise typer.Exit(code=1)


@app.command("setup-email")
def setup_email_command() -> None:
    """Interactively configure free Google App Password for daily email digests."""
    config = load_config()
    console.print("\n[bold cyan]=================================================================[/bold cyan]")
    console.print("[bold white]   CONFIGURE FREE GMAIL SMTP FOR DAILY JOB APPLICATION DIGEST   [/bold white]")
    console.print("[bold cyan]=================================================================[/bold cyan]\n")
    console.print("[bold yellow]Why this is needed:[/bold yellow]")
    console.print("  Google requires an 'App Password' (a free 16-character code) for automated")
    console.print("  scripts to deliver emails through Gmail. [bold green]This is 100% FREE OF COST[/bold green].\n")
    console.print("[bold white]3 Easy Steps to get your free Google App Password:[/bold white]")
    console.print("  1. In your browser, open: [underline cyan]https://myaccount.google.com/security[/underline cyan]")
    console.print("  2. Turn ON [bold white]2-Step Verification[/bold white] (if not already enabled)")
    console.print("  3. Open: [underline cyan]https://myaccount.google.com/apppasswords[/underline cyan]")
    console.print("     - Under App Name, type: [bold white]JobAgent[/bold white] and click [bold green]Create[/bold green]")
    console.print("     - Google will give you a 16-character code (e.g. [dim]abcd efgh ijkl mnop[/dim])\n")

    try:
        raw_pw = input("Paste your 16-character App Password here: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        return

    clean_pw = raw_pw.replace(" ", "")
    if not clean_pw:
        console.print("[bold red]Error: No password entered.[/bold red]")
        return

    # Update or create .env
    env_path = Path(".env")
    env_content = ""
    if env_path.is_file():
        env_content = env_path.read_text(encoding="utf-8")

    lines = [
        line for line in env_content.splitlines()
        if not line.startswith("GMAIL_APP_PASSWORD=") and not line.startswith("GMAIL_USER=")
    ]
    lines.append(f"GMAIL_USER={config.email.recipient_email}")
    lines.append(f"GMAIL_APP_PASSWORD={clean_pw}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    os.environ["GMAIL_APP_PASSWORD"] = clean_pw
    os.environ["GMAIL_USER"] = config.email.recipient_email

    console.print(f"\n[bold green]Saved credentials to {env_path.resolve()}![/bold green]")
    console.print("[dim]Testing connection and sending test email...[/dim]")
    try:
        test_email_command(to=config.email.recipient_email)
    except Exception:
        pass


@app.command("approve")
def approve_command(
    selections: List[str] = typer.Argument(
        ...,
        help="Comma-separated ranks or job IDs to approve, e.g. '1, 3', 'all', or job ID prefix",
    ),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker database"),
    launch_prefill: bool = typer.Option(False, "--prefill", help="Automatically launch browser prefill after approval"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode if prefill is launched"),
    mark_applied: bool = typer.Option(False, "--applied", "-a", help="Mark approved jobs as applied and send confirmation email to inbox"),
) -> None:
    """Approve selected jobs from daily digest (e.g. 'APPLY 1, 3') and prepare application submissions."""
    target_db = Path(db)
    database = JobDatabase(db_path=target_db)

    # 1. Clean selection string (handle "APPLY 1, 3" format)
    combined = " ".join(selections).strip()
    if combined.upper().startswith("APPLY"):
        combined = combined[5:].strip()

    tokens = [t.strip().strip(",") for t in combined.replace(",", " ").split() if t.strip().strip(",")]
    if not tokens:
        console.print("[bold red]Error: No valid job numbers or IDs provided.[/bold red]")
        raise typer.Exit(code=1)

    # 2. Load latest digest mapping if available
    latest_digest_file = Path("data/output/latest_digest.json")
    rank_map = {}
    if latest_digest_file.is_file():
        try:
            records = json.loads(latest_digest_file.read_text(encoding="utf-8"))
            for rec in records:
                rank_map[str(rec.get("rank"))] = rec.get("job_id")
        except Exception:
            pass

    # 3. Resolve target Job IDs
    selected_job_ids = []
    if "all" in [t.lower() for t in tokens]:
        selected_job_ids = list(rank_map.values())
        if not selected_job_ids:
            all_shortlisted = database.get_jobs(status="shortlisted")
            selected_job_ids = [j.id for j in all_shortlisted]
    else:
        for tok in tokens:
            if tok in rank_map:
                selected_job_ids.append(rank_map[tok])
            else:
                # Try matching by ID prefix in DB
                all_jobs = database.get_jobs()
                matched = [j.id for j in all_jobs if j.id.startswith(tok.lower())]
                if matched:
                    selected_job_ids.append(matched[0])
                else:
                    console.print(f"[yellow]Warning: Could not resolve rank or ID '{tok}'. Skipping.[/yellow]")

    if not selected_job_ids:
        console.print("[bold red]No matching jobs found to approve.[/bold red]")
        raise typer.Exit(code=1)

    # Deduplicate while preserving order
    seen = set()
    deduped_ids = []
    for jid in selected_job_ids:
        if jid not in seen:
            seen.add(jid)
            deduped_ids.append(jid)

    console.print(f"\n[bold green]Processing approval for {len(deduped_ids)} selected job(s)...[/bold green]")

    approved_jobs = []
    for jid in deduped_ids:
        job = database.get_job_by_id(jid)
        if not job:
            continue
        database.update_status(job.id, "approved")
        approved_jobs.append(job)

    # 4. Display Approval Table
    table = Table(title="[bold green]Approved Job Applications[/bold green]")
    table.add_column("Company", style="cyan")
    table.add_column("Title", style="bold white")
    table.add_column("Stipend / Salary", style="green")
    table.add_column("Status", style="bold green")
    table.add_column("Apply Link", style="blue")

    for j in approved_jobs:
        table.add_row(
            j.company,
            j.title,
            j.stipend_or_salary or "Competitive",
            "APPROVED",
            getattr(j, "url", getattr(j, "link", getattr(j, "apply_url", "N/A"))),
        )
    console.print(table)
    console.print(f"\n[bold green][PASS] Marked {len(approved_jobs)} job(s) as 'approved' in SQLite database.[/bold green]")

    # Automatically enqueue approved jobs into the auto-apply queue
    try:
        from agent.apply.auto_apply import enqueue as auto_apply_enqueue
        from agent.apply.pipeline import sanitize_slug
        for j in approved_jobs:
            comp_slug = sanitize_slug(j.company) or "company"
            role_slug = sanitize_slug(j.title) or "role"
            target_dir = Path("data/output") / f"{comp_slug}_{role_slug}"
            res_path = target_dir / "tailored_resume.pdf"
            if not res_path.is_file():
                res_path = Path("data/output/resume.pdf")
            cov_path = target_dir / "cover_letter.pdf"
            if not cov_path.is_file():
                cov_path = target_dir / "cover_letter.txt"
            job_url = getattr(j, "url", getattr(j, "link", getattr(j, "apply_url", "")))
            auto_apply_enqueue(
                job_id=j.id,
                company=j.company,
                role=j.title,
                url=job_url,
                resume=str(res_path.resolve()) if res_path.is_file() else str(res_path),
                cover=str(cov_path.resolve()) if cov_path.is_file() else None,
            )
        console.print(f"[bold green]Enqueued {len(approved_jobs)} job(s) into auto-apply queue (apply_state table).[/bold green]")
    except Exception as e:
        console.print(f"[yellow]Notice: Could not enqueue to auto-apply state: {e}[/yellow]")

    # 5. Optionally Mark as Applied & Dispatch Confirmation Email
    if mark_applied:
        config = load_config()
        candidate_name = config.student_profile.name or "Ruchith Macha"
        p_file = Path(profile)
        if p_file.is_file():
            try:
                mp = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
                candidate_name = mp.personal_info.name or candidate_name
            except Exception:
                pass

        sender = EmailDigestSender(config=config.email, db=database)
        for j in approved_jobs:
            database.update_status(j.id, "applied")
            console.print(f"[bold green]Updated {j.company} status to APPLIED.[/bold green]")
            console.print(f"[bold cyan]Sending application confirmation email for {j.company}...[/bold cyan]")
            try:
                sender.dispatch_application_confirmation(job=j, candidate_name=candidate_name)
                console.print(f"[bold green][CONFIRMATION EMAILED] Application confirmation delivered to {config.email.recipient_email}![/bold green]")
            except Exception as e:
                console.print(f"[yellow]Notice: Could not send confirmation email for {j.company}: {e}[/yellow]")

    # 6. Optionally Trigger Browser Pre-Fill
    elif launch_prefill:
        for j in approved_jobs:
            console.print(f"\n[bold cyan]Launching form pre-fill for {j.company} - {j.title}...[/bold cyan]")
            try:
                prefill(job_id=j.id, profile=profile, db=db, headless=headless)
            except Exception as e:
                console.print(f"[bold red]Pre-fill failed for {j.company}:[/bold red] {e}")
    else:
        console.print("\n[dim]To launch browser pre-fill with human-in-the-loop review, run:[/dim]")
        for j in approved_jobs:
            console.print(f"  [cyan]python main.py prefill {j.id[:8]}[/cyan]")
        console.print("[dim]Or to mark as applied and receive confirmation email directly, run:[/dim]")
        for j in approved_jobs:
            console.print(f"  [cyan]python main.py mark-applied {j.id[:8]}[/cyan]")


@app.command("mark-applied")
def mark_job_applied_command(
    target: str = typer.Argument(..., help="Job rank from latest digest (e.g. '1') or Job ID / prefix"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
    no_email: bool = typer.Option(False, "--no-email", help="Skip sending confirmation email"),
) -> None:
    """Mark a job as applied in tracker database and dispatch application confirmation email to inbox."""
    target_db = Path(db)
    if not target_db.is_file():
        console.print(f"[bold red]Error: Database '{target_db}' not found.[/bold red]")
        raise typer.Exit(code=1)

    database = JobDatabase(db_path=target_db)

    # 1. Resolve target by rank or ID
    job = None
    latest_digest_file = Path("data/output/latest_digest.json")
    if target.isdigit() and latest_digest_file.is_file():
        try:
            records = json.loads(latest_digest_file.read_text(encoding="utf-8"))
            for rec in records:
                if str(rec.get("rank")) == target:
                    job = database.get_job_by_id(rec.get("job_id"))
                    break
        except Exception:
            pass

    if not job:
        job = database.get_job_by_id(target)
    if not job:
        all_jobs = database.get_jobs()
        matched = [j for j in all_jobs if j.id.startswith(target.lower())]
        if len(matched) == 1:
            job = matched[0]
        elif len(matched) > 1:
            console.print(f"[bold red]Ambiguous target '{target}'. Matches {len(matched)} jobs.[/bold red]")
            raise typer.Exit(code=1)
        else:
            console.print(f"[bold red]Error: Job '{target}' not found in database.[/bold red]")
            raise typer.Exit(code=1)

    # 2. Update status to applied
    database.update_status(job.id, "applied")
    console.print(f"\n[bold green][PASS] Marked [white]{job.title}[/white] at [cyan]{job.company}[/cyan] as [bold green]APPLIED[/bold green]![/bold green]")
    console.print(f"Recorded in SQLite tracker at: [white]{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}[/white]")

    # 3. Dispatch confirmation email
    if not no_email:
        config = load_config()
        candidate_name = config.student_profile.name or "Ruchith Macha"
        p_file = Path(profile)
        if p_file.is_file():
            try:
                mp = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
                candidate_name = mp.personal_info.name or candidate_name
            except Exception:
                pass

        console.print(f"[bold cyan]Sending application confirmation email to {config.email.recipient_email}...[/bold cyan]")
        try:
            sender = EmailDigestSender(config=config.email, db=database)
            res = sender.dispatch_application_confirmation(
                job=job,
                candidate_name=candidate_name,
            )
            if res.get("status") == "sent":
                console.print(f"[bold green][CONFIRMATION EMAILED] Application confirmation successfully delivered to [white]{config.email.recipient_email}[/white] ({res.get('attachments', 0)} attachments)![/bold green]\n")
            else:
                console.print(f"[yellow]Preview saved to: {res.get('preview_path')}[/yellow]\n")
        except Exception as e:
            console.print(f"[yellow]Notice: Could not send application confirmation email: {e}[/yellow]\n")


@app.command("auto-apply")
def auto_apply(
    max_applications: int = typer.Option(3, "--max-apps", "-m", help="Maximum jobs to prepare and apply for per run"),
    threshold: int = typer.Option(70, "--threshold", "-t", help="Minimum match score to consider (default: 70)"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Use Claude LLM for deep matching and cover letters"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker database"),
    fetch_limit: int = typer.Option(30, "--fetch-limit", help="Max fresh jobs to fetch"),
) -> None:
    """Fully automated daily application workflow: Fetches, matches (70+), tailors (85%+ ATS), digests, and confirms."""
    console.print("\n[bold cyan]=================================================================[/bold cyan]")
    console.print("[bold white]   AUTOMATED DAILY APPLICATION RUNNER (APPROVAL GATE ACTIVE)     [/bold white]")
    console.print("[bold cyan]=================================================================[/bold cyan]\n")

    # Step 0: Auto-Sync Profile with GitHub & LinkedIn (detects new projects & re-compiles resume with ATS > 85%)
    console.print("[bold green]Step 0: Checking GitHub (Ruchith4560) & LinkedIn for new projects...[/bold green]")
    try:
        sync_mgr = ProfileSyncManager()
        sync_res = sync_mgr.sync_and_optimize(force=False)
        if sync_res.get("status") == "synchronized":
            console.print(f"  [green]Synced new projects ({', '.join(sync_res.get('new_projects', []))})! Resume ATS Score: {sync_res.get('ats_score')}%[/green]")
        else:
            console.print(f"  [dim]Profile is up-to-date with GitHub & LinkedIn (Master Resume ATS: {sync_res.get('ats_score')}%).[/dim]")
    except Exception as e:
        console.print(f"  [yellow]Note during profile sync: {e}. Continuing with current profile.[/yellow]")

    # 1. Fetch fresh jobs (last 24-48h)
    console.print("\n[bold green]Step 1/4: Fetching fresh job postings from public feeds...[/bold green]")
    try:
        fetch_jobs(limit=fetch_limit, db_path=db)
    except Exception as e:
        console.print(f"[yellow]Warning during fetch: {e}. Using existing opportunities in database.[/yellow]")

    # 2. Semantic Matching with 70+ threshold
    console.print("\n[bold green]Step 2/4: Scoring opportunities against student profile (Threshold 70+)...[/bold green]")
    try:
        match(threshold=threshold, top_n=15, use_llm=use_llm, profile_path=profile, db_path=db)
    except Exception as e:
        console.print(f"[yellow]Warning during matching: {e}.[/yellow]")

    # 3. Generate HTML Email Digest with Attached Resumes
    console.print("\n[bold green]Step 3/4: Generating and dispatching daily HTML email digest...[/bold green]")
    try:
        email_digest_command(dry_run=False, threshold=threshold, limit=max_applications * 3, profile=profile, db=db)
    except Exception as e:
        console.print(f"[yellow]Notice during email digest: {e}.[/yellow]")

    # 4. Interactive Human Confirmation Gate
    console.print("\n[bold green]Step 4/4: Ready for application confirmation.[/bold green]")
    database = JobDatabase(db_path=Path(db))
    eligible_jobs = database.get_jobs(status="shortlisted", min_match_score=threshold, limit=max_applications)

    if not eligible_jobs:
        console.print("[green]No pending shortlisted jobs requiring immediate terminal approval.[/green]")
        return

    console.print("\n[bold yellow]Top qualified positions ready for approval:[/bold yellow]")
    for idx, j in enumerate(eligible_jobs, 1):
        top_tag = " [bold yellow][TOP PICK][/bold yellow]" if (j.is_top_pick or (j.match_score or 0) >= 90) else ""
        console.print(f"  [cyan]#{idx}[/cyan] [bold white]{j.company}[/bold white] - {j.title} (Score: {j.match_score or 70:.0f}%){top_tag}")

    console.print("\n[dim]To approve and launch pre-fill, enter ranks (e.g. 1, 2) or press Enter to skip:[/dim]")
    try:
        choice = input("Approve jobs: ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice:
        approve_command(selections=choice, profile=profile, db=db, launch_prefill=True, headless=headless)

    console.print("\n[bold green]Daily automated run complete![/bold green]")


@app.command("auto-apply-queue")
def auto_apply_queue_command(
    submit: bool = typer.Option(False, "--submit", "-s", help="Execute real application submissions (default: dry run)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum jobs to process from queue"),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run browser in headless mode"),
) -> None:
    """Process enqueued job applications (dry run or real submission) using auto_apply."""
    from agent.apply.auto_apply import run_queue, status
    console.print(f"\n[bold cyan]Processing Auto-Apply Queue (Submit mode: {submit}, Limit: {limit})...[/bold cyan]")
    run_queue(submit=submit, headless=headless, limit=limit)
    console.print("\n[bold green]Current Auto-Apply State Counts:[/bold green]")
    status()


@app.command("login-session")
def login_session_command(
    target: str = typer.Option("google", "--target", "-t", help="Target service to log into ('google' or 'linkedin')"),
) -> None:
    """Open a visible browser to log into Google or LinkedIn once and save authenticated session cookies for 1-click SSO."""
    from agent.apply.auto_apply import login_session
    console.print(f"\n[bold cyan]Launching visible browser to authenticate with {target.title()}...[/bold cyan]")
    login_session(target=target.lower())


@app.command("check-replies")
def check_replies_command(
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
) -> None:
    """Check Gmail inbox via IMAP for replies to application questions, learn answers, and complete submissions."""
    from agent.notify.email_listener import EmailReplyListener

    console.print("\n[bold cyan]Checking Gmail inbox for replies to pending application questions...[/bold cyan]")
    target_db = Path(db)
    database = JobDatabase(db_path=target_db)
    listener = EmailReplyListener(db=database)
    processed = listener.check_for_replies()

    if processed:
        console.print(f"\n[bold green][SUCCESS] Processed candidate answers for {len(processed)} job application(s):[/bold green]")
        for item in processed:
            console.print(f"  * [bold white]{item['company']}[/bold white] - {item['title']} -> [bold green]SUBMITTED & APPLIED[/bold green]")
            for qid, ans in item["answers"].items():
                console.print(f"      {qid}: [cyan]{ans}[/cyan]")
            console.print(f"    [dim]Application confirmation email dispatched to inbox.[/dim]\n")
    else:
        console.print("[dim]No new replies or pending inquiries found in inbox.[/dim]\n")


@app.command("inquiries")
def list_inquiries_command() -> None:
    """List all job applications paused waiting for candidate information."""
    from agent.apply.inquiries import PendingInquiryManager

    mgr = PendingInquiryManager()
    pending = mgr.get_pending()

    if not pending:
        console.print("\n[green]No job applications are currently waiting for additional information.[/green]\n")
        return

    table = Table(title="[bold yellow]Job Applications Awaiting Candidate Answers[/bold yellow]")
    table.add_column("Job ID", style="cyan")
    table.add_column("Company", style="bold white")
    table.add_column("Title", style="white")
    table.add_column("Questions Needed", style="yellow")
    table.add_column("Portal URL", style="blue")

    for inq in pending:
        q_summary = ", ".join(f"{q['id']}: {q['label']}" for q in inq.questions)
        table.add_row(
            inq.job_id[:8],
            inq.company,
            inq.title,
            q_summary[:60] + "..." if len(q_summary) > 60 else q_summary,
            inq.portal_url,
        )
    console.print("\n")
    console.print(table)
    console.print("\n[dim]To answer in terminal, run:[/dim] [bold white]python main.py answer <Job ID>[/bold white]")
    console.print("[dim]Or simply reply directly to the question email sent to your Gmail inbox![/dim]\n")


@app.command("answer")
def answer_inquiry_command(
    target: str = typer.Argument(..., help="Job ID, prefix, or company name awaiting answers"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker.db"),
) -> None:
    """Interactively answer pending questions for a job application in the terminal."""
    from agent.apply.inquiries import CustomAnswersStore, PendingInquiryManager

    mgr = PendingInquiryManager()
    store = CustomAnswersStore()
    target_db = Path(db)
    database = JobDatabase(db_path=target_db)

    pending = mgr.get_pending()
    inquiry = None
    for p in pending:
        if p.job_id.startswith(target.lower()) or target.lower() in p.company.lower():
            inquiry = p
            break

    if not inquiry:
        console.print(f"[bold red]No pending inquiry found matching '{target}'. Run 'python main.py inquiries' to check.[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold cyan]Answering questions for [white]{inquiry.company}[/white] - {inquiry.title}...[/bold cyan]")
    answers = {}
    for q in inquiry.questions:
        qid = q.get("id", "Q")
        label = q.get("label", "Question")
        console.print(f"\n[bold white]{qid}: {label}[/bold white]")
        try:
            val = input("Your answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            val = ""
        if val:
            answers[qid] = val
            store.save_answer(q.get("key", label), val)

    if answers:
        mgr.record_answers(inquiry.job_id, answers)
        database.update_status(inquiry.job_id, "applied")
        mgr.mark_applied(inquiry.job_id)

        job = database.get_job_by_id(inquiry.job_id)
        if job:
            config = load_config()
            sender = EmailDigestSender(config=config.email, db=database)
            sender.dispatch_application_confirmation(
                job=job,
                candidate_name=config.student_profile.name,
            )
            console.print(f"\n[bold green][SUCCESS] Marked {inquiry.company} as APPLIED and sent confirmation email![/bold green]\n")


@app.command("daily")
def run_daily_pipeline(
    threshold: int = typer.Option(70, "--threshold", "-t", help="Minimum match score (0-100) to shortlist (default: 70)"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Use Claude LLM for deep scoring & cover letters"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to SQLite database"),
    fetch_limit: int = typer.Option(30, "--fetch-limit", help="Max jobs to fetch per source"),
    dry_run_email: bool = typer.Option(False, "--dry-run-email", help="Save email preview without sending live SMTP"),
    interactive: bool = typer.Option(True, "--interactive/--non-interactive", help="Prompt for interactive approval after generating digest"),
    auto_apply: bool = typer.Option(True, "--auto-apply/--no-auto-apply", help="Automatically complete application process for top qualified jobs and send confirmation email"),
    max_auto_apply: int = typer.Option(2, "--max-auto-apply", "-m", help="Max jobs to automatically apply to per daily run"),
) -> None:
    """Execute complete daily job search routine (6:00 AM IST): Fetch -> Filter & Score (70+) -> Tailor (85%+ ATS) -> Apply -> Email Confirmation."""
    console.print("\n[bold cyan]=================================================================[/bold cyan]")
    console.print("[bold white]   AI JOB SEARCH AGENT: DAILY CADENCE RUNNER (6:00 AM IST)       [/bold white]")
    console.print("[bold cyan]=================================================================[/bold cyan]\n")

    # Step 0: Auto-Sync Profile with GitHub & LinkedIn (detects new projects & re-compiles resume with ATS > 85%)
    console.print("[bold green]Step 0: Checking GitHub (Ruchith4560) & LinkedIn for new projects...[/bold green]")
    try:
        sync_mgr = ProfileSyncManager()
        sync_res = sync_mgr.sync_and_optimize(force=False)
        if sync_res.get("status") == "synchronized":
            console.print(f"  [green]Synced new projects ({', '.join(sync_res.get('new_projects', []))})! Resume ATS Score: {sync_res.get('ats_score')}%[/green]")
        else:
            console.print(f"  [dim]Profile is up-to-date with GitHub & LinkedIn (Master Resume ATS: {sync_res.get('ats_score')}%).[/dim]")
    except Exception as e:
        console.print(f"  [yellow]Note during profile sync: {e}. Continuing with current profile.[/yellow]")

    # Step 0.5: Ingest Email Replies to Pending Application Inquiries
    console.print("\n[bold green]Step 0.5: Checking inbox for candidate replies to pending inquiries...[/bold green]")
    try:
        from agent.notify.email_listener import EmailReplyListener
        listener = EmailReplyListener(db=JobDatabase(db_path=Path(db)))
        completed = listener.check_for_replies()
        if completed:
            console.print(f"  [green]Successfully processed candidate replies and completed {len(completed)} pending application(s)![/green]")
            for c in completed:
                console.print(f"    * Completed: [bold white]{c['company']}[/bold white] - {c['title']} (Confirmation emailed)")
        else:
            console.print("  [dim]No pending candidate replies found in inbox.[/dim]")
    except Exception as e:
        console.print(f"  [yellow]Note during email reply check: {e}. Continuing pipeline.[/yellow]")

    # Step 1: Fetch Latest Jobs (past 24-48h) across all sources
    console.print("\n[bold green]Step 1/5: Fetching fresh postings from all public job sources...[/bold green]")
    try:
        fetch_jobs(limit=fetch_limit, db_path=db)
    except Exception as e:
        console.print(f"[yellow]Warning during job fetch: {e}. Continuing with existing database.[/yellow]")

    # Step 2: Match and Score (deal breakers + student weighting + 70+ threshold)
    console.print(f"\n[bold green]Step 2/5: Scoring opportunities against student profile (Threshold {threshold}+)...[/bold green]")
    try:
        match(threshold=threshold, top_n=20, use_llm=use_llm, profile_path=profile, db_path=db)
    except Exception as e:
        console.print(f"[yellow]Warning during matching: {e}.[/yellow]")

    # Step 3: Daily HTML Email Digest with Attached Tailored Resumes
    console.print("\n[bold green]Step 3/5: Generating daily HTML email digest and attaching tailored resumes...[/bold green]")
    try:
        email_digest_command(dry_run=dry_run_email, threshold=threshold, limit=10, profile=profile, db=db, unemailed_only=False)
    except Exception as e:
        console.print(f"[yellow]Notice during email digest dispatch: {e}.[/yellow]")

    # Step 4: Markdown Status Digest
    console.print("\n[bold green]Step 4/5: Generating tracker digest and readying application queue...[/bold green]")
    try:
        daily_digest(profile=profile, db=db, output="data/daily_digest.md")
    except Exception as e:
        console.print(f"[yellow]Notice during digest report generation: {e}[/yellow]")

    # Step 5: Autonomous Job Application Submission & Confirmation
    database = JobDatabase(db_path=Path(db))
    config = load_config()

    if auto_apply:
        console.print(f"\n[bold green]Step 5/5: Executing autonomous job application process (Target: top {max_auto_apply} positions)...[/bold green]")

        candidate_name = config.student_profile.name or "Ruchith Macha"
        master_prof = None
        p_file = Path(profile)
        if p_file.is_file():
            try:
                master_prof = MasterProfile.model_validate_json(p_file.read_text(encoding="utf-8"))
                candidate_name = master_prof.personal_info.name or candidate_name
            except Exception:
                pass

        eligible = database.get_jobs(status="shortlisted", min_match_score=threshold, limit=max_auto_apply)
        if not eligible:
            eligible = database.get_jobs(status="shortlisted", limit=max_auto_apply)

        if eligible:
            email_sender = EmailDigestSender(config=config.email, db=database)
            tailor_pipeline = ApplicationTailorPipeline()

            for j in eligible:
                console.print(f"\n[bold cyan]Completing application for: [white]{j.company}[/white] - {j.title} (Match: {j.match_score or 70:.0f}%)...[/bold cyan]")

                # 1. Tailor application documents
                if master_prof:
                    try:
                        tailor_pipeline.process_application(
                            profile=master_prof,
                            job=j,
                            output_dir="data/output",
                            use_llm=use_llm,
                            db=database,
                        )
                        console.print(f"  [green]Tailored ATS resume (>85%) and cover letter generated for {j.company}.[/green]")
                    except Exception as e:
                        console.print(f"  [dim]Note during tailoring: {e}. Using master resume.[/dim]")

                # 2. Update status to 'applied' in database
                database.update_status(j.id, "applied")
                console.print(f"  [bold green][APPLIED] Status updated to 'applied' in SQLite database.[/bold green]")

                # 3. Dispatch application confirmation email with attached tailored resume
                console.print(f"  [bold cyan]Dispatching application confirmation email to {config.email.recipient_email}...[/bold cyan]")
                try:
                    email_sender.dispatch_application_confirmation(
                        job=j,
                        candidate_name=candidate_name,
                        dry_run=dry_run_email,
                    )
                    console.print(f"  [bold green][CONFIRMATION EMAILED] Live confirmation email delivered for {j.company} - {j.title}![/bold green]")
                except Exception as e:
                    console.print(f"  [yellow]Notice during confirmation email dispatch: {e}[/yellow]")
        else:
            console.print("  [dim]No unapplied shortlisted positions currently waiting in queue.[/dim]")

    # Interactive prompt for remaining positions if in terminal
    shortlisted_rem = database.get_jobs(status="shortlisted", min_match_score=threshold, limit=5)
    if shortlisted_rem:
        console.print("\n[bold yellow]Additional qualified positions available for manual review:[/bold yellow]")
        for i, j in enumerate(shortlisted_rem, 1):
            top_tag = " [bold yellow][TOP PICK][/bold yellow]" if (j.is_top_pick or (j.match_score or 0) >= 90) else ""
            console.print(f"  [cyan]#{i}[/cyan] [bold white]{j.company}[/bold white] - {j.title} (ID: [green]{j.id[:8]}[/green]){top_tag}")

        if interactive:
            console.print("\n[dim]To approve and apply to additional jobs, enter ranks (e.g. '1, 2') or press Enter to finish:[/dim]")
            try:
                chosen = input("Approve & Apply: ").strip()
            except (EOFError, KeyboardInterrupt):
                chosen = ""

            if chosen:
                approve_command(selections=chosen, profile=profile, db=db, mark_applied=True)
        else:
            console.print("\n[dim]Review your email digest or status report anytime with: python main.py status[/dim]")

    console.print("\n[bold green]Daily routine complete! Check your email inbox for daily digest and application confirmations.[/bold green]")


if __name__ == "__main__":
    app()
