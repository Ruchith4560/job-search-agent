"""Configuration loader and schema definitions for the AI Job Application Agent."""

import os
from pathlib import Path
from typing import List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env file
load_dotenv()


class PreferencesConfig(BaseModel):
    """User preferences for job searching and profile targeting."""
    target_roles: List[str] = Field(default_factory=lambda: ["Backend Engineer", "ML Engineer"])
    experience_level: str = "2 years"
    locations: List[str] = Field(default_factory=lambda: ["Remote", "Bengaluru", "Hyderabad"])
    salary_expectation: Optional[str] = None
    core_skills: List[str] = Field(default_factory=list)
    exclude_companies: List[str] = Field(default_factory=list)
    github_username: str = "octocat"


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
    sources: List[str] = Field(default_factory=lambda: ["remotive", "remoteok", "greenhouse", "lever"])
    greenhouse_companies: List[str] = Field(
        default_factory=lambda: ["stripe", "canonical", "cloudflare", "gitlab", "discord"]
    )
    lever_companies: List[str] = Field(
        default_factory=lambda: ["palantir", "netflix", "spotify"]
    )
    max_jobs_per_source: int = 50
    allow_remote: bool = True
    exclude_keywords: List[str] = Field(
        default_factory=lambda: ["director", "vp", "vice president", "principal", "head of", "recruiter", "sales representative"]
    )


class AppConfig(BaseModel):
    """Root configuration for the application."""
    preferences: PreferencesConfig = Field(default_factory=PreferencesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    jobs: JobDiscoveryConfig = Field(default_factory=JobDiscoveryConfig)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load and parse application configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        AppConfig: Parsed configuration instance.
    """
    path = Path(config_path)
    if not path.is_file():
        # Fall back to default config if file is not found
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return AppConfig(**data)
