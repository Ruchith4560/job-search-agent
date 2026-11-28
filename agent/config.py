"""Configuration loader and schema definitions for the AI Job Search Agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env file
load_dotenv()


class StudentProfileConfig(BaseModel):
    """Student profile attributes."""
    name: str = "Ruchith Macha"
    email: str = "macharuchith1@gmail.com"
    current_status: str = "B.Tech 3rd-year student"
    college: str = "Anurag University"
    branch: str = "Computer Science and Engineering"
    graduation_year: int = 2028
    cgpa: Optional[str] = "9.05"
    github_username: str = "Ruchith4560"

    @property
    def university(self) -> str:
        return self.college


class StipendConfig(BaseModel):
    """Stipend and salary expectations."""
    min_monthly: float = 15000.0
    preferred_monthly: float = 40000.0
    full_time_min_lpa: float = 8.0


class DealBreakersConfig(BaseModel):
    """Strict elimination criteria."""
    max_experience_years: int = 1
    exclude_unpaid: bool = True
    exclude_fee_charging: bool = True


class PreferencesConfig(BaseModel):
    """User preferences for job searching and profile targeting."""
    target_roles: List[str] = Field(
        default_factory=lambda: [
            "Software Engineer Intern",
            "SDE Intern",
            "Backend Intern",
            "Full Stack Intern",
            "Graduate Engineer",
            "Associate Engineer",
            "Trainee",
        ]
    )
    job_types: List[str] = Field(default_factory=lambda: ["internship", "entry_level"])
    locations: List[str] = Field(
        default_factory=lambda: [
            "Hyderabad",
            "Bengaluru",
            "Pune",
            "Chennai",
            "Remote India",
            "Remote",
        ]
    )
    stipend: StipendConfig = Field(default_factory=StipendConfig)
    core_skills: List[str] = Field(
        default_factory=lambda: [
            "Java", "Python", "DSA", "React", "SQL", "Git",
            "Spring Boot", "FastAPI", "Docker", "Node.js", "TypeScript"
        ]
    )
    exclude_companies: List[str] = Field(default_factory=list)
    deal_breakers: DealBreakersConfig = Field(default_factory=DealBreakersConfig)
    github_username: str = "Ruchith4560"


class ScoringConfig(BaseModel):
    """Scoring and ATS thresholds."""
    min_match_threshold: int = 70
    top_pick_threshold: int = 90
    min_ats_score: int = 85


class EmailConfig(BaseModel):
    """Daily email digest notification settings."""
    recipient: str = "macharuchith1@gmail.com"
    recipient_email: Optional[str] = None
    smtp_host: str = Field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = Field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    sender_email: str = Field(default_factory=lambda: os.getenv("GMAIL_USER", "macharuchith1@gmail.com"))
    smtp_user: Optional[str] = None
    sender_password: Optional[str] = Field(default_factory=lambda: os.getenv("GMAIL_APP_PASSWORD"))
    send_email: bool = True
    enabled: Optional[bool] = None
    use_tls: bool = True

    def model_post_init(self, __context: Any) -> None:
        if not self.recipient_email:
            self.recipient_email = self.recipient
        if not self.smtp_user:
            self.smtp_user = self.sender_email
        if self.enabled is None:
            self.enabled = self.send_email


class LLMConfig(BaseModel):
    """LLM client configuration."""
    model: str = "claude-3-5-sonnet-20241022"
    temperature: float = 0.2
    max_retries: int = 3
    timeout_seconds: int = 60


class PathsConfig(BaseModel):
    """Local file and directory paths."""
    data_raw_dir: str = "data/raw"
    data_output_dir: str = "data/output"
    github_raw_file: str = "data/raw/github.json"
    linkedin_raw_file: str = "data/raw/linkedin.json"
    master_profile_file: str = "master_profile.json"
    tracker_db_file: str = "data/tracker.db"


class JobDiscoveryConfig(BaseModel):
    """Configuration for job board fetching and filtering."""
    sources: List[str] = Field(
        default_factory=lambda: [
            "linkedin",
            "internshala",
            "unstop",
            "freshersworld",
            "indian_portals",
            "enterprise_careers",
            "smartrecruiters",
            "remotive",
            "arbeitnow",
            "jobicy",
            "himalayas",
            "weworkremotely",
            "python_org",
            "greenhouse",
            "lever",
        ]
    )
    greenhouse_companies: List[str] = Field(
        default_factory=lambda: [
            "canonical",
            "cloudflare",
            "gitlab",
            "discord",
            "stripe",
            "airbnb",
            "figma",
            "elastic",
            "automattic",
            "hashicorp",
            "datadog",
            "brex",
            "reddit",
            "supabase",
            "postman",
        ]
    )
    lever_companies: List[str] = Field(
        default_factory=lambda: [
            "palantir",
            "netflix",
            "spotify",
            "vercel",
            "swiggy",
            "twitch",
            "coinbase",
            "atlassian",
            "affirm",
        ]
    )
    smartrecruiters_companies: List[str] = Field(
        default_factory=lambda: [
            "visa",
            "bosch",
            "square",
            "ubisoft",
            "epicgames",
            "ikea",
            "publicissapient",
        ]
    )
    max_jobs_per_source: int = 50
    allow_remote: bool = True
    exclude_keywords: List[str] = Field(
        default_factory=lambda: [
            "director", "vp", "vice president", "principal", "head of",
            "recruiter", "sales representative", "senior", "lead", "staff", "manager"
        ]
    )


class AutonomousApplicationConfig(BaseModel):
    """Configuration for autonomous browser job application workflow."""
    enabled: bool = True
    autonomous_mode: bool = False
    max_daily_submissions: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_SUBMITS", "10")))
    max_retry_attempts: int = 3
    min_match_threshold: int = 70
    auto_apply_min_match_score: int = 85
    supported_portals: List[str] = Field(
        default_factory=lambda: [
            "greenhouse",
            "lever",
            "smartrecruiters",
            "phenom",
            "workday",
            "generic",
        ]
    )
    dry_run: bool = False
    allow_custom_questions: bool = True
    capture_screenshots: bool = True
    delay_between_applications_seconds: int = 5


class AppConfig(BaseModel):
    """Root configuration for the application."""
    profile: StudentProfileConfig = Field(default_factory=StudentProfileConfig)
    preferences: PreferencesConfig = Field(default_factory=PreferencesConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    jobs: JobDiscoveryConfig = Field(default_factory=JobDiscoveryConfig)
    autonomous_application: AutonomousApplicationConfig = Field(default_factory=AutonomousApplicationConfig)

    @property
    def student_profile(self) -> StudentProfileConfig:
        return self.profile


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load and parse application configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        AppConfig: Parsed configuration instance.
    """
    path = Path(config_path)
    if not path.is_file():
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return AppConfig(**data)
