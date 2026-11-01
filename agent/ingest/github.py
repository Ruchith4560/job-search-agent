"""GitHub public repository ingestion module."""

import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from github import Auth, Github, GithubRetry
from github.GithubException import GithubException, RateLimitExceededException, RateLimitExceededExceedsMaxWait
from pydantic import BaseModel, Field

from agent.llm import ClaudeClient, LLMError

logger = logging.getLogger(__name__)


class GitHubRepo(BaseModel):
    """Schema for a single ingested GitHub repository."""
    name: str
    full_name: str
    description: Optional[str] = None
    html_url: str
    stars: int = 0
    forks: int = 0
    primary_language: Optional[str] = None
    languages: Dict[str, int] = Field(default_factory=dict)
    topics: List[str] = Field(default_factory=list)
    last_activity: str
    created_at: str
    updated_at: str
    is_fork: bool = False
    is_archived: bool = False
    readme_summary: Optional[str] = None
    raw_readme: Optional[str] = None


class GitHubProfileData(BaseModel):
    """Container schema for all ingested GitHub repository data."""
    username: str
    fetched_at: str
    total_repos: int
    repos: List[GitHubRepo] = Field(default_factory=list)


def extract_fallback_summary(readme_text: str, max_length: int = 300) -> str:
    """Extract a quick fallback summary from the beginning of a README when LLM is unavailable.

    Args:
        readme_text: Raw markdown text.
        max_length: Maximum character length for summary.

    Returns:
        Cleaned plain text summary.
    """
    if not readme_text:
        return ""

    lines = readme_text.splitlines()
    summary_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip empty lines, main title headers (# Name), images, badges, and license notes
        if not stripped:
            continue
        if stripped.startswith("# ") or stripped.startswith("![") or "[![" in stripped:
            continue
        if stripped.lower().startswith("license"):
            continue
        # Remove markdown links [text](url) -> text
        cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", stripped)
        # Remove bold/italics
        cleaned = re.sub(r"[*_`]", "", cleaned)
        summary_lines.append(cleaned)
        if len(" ".join(summary_lines)) >= max_length:
            break

    result = " ".join(summary_lines).strip()
    if len(result) > max_length:
        result = result[:max_length].rsplit(" ", 1)[0] + "..."
    return result


class GitHubIngester:
    """Fetches public repositories and metadata for a specified GitHub user."""

    def __init__(
        self,
        token: Optional[str] = None,
        claude_client: Optional[ClaudeClient] = None,
    ) -> None:
        """Initialize the GitHub Ingester.

        Args:
            token: Optional GitHub Personal Access Token. If omitted, checks GITHUB_TOKEN in env.
            claude_client: Optional ClaudeClient instance for generating README summaries.
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.claude_client = claude_client

        # Configure custom retry that does NOT sleep indefinitely on 403 Rate Limits
        retry_policy = GithubRetry(
            total=2,
            backoff_factor=0.5,
            max_rate_limit_wait=5.0,
            status_forcelist=[500, 502, 503, 504],
        )

        if self.token:
            auth = Auth.Token(self.token)
            self.gh = Github(auth=auth, retry=retry_policy)
            logger.info("GitHub client initialized with token authentication.")
        else:
            self.gh = Github(retry=retry_policy)
            logger.warning(
                "GitHub client initialized without token. Unauthenticated requests are subject to "
                "a strict rate limit of 60 requests per hour. Set GITHUB_TOKEN in .env for 5,000 req/hr."
            )

    def _fetch_readme(self, repo: Any) -> Optional[str]:
        """Fetch and decode the default branch README file for a repository.

        Args:
            repo: PyGithub Repository instance.

        Returns:
            Decoded string content of README, or None if not found.
        """
        try:
            readme_file = repo.get_readme()
            if readme_file.encoding == "base64":
                content = base64.b64decode(readme_file.content).decode("utf-8", errors="replace")
                return content
            return readme_file.decoded_content.decode("utf-8", errors="replace")
        except GithubException as e:
            if e.status == 404:
                logger.debug("No README found for %s", repo.full_name)
                return None
            logger.warning("Error fetching README for %s: %s", repo.full_name, e)
            return None
        except Exception as e:
            logger.warning("Unexpected error reading README for %s: %s", repo.full_name, e)
            return None

    def _summarize_readme(self, readme_text: str, repo_name: str) -> Optional[str]:
        """Generate a summary of the README using Claude if available, falling back to heuristic extraction."""
        if not readme_text:
            return None

        if self.claude_client:
            try:
                return self.claude_client.summarize_readme(readme_text)
            except LLMError as e:
                logger.warning("LLM README summarization failed for %s (%s). Using fallback summary.", repo_name, e)

        return extract_fallback_summary(readme_text)

    def fetch_user_repos(
        self,
        username: str,
        include_forks: bool = False,
        limit: Optional[int] = None,
        summarize_readmes: bool = True,
    ) -> GitHubProfileData:
        """Fetch all public repositories for a given GitHub username.

        Args:
            username: The GitHub account username.
            include_forks: Whether to include forked repositories. Defaults to False.
            limit: Maximum number of repositories to process. None for all.
            summarize_readmes: Whether to fetch and summarize repository README files.

        Returns:
            GitHubProfileData containing validated repository items.
        """
        logger.info("Fetching public repositories for user '%s'...", username)
        try:
            user = self.gh.get_user(username)
            repos = user.get_repos(type="public", sort="pushed", direction="desc")
        except (RateLimitExceededException, RateLimitExceededExceedsMaxWait, GithubException) as e:
            if isinstance(e, (RateLimitExceededException, RateLimitExceededExceedsMaxWait)) or (hasattr(e, "status") and e.status == 403):
                logger.warning(
                    "GitHub API rate limit reached before fetching repositories for user '%s'. "
                    "Tip: Add GITHUB_TOKEN in your .env file to enable 5,000 requests/hour.",
                    username,
                )
                return GitHubProfileData(
                    username=username,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    total_repos=0,
                    repos=[],
                )
            logger.error("GitHub API error accessing user '%s': %s", username, e)
            raise

        ingested_repos: List[GitHubRepo] = []
        count = 0

        try:
            for repo in repos:
                if limit is not None and count >= limit:
                    break

                if repo.fork and not include_forks:
                    continue

                count += 1
                logger.info("[%d] Ingesting repository: %s", count, repo.name)

                # Languages
                languages = {}
                try:
                    raw_languages = repo.get_languages() or {}
                    languages = {
                        k: int(v)
                        for k, v in raw_languages.items()
                        if k.lower() != "url" and (isinstance(v, int) or (isinstance(v, str) and v.isdigit()))
                    }
                except RateLimitExceededException:
                    logger.warning("Rate limit hit while fetching languages for %s", repo.name)
                except Exception as e:
                    logger.debug("Could not fetch languages for %s: %s", repo.name, e)

                # Topics
                topics = []
                try:
                    topics = repo.get_topics()
                except RateLimitExceededException:
                    logger.warning("Rate limit hit while fetching topics for %s", repo.name)
                except Exception as e:
                    logger.debug("Could not fetch topics for %s: %s", repo.name, e)

                # README and summary
                readme_content = None
                readme_summary = None
                if summarize_readmes:
                    readme_content = self._fetch_readme(repo)
                    if readme_content:
                        readme_summary = self._summarize_readme(readme_content, repo.name)

                last_activity = (repo.pushed_at or repo.updated_at).isoformat() if (repo.pushed_at or repo.updated_at) else ""
                created_at = repo.created_at.isoformat() if repo.created_at else ""
                updated_at = repo.updated_at.isoformat() if repo.updated_at else ""

                repo_data = GitHubRepo(
                    name=repo.name,
                    full_name=repo.full_name,
                    description=repo.description,
                    html_url=repo.html_url,
                    stars=repo.stargazers_count,
                    forks=repo.forks_count,
                    primary_language=repo.language,
                    languages=languages,
                    topics=topics,
                    last_activity=last_activity,
                    created_at=created_at,
                    updated_at=updated_at,
                    is_fork=repo.fork,
                    is_archived=repo.archived,
                    readme_summary=readme_summary,
                    raw_readme=readme_content[:1000] if readme_content else None,
                )
                ingested_repos.append(repo_data)
        except (RateLimitExceededException, RateLimitExceededExceedsMaxWait, GithubException) as e:
            if isinstance(e, (RateLimitExceededException, RateLimitExceededExceedsMaxWait)) or (hasattr(e, "status") and e.status == 403):
                logger.warning(
                    "GitHub API rate limit exceeded. Saving the %d repositories fetched so far. "
                    "Tip: Set GITHUB_TOKEN in your .env file to get 5,000 requests per hour.",
                    len(ingested_repos),
                )
            else:
                logger.error("GitHub API error: %s", e)
                if not ingested_repos:
                    raise

        result = GitHubProfileData(
            username=username,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            total_repos=len(ingested_repos),
            repos=ingested_repos,
        )
        return result

    def save_to_json(self, data: GitHubProfileData, output_path: str = "data/raw/github.json") -> Path:
        """Serialize and save ingested GitHub data to a JSON file.

        Args:
            data: GitHubProfileData instance.
            output_path: Target path for the JSON file.

        Returns:
            Path object of the written file.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(data.model_dump_json(indent=2))

        logger.info("Successfully saved %d repositories to %s", len(data.repos), path)
        return path
