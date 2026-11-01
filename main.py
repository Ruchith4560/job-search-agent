"""CLI entry point for the AI Resume & Job Application Agent."""

import logging
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
import typer

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
from agent.profile.builder import ProfileBuilder
from agent.profile.schema import MasterProfile
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

    # Print success summary
    res_table = Table(title="Generated ATS Resume Files", show_header=True)
    res_table.add_column("Format", style="cyan", no_wrap=True)
    res_table.add_column("File Path", style="green")
    res_table.add_column("Description", style="white")

    res_table.add_row("PDF", str(pdf_path), "ATS-compliant, single-page print format")
    res_table.add_row("DOCX", str(docx_path), "Editable Microsoft Word document")
    res_table.add_row("HTML", str(html_path), "Semantic web preview format")

    console.print(res_table)
    console.print(
        f"[bold green]Resume successfully generated for [white]{resume_data.name}[/white]![/bold green]"
    )


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
    summary_table.add_row("ATS Resume PDF", str(target_dir / "tailored_resume.pdf"))
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
    saved_path = generator.save_markdown_report(digest_data, output_path=output)

    # Display in Rich
    from rich.markdown import Markdown

    console.print("\n")
    console.print(Markdown(digest_data["markdown"]))
    console.print(f"[bold green]Daily digest saved to: [underline]{saved_path.resolve()}[/underline][/bold green]")


