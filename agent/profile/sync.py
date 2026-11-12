"""Automatic profile synchronization and continuous ATS resume optimization engine."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.config import AppConfig, load_config
from agent.ingest.github import GitHubIngester, GitHubProfileData
from agent.ingest.linkedin import LinkedInExportData, LinkedInParser
from agent.profile.builder import ProfileBuilder
from agent.profile.schema import MasterProfile
from agent.resume.ats_checker import ATSChecker, ATSScoreResult
from agent.resume.generator import ResumeGenerator
from agent.resume.render import render_docx, render_html, render_pdf
from agent.resume.schema import ResumeData

logger = logging.getLogger(__name__)


class ProfileSyncManager:
    """Monitors GitHub repositories and LinkedIn data, automatically updating

    master_profile.json and compiling optimized ATS resumes (>85% score).
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        token: Optional[str] = None,
    ) -> None:
        self.config = config or load_config()
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.ingester = GitHubIngester(token=self.token)
        self.parser = LinkedInParser()
        self.builder = ProfileBuilder()
        self.generator = ResumeGenerator()
        self.ats_checker = ATSChecker(min_passing_score=self.config.scoring.min_ats_score)

    def check_for_updates(self, username: Optional[str] = None) -> Dict[str, Any]:
        """Check whether GitHub or LinkedIn contains newer projects or data than master_profile.json."""
        target_username = username or self.config.preferences.github_username
        master_path = Path(self.config.paths.master_profile_file)
        github_raw_path = Path(self.config.paths.github_raw_file)
        linkedin_raw_dir = Path("data/raw/linkedin")
        linkedin_raw_json = Path(self.config.paths.linkedin_raw_file)

        existing_repos: Dict[str, str] = {}
        master_mtime = master_path.stat().st_mtime if master_path.is_file() else 0

        # Read existing repos from current master_profile.json
        if master_path.is_file():
            try:
                prof = MasterProfile.model_validate_json(master_path.read_text(encoding="utf-8"))
                for p in prof.projects:
                    existing_repos[p.name.lower()] = p.url or ""
            except Exception as e:
                logger.warning(f"Could not read master profile for comparison: {e}")

        # Check GitHub API
        new_repos: List[str] = []
        updated_repos: List[str] = []

        try:
            live_data = self.ingester.fetch_user_repos(
                username=target_username,
                limit=30,
                summarize_readmes=False,
            )
            for r in live_data.repos:
                r_name = r.name.lower()
                if r_name not in existing_repos:
                    new_repos.append(r.name)
                else:
                    # Check if updated recently
                    r_updated_iso = r.updated_at
                    try:
                        r_dt = datetime.fromisoformat(r_updated_iso.replace("Z", "+00:00"))
                        if master_mtime > 0 and r_dt.timestamp() > master_mtime:
                            updated_repos.append(r.name)
                    except Exception:
                        pass
        except Exception as e:
            logger.info(f"GitHub API check unavailable or rate limited ({e}). Checking local files.")

        # Check LinkedIn modifications
        linkedin_changed = False
        if linkedin_raw_dir.is_dir():
            for f in linkedin_raw_dir.glob("*.csv"):
                if f.stat().st_mtime > master_mtime:
                    linkedin_changed = True
                    break
        elif linkedin_raw_json.is_file() and linkedin_raw_json.stat().st_mtime > master_mtime:
            linkedin_changed = True

        has_changes = bool(new_repos or updated_repos or linkedin_changed or not master_path.is_file())

        return {
            "has_changes": has_changes,
            "new_repos": new_repos,
            "updated_repos": updated_repos,
            "linkedin_changed": linkedin_changed,
            "master_exists": master_path.is_file(),
            "target_username": target_username,
        }

    def sync_and_optimize(
        self,
        force: bool = False,
        output_dir: str = "data/output",
        use_llm: bool = False,
    ) -> Dict[str, Any]:
        """Fetch latest GitHub/LinkedIn items, update master profile, and re-compile

        an ATS-optimized resume (>85% score).
        """
        check = self.check_for_updates()
        if not check["has_changes"] and not force and check["master_exists"]:
            logger.info("Master profile is already up-to-date with GitHub and LinkedIn.")
            # Verify current master resume ATS score
            master_prof = MasterProfile.model_validate_json(
                Path(self.config.paths.master_profile_file).read_text(encoding="utf-8")
            )
            resume_data = self.generator.generate(master_prof)
            resume_data, ats_res = self.ats_checker.optimize_and_verify(resume_data, None, master_prof)
            return {
                "status": "up_to_date",
                "message": "No new projects or LinkedIn updates detected. Profile is current.",
                "ats_score": ats_res.overall_score,
                "profile_version": master_prof.version,
            }

        logger.info(
            f"Synchronizing profile: {len(check['new_repos'])} new repo(s), "
            f"{len(check['updated_repos'])} updated repo(s), "
            f"LinkedIn updated={check['linkedin_changed']}."
        )

        # 1. Ingest GitHub
        target_username = check["target_username"]
        gh_data: Optional[GitHubProfileData] = None
        try:
            gh_data = self.ingester.fetch_user_repos(
                username=target_username,
                limit=30,
                summarize_readmes=True,
            )
            self.ingester.save_to_json(gh_data, self.config.paths.github_raw_file)
            logger.info(f"Ingested {len(gh_data.repos)} repositories for {target_username}.")
        except Exception as e:
            logger.warning(f"GitHub ingestion issue: {e}. Falling back to cached github.json.")
            gh_file = Path(self.config.paths.github_raw_file)
            if gh_file.is_file():
                try:
                    gh_data = GitHubProfileData.model_validate_json(gh_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

        # 2. Ingest LinkedIn
        lk_data: Optional[LinkedInExportData] = None
        lk_dir = Path("data/raw/linkedin")
        lk_json = Path(self.config.paths.linkedin_raw_file)
        if lk_dir.is_dir() and any(lk_dir.glob("*.csv")):
            try:
                lk_data = self.parser.parse(lk_dir)
            except Exception as e:
                logger.warning(f"Could not parse LinkedIn directory: {e}")
        elif lk_json.is_file():
            try:
                lk_data = LinkedInExportData.model_validate_json(lk_json.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not parse LinkedIn JSON: {e}")

        # 3. Merge into Master Profile
        master = self.builder.build(github_data=gh_data, linkedin_data=lk_data)

        # Increment version and update timestamp
        now_iso = datetime.now(timezone.utc).isoformat()
        master.last_updated = now_iso
        try:
            old_ver = float(master.version)
            master.version = f"{old_ver + 0.1:.1f}"
        except Exception:
            master.version = "1.1"

        saved_master_path = self.builder.save_profile(master, self.config.paths.master_profile_file)
        logger.info(f"Saved synchronized master profile v{master.version} to {saved_master_path}")

        # 4. Generate Master Resume
        resume_data = self.generator.generate(profile=master, max_projects=4, use_llm=use_llm)

        # 5. Enforce ATS Optimization Pass (> 85% Score Guaranteed)
        resume_data, ats_result = self.ats_checker.optimize_and_verify(
            resume=resume_data,
            job=None,
            profile=master,
        )

        # 6. Render Master Resume Files
        target_out = Path(output_dir)
        target_out.mkdir(parents=True, exist_ok=True)

        clean_name = master.personal_info.name.replace(" ", "") if master.personal_info.name else "RuchithMacha"
        named_pdf_path = target_out / f"{clean_name}_Master_Resume.pdf"
        named_docx_path = target_out / f"{clean_name}_Master_Resume.docx"
        base_pdf_path = target_out / "resume.pdf"
        base_docx_path = target_out / "resume.docx"
        base_html_path = target_out / "resume.html"

        render_pdf(resume_data, str(named_pdf_path))
        render_pdf(resume_data, str(base_pdf_path))
        render_docx(resume_data, str(named_docx_path))
        render_docx(resume_data, str(base_docx_path))

        html_str = render_html(resume_data)
        base_html_path.write_text(html_str, encoding="utf-8")

        logger.info(
            f"Master resume re-compiled and optimized! ATS Score: {ats_result.overall_score}% "
            f"(Target >85% met: {ats_result.overall_score >= 85})."
        )

        return {
            "status": "synchronized",
            "profile_version": master.version,
            "last_updated": now_iso,
            "total_projects": len(master.projects),
            "new_projects": check["new_repos"],
            "updated_projects": check["updated_repos"],
            "total_skills": len(master.skills),
            "ats_score": ats_result.overall_score,
            "is_ats_compliant": ats_result.overall_score >= 85,
            "named_pdf_path": str(named_pdf_path.resolve()),
            "base_pdf_path": str(base_pdf_path.resolve()),
        }