@app.command("auto-apply")
def auto_apply(
    max_applications: int = typer.Option(2, "--max-apps", "-m", help="Maximum jobs to prepare and apply for per run"),
    threshold: int = typer.Option(50, "--threshold", "-t", help="Minimum match score to consider"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Use Claude LLM for deep matching and cover letters"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode (default: False for visual inspection)"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to tracker database"),
    fetch_limit: int = typer.Option(30, "--fetch-limit", help="Max fresh jobs to fetch"),
) -> None:
    """Fully automated daily application workflow: Fetches, matches, auto-tailors, and prompts for confirmation."""
    console.print("\n[bold cyan]=================================================================[/bold cyan]")
    console.print("[bold white]   AUTOMATED DAILY APPLICATION RUNNER (APPROVAL GATE ACTIVE)     [/bold white]")
    console.print("[bold cyan]=================================================================[/bold cyan]\n")

    # 1. Fetch fresh jobs
    console.print("[bold green]Step 1/4: Fetching fresh job postings from public feeds...[/bold green]")
    try:
        fetch_jobs(limit_per_source=fetch_limit, db=db)
    except Exception as e:
        console.print(f"[yellow]Warning during fetch: {e}. Using existing opportunities in database.[/yellow]")

    # 2. Semantic Matching
    console.print("\n[bold green]Step 2/4: Scoring opportunities against your Master Profile...[/bold green]")
    try:
        match_jobs(threshold=threshold, top_n=15, use_llm=use_llm, profile=profile, db=db)
    except Exception as e:
        console.print(f"[yellow]Warning during matching: {e}.[/yellow]")

    # 3. Find candidates to apply for
    database = JobDatabase(db_path=Path(db))
    eligible_jobs = database.get_jobs(status="shortlisted")
    if not eligible_jobs:
        eligible_jobs = database.get_jobs(status="tailored")

    if not eligible_jobs:
        console.print("\n[bold green]All caught up! No un-applied matching jobs above threshold. Run 'python main.py match' to inspect jobs.[/bold green]")
        return

    console.print(f"\n[bold green]Step 3/4: Found {len(eligible_jobs)} eligible shortlisted job(s). Preparing up to {max_applications}...[/bold green]")

    for idx, job in enumerate(eligible_jobs[:max_applications], 1):
        console.print(f"\n[bold cyan]-----------------------------------------------------------------[/bold cyan]")
        console.print(f"[bold white]Processing Job #{idx}: [cyan]{job.company}[/cyan] - [white]{job.title}[/white] (`{job.id[:8]}`)[/bold white]")
        console.print(f"[bold cyan]-----------------------------------------------------------------[/bold cyan]")

        # 3a. Auto-tailor resume & cover letter
        console.print(f"[dim]Tailoring resume and 3-paragraph cover letter for {job.company}...[/dim]")
        try:
            tailor(job_id=job.id, profile=profile, db=db, use_llm=use_llm)
        except Exception as e:
            console.print(f"[bold red]Tailoring failed for {job.company}:[/bold red] {e}")
            continue

        # 3b. Pre-fill form & pause at Human Approval Gate
        console.print(f"[bold green]Opening browser to pre-fill form for {job.company}...[/bold green]")
        try:
            prefill(job_id=job.id, profile=profile, db=db, headless=headless)
        except Exception as e:
            console.print(f"[bold red]Pre-fill encountered an issue:[/bold red] {e}")

    # 4. Generate refreshed Daily Digest
    console.print("\n[bold green]Step 4/4: Refreshing Daily Status Digest...[/bold green]")
    daily_digest(profile=profile, db=db)
    console.print("\n[bold green]Daily automated run complete![/bold green]")


@app.command("daily")
def run_daily_pipeline(
    threshold: int = typer.Option(50, "--threshold", "-t", help="Minimum match score (0-100) to shortlist"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Use Claude LLM for deep scoring & cover letters"),
    profile: str = typer.Option("master_profile.json", "--profile", "-p", help="Path to master profile"),
    db: str = typer.Option("data/tracker.db", "--db", "-d", help="Path to SQLite database"),
    fetch_limit: int = typer.Option(30, "--fetch-limit", help="Max jobs to fetch per source"),
) -> None:
    """Execute complete daily job search routine: Fetch -> Match & Score -> Digest -> Interactive Apply."""
    console.print("\n[bold cyan]=================================================================[/bold cyan]")
    console.print("[bold white]   AI RESUME & JOB APPLICATION AGENT: DAILY SEARCH ROUTINE       [/bold white]")
    console.print("[bold cyan]=================================================================[/bold cyan]\n")

    # Step 1: Fetch Latest Jobs
    console.print("[bold green]Step 1/3: Fetching fresh job opportunities from public feeds...[/bold green]")
    try:
        fetch_jobs(limit_per_source=fetch_limit, db=db)
    except Exception as e:
        console.print(f"[yellow]Warning during job fetch: {e}. Continuing with existing database.[/yellow]")

    # Step 2: Match and Score
    console.print("\n[bold green]Step 2/3: Semantic vector matching & scoring against your profile...[/bold green]")
    try:
        match_jobs(threshold=threshold, top_n=15, use_llm=use_llm, profile=profile, db=db)
    except Exception as e:
        console.print(f"[yellow]Warning during matching: {e}.[/yellow]")

    # Step 3: Daily Digest
    console.print("\n[bold green]Step 3/3: Generating daily search digest and action items...[/bold green]")
    daily_digest(profile=profile, db=db)

    # Step 4: Interactive Apply Prompt
    database = JobDatabase(db_path=Path(db))
    shortlisted = database.get_jobs(status="shortlisted", limit=5)

    if shortlisted:
        console.print("\n[bold yellow]Ready to apply! Top shortlisted jobs available:[/bold yellow]")
        for i, j in enumerate(shortlisted, 1):
            console.print(f"  [cyan]#{i}[/cyan] [bold white]{j.company}[/bold white] - {j.title} (ID: [green]{j.id[:8]}[/green])")

        console.print("\n[dim]To tailor and apply for any job above, enter its Job ID (or press Enter to exit):[/dim]")
        try:
            chosen_id = input("Job ID to tailor & apply: ").strip()
        except (EOFError, KeyboardInterrupt):
            chosen_id = ""

        if chosen_id:
            # Find matching full ID
            matched_job = database.get_job_by_id(chosen_id)
            if not matched_job:
                candidates = [j for j in database.get_jobs() if j.id.startswith(chosen_id.lower())]
                if candidates:
                    matched_job = candidates[0]

            if matched_job:
                console.print(f"\n[bold green]Tailoring application for {matched_job.company} - {matched_job.title}...[/bold green]")
                tailor(job_id=matched_job.id, profile=profile, db=db, use_llm=use_llm)

                try:
                    do_prefill = input("\nLaunch browser to pre-fill application now? [Y/n]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    do_prefill = "n"

                if do_prefill in ("", "y", "yes"):
                    prefill(job_id=matched_job.id, profile=profile, db=db)
            else:
                console.print(f"[yellow]Job ID '{chosen_id}' not found. You can run 'python main.py tailor <id>' anytime.[/yellow]")

    console.print("\n[bold green]Daily routine complete! Check 'data/tracker.db' or run 'python main.py status'.[/bold green]")


if __name__ == "__main__":
    app()
