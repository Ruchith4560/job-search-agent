"""Master profile builder that merges GitHub and LinkedIn data with source tracking."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.ingest.github import GitHubProfileData, GitHubRepo
from agent.ingest.linkedin import LinkedInExportData, LinkedInParser
from agent.llm import ClaudeClient, LLMError
from agent.profile.schema import (
    AchievementItem,
    CertificationItem,
    ConflictItem,
    EducationItem,
    ExperienceItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)

logger = logging.getLogger(__name__)

# Known skill taxonomy for deterministic categorization
CATEGORIES = {
    "Languages": {
        "python", "java", "core java", "typescript", "javascript", "sql", "c", "c++",
        "c (programming language)", "c#", "go", "golang", "rust", "kotlin", "ruby",
        "php", "html", "html5", "css", "r", "scala", "dart", "shell", "bash"
    },
    "Frameworks & Libraries": {
        "spring boot", "spring", "react", "react.js", "react 18", "fastapi", "django", "flask",
        "express", "express.js", "node.js", "nodejs", "next.js", "nextjs", "vite", "tailwind css",
        "tailwind", "bootstrap", "pydantic", "sqlalchemy", "hibernate", "redux", "vue", "angular"
    },
    "Databases & Cloud": {
        "postgresql", "postgres", "mysql", "mongodb", "redis", "sqlite", "docker", "kubernetes",
        "aws", "gcp", "azure", "google cloud", "terraform", "firebase", "elasticsearch", "render"
    },
    "Developer Tools & Practices": {
        "git", "github", "dockerfile", "rest api", "rest apis", "restful apis", "microservices",
        "ci/cd", "postman", "linux", "jira", "agile", "pytest", "unit testing", "system design",
        "sdlc", "software development life cycle (sdlc)", "data structures", "algorithms"
    },
}


def normalize_skill_name(name: str) -> str:
    """Normalize skill name variations (e.g. 'Python (Programming Language)' -> 'Python')."""
    n = name.strip()
    if re.match(r"^Python\s*\(.*?\)$", n, re.I):
        return "Python"
    if re.match(r"^Cascading Style Sheets\s*\(CSS\)$", n, re.I):
        return "CSS"
    if n.lower() == "dockerfile":
        return "Docker"
    return n


def categorize_skill(skill_name: str) -> str:
    """Assign a categorical group to a technical skill based on known taxonomy."""
    lower = skill_name.strip().lower()
    for category, skills_set in CATEGORIES.items():
        if lower in skills_set:
            return category
        # Partial match checks
        for s in skills_set:
            if s == lower or f" {s} " in f" {lower} ":
                return category

    return "Specialized & Domain Skills"


def detect_stack_from_readme(readme_text: str) -> List[str]:
    """Scan README text for well-known frameworks and tools."""
    if not readme_text:
        return []

    detected: Set[str] = set()
    keywords = [
        "React", "TypeScript", "Tailwind CSS", "Spring Boot", "FastAPI",
        "PostgreSQL", "Docker", "Java", "Python", "Vite", "MongoDB",
        "Express", "Node.js", "Next.js", "Redis", "REST API", "SQL"
    ]
    for kw in keywords:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, readme_text, re.IGNORECASE):
            detected.add(kw)
    return sorted(list(detected))


class ProfileBuilder:
    """Builds and normalizes master_profile.json from GitHub and LinkedIn inputs."""

    def __init__(self, claude_client: Optional[ClaudeClient] = None) -> None:
        """Initialize profile builder.

        Args:
            claude_client: Optional ClaudeClient for LLM-assisted normalization.
        """
        self.claude_client = claude_client

    def _merge_personal_info(
        self,
        github_data: Optional[GitHubProfileData],
        linkedin_data: Optional[LinkedInExportData],
    ) -> PersonalInfo:
        """Synthesize contact and profile links from both sources."""
        from agent.config import load_config
        cfg = load_config()
        name = cfg.student_profile.name or "Ruchith Macha"
        headline = "Computer Science & Engineering Student | Full-Stack & AI Systems Developer"
        location = "Hyderabad, Telangana, India"
        email = cfg.student_profile.email or "macharuchith1@gmail.com"
        phone = "+91 6305239230"
        links: Dict[str, str] = {
            "github": f"https://github.com/{github_data.username}" if github_data else "https://github.com/Ruchith4560",
            "linkedin": "https://linkedin.com/in/ruchith-macha",
        }

        if linkedin_data and linkedin_data.profile:
            lp = linkedin_data.profile
            first = lp.first_name or ""
            last = lp.last_name or ""
            full = f"{first} {last}".strip()
            if full and full != "Candidate":
                name = full
            if lp.headline:
                headline = lp.headline
            if lp.geo_location:
                location = lp.geo_location
            if lp.email:
                email = lp.email
            if lp.phone:
                phone = lp.phone
            if getattr(lp, "linkedin_url", None):
                links["linkedin"] = getattr(lp, "linkedin_url")

        return PersonalInfo(
            name=name,
            headline=headline,
            location=location,
            email=email,
            phone=phone,
            links=links,
        )

    def _merge_projects(
        self,
        github_data: Optional[GitHubProfileData],
        linkedin_data: Optional[LinkedInExportData],
    ) -> List[ProjectItem]:
        """Convert GitHub repositories and LinkedIn project entries into ProjectItems."""
        projects: List[ProjectItem] = []
        # Map normalized key -> ProjectItem index
        norm_map: Dict[str, int] = {}

        def norm_key(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", s.lower())

        if github_data:
            for repo in github_data.repos:
                stack_set: Set[str] = set()
                if repo.primary_language:
                    stack_set.add(repo.primary_language)
                for lang in repo.languages.keys():
                    if lang.lower() != "dockerfile":
                        stack_set.add(lang)
                    else:
                        stack_set.add("Docker")
                for topic in repo.topics:
                    stack_set.add(topic.title())

                if repo.raw_readme:
                    detected_extra = detect_stack_from_readme(repo.raw_readme)
                    stack_set.update(detected_extra)

                highlights: List[AchievementItem] = []
                if repo.readme_summary:
                    highlights.append(
                        AchievementItem(text=repo.readme_summary, source="github")
                    )
                elif repo.description:
                    highlights.append(
                        AchievementItem(text=repo.description, source="github")
                    )

                project = ProjectItem(
                    name=repo.name,
                    url=repo.html_url,
                    stack=sorted(list(stack_set)),
                    description=repo.description or repo.readme_summary,
                    highlights=highlights,
                    stars=repo.stars,
                    source="github",
                )
                norm_map[norm_key(repo.name)] = len(projects)
                projects.append(project)

        if linkedin_data:
            for p in linkedin_data.projects:
                nk = norm_key(p.title)
                stack_tags: List[str] = []
                bullets: List[AchievementItem] = []

                if p.description:
                    if "•" in p.description:
                        parts = p.description.split("•")
                        # First part often lists tech stack tags: React.js, FastAPI, etc.
                        for tag in parts[0].split(","):
                            cleaned_tag = tag.strip()
                            if cleaned_tag and len(cleaned_tag) < 30:
                                stack_tags.append(cleaned_tag)
                        for b in parts[1:]:
                            cleaned_b = b.strip()
                            if cleaned_b:
                                bullets.append(AchievementItem(text=cleaned_b, source="linkedin"))
                    else:
                        for line in p.description.splitlines():
                            cleaned_line = line.strip().lstrip("-*•> ")
                            if cleaned_line:
                                bullets.append(AchievementItem(text=cleaned_line, source="linkedin"))

                if nk in norm_map:
                    # Enrich existing GitHub project with LinkedIn details
                    existing = projects[norm_map[nk]]
                    existing.name = p.title  # Use cleaner title from LinkedIn
                    existing.stack = sorted(list(set(existing.stack + stack_tags)))
                    # Prepend the detailed LinkedIn achievement bullets
                    existing.highlights = bullets + existing.highlights
                    if p.description and not existing.description:
                        existing.description = p.description
                else:
                    proj = ProjectItem(
                        name=p.title,
                        url=p.url,
                        stack=stack_tags,
                        description=p.description,
                        highlights=bullets,
                        source="linkedin",
                    )
                    norm_map[nk] = len(projects)
                    projects.append(proj)

        return projects

    def _merge_experience(
        self,
        linkedin_data: Optional[LinkedInExportData],
    ) -> List[ExperienceItem]:
        """Convert LinkedIn position records into ExperienceItems."""
        experience: List[ExperienceItem] = []
        if linkedin_data:
            for pos in linkedin_data.positions:
                achievements: List[AchievementItem] = []
                if pos.description:
                    if "•" in pos.description:
                        for b in pos.description.split("•"):
                            cleaned = b.strip()
                            if cleaned:
                                achievements.append(
                                    AchievementItem(text=cleaned, source="linkedin")
                                )
                    else:
                        for line in pos.description.splitlines():
                            cleaned = line.strip().lstrip("-*•> ")
                            if cleaned:
                                achievements.append(
                                    AchievementItem(text=cleaned, source="linkedin")
                                )

                is_current = not bool(pos.finished_on)
                item = ExperienceItem(
                    company=pos.company_name,
                    title=pos.title,
                    location=pos.location,
                    start_date=pos.started_on,
                    end_date=pos.finished_on,
                    is_current=is_current,
                    achievements=achievements,
                    source="linkedin",
                )
                experience.append(item)

        if not experience:
            experience.append(
                ExperienceItem(
                    company="Alfido Tech",
                    title="MERN Stack Web Development Intern",
                    location="Remote",
                    start_date="2024",
                    end_date="2024",
                    is_current=False,
                    achievements=[
                        AchievementItem(
                            text="Developed production-ready RESTful APIs in Node.js and Express with MongoDB Mongoose ODM, implementing secure JWT authentication and bcrypt password hashing.",
                            metrics="Built full CRUD API & auth system",
                            source="manual",
                        ),
                        AchievementItem(
                            text="Engineered responsive React single-page applications with dynamic state management, React Router navigation, input validation, and real-time API integrations.",
                            metrics="100% responsive SPA with complete CRUD operations",
                            source="manual",
                        ),
                    ],
                    source="manual",
                )
            )

        return experience

    def _merge_education(
        self,
        linkedin_data: Optional[LinkedInExportData],
    ) -> List[EducationItem]:
        """Convert LinkedIn education records into EducationItems."""
        education: List[EducationItem] = []
        if linkedin_data:
            for edu in linkedin_data.education:
                item = EducationItem(
                    school=edu.school_name,
                    degree=edu.degree_name,
                    start_date=edu.start_date,
                    end_date=edu.end_date,
                    notes=edu.notes or edu.activities,
                    source="linkedin",
                )
                education.append(item)

        if not education:
            education.append(
                EducationItem(
                    school="Anurag University",
                    degree="Bachelor of Technology (B.Tech)",
                    field_of_study="Computer Science and Engineering",
                    start_date="2024",
                    end_date="2028",
                    notes="CGPA: 9.05 / 10 | Relevant Coursework: Data Structures & Algorithms, Object-Oriented Programming, Database Management Systems, Operating Systems, Computer Networks",
                    source="manual",
                )
            )

        return education

    def _merge_certifications(
        self,
        linkedin_data: Optional[LinkedInExportData],
    ) -> List[CertificationItem]:
        """Convert LinkedIn certifications into CertificationItems."""
        certs: List[CertificationItem] = []
        if not linkedin_data:
            return certs

        for c in linkedin_data.certifications:
            item = CertificationItem(
                name=c.name,
                authority=c.authority,
                url=c.url,
                start_date=c.started_on,
                end_date=c.finished_on,
                license_number=c.license_number,
                source="linkedin",
            )
            certs.append(item)

        return certs

    def _merge_skills(
        self,
        github_data: Optional[GitHubProfileData],
        linkedin_data: Optional[LinkedInExportData],
    ) -> List[SkillItem]:
        """Merge, deduplicate, and cross-validate skills from GitHub and LinkedIn."""
        # Key: lowercase skill name -> dict with canonical name, category, evidence list, sources set
        merged: Dict[str, Dict[str, Any]] = {}

        # 1. Ingest LinkedIn Skills
        if linkedin_data:
            for s in linkedin_data.skills:
                raw_name = normalize_skill_name(s.name)
                k = raw_name.lower()
                if k not in merged:
                    merged[k] = {
                        "name": raw_name,
                        "category": categorize_skill(raw_name),
                        "evidence": ["Listed on LinkedIn profile"],
                        "sources": {"linkedin"},
                    }
                else:
                    merged[k]["sources"].add("linkedin")

        # 2. Ingest GitHub Languages & Technologies
        if github_data:
            # Language byte counts and repo associations
            lang_stats: Dict[str, Dict[str, Any]] = {}
            for repo in github_data.repos:
                for lang, bytes_count in repo.languages.items():
                    norm_lang = normalize_skill_name(lang)
                    k = norm_lang.lower()
                    if k not in lang_stats:
                        lang_stats[k] = {"name": norm_lang, "bytes": 0, "repos": []}
                    lang_stats[k]["bytes"] += bytes_count
                    lang_stats[k]["repos"].append(repo.name)

                # Topics
                for topic in repo.topics:
                    k = topic.lower()
                    if k not in merged:
                        merged[k] = {
                            "name": topic.title(),
                            "category": categorize_skill(topic),
                            "evidence": [f"Tag in GitHub repository '{repo.name}'"],
                            "sources": {"github"},
                        }
                    else:
                        merged[k]["sources"].add("github")
                        merged[k]["evidence"].append(f"Tag in GitHub repository '{repo.name}'")

            for k, info in lang_stats.items():
                repo_list_str = ", ".join(info["repos"][:3])
                if len(info["repos"]) > 3:
                    repo_list_str += f" (+{len(info['repos']) - 3} more)"
                evidence_str = (
                    f"Used in {len(info['repos'])} GitHub repositories ({repo_list_str}) "
                    f"with {info['bytes']:,} bytes of code"
                )

                if k in merged:
                    merged[k]["sources"].add("github")
                    merged[k]["evidence"].append(evidence_str)
                else:
                    merged[k] = {
                        "name": info["name"],
                        "category": categorize_skill(info["name"]),
                        "evidence": [evidence_str],
                        "sources": {"github"},
                    }

        # 3. Construct final SkillItems
        skill_items: List[SkillItem] = []
        for info in merged.values():
            combined_evidence = "; ".join(info["evidence"])
            # Determine primary source tag
            if "linkedin" in info["sources"]:
                source_tag = "linkedin"
            else:
                source_tag = "github"

            item = SkillItem(
                name=info["name"],
                category=info["category"],
                evidence=combined_evidence,
                source=source_tag,
            )
            skill_items.append(item)

        # Sort by category and name
        skill_items.sort(key=lambda s: (s.category, s.name.lower()))
        return skill_items

    def build(
        self,
        github_data: Optional[GitHubProfileData] = None,
        linkedin_data: Optional[LinkedInExportData] = None,
    ) -> MasterProfile:
        """Construct the consolidated MasterProfile.

        Args:
            github_data: Parsed GitHub profile data.
            linkedin_data: Parsed LinkedIn export data.

        Returns:
            MasterProfile instance with fully sourced data items.
        """
        personal_info = self._merge_personal_info(github_data, linkedin_data)
        projects = self._merge_projects(github_data, linkedin_data)
        experience = self._merge_experience(linkedin_data)
        education = self._merge_education(linkedin_data)
        certifications = self._merge_certifications(linkedin_data)
        skills = self._merge_skills(github_data, linkedin_data)

        # Check for conflicts
        conflicts: List[ConflictItem] = []
        # Example check: Verify whether experience titles and projects have date discrepancies
        # Can be expanded as more sources are added

        summary = None
        if linkedin_data and linkedin_data.profile.summary:
            summary = AchievementItem(
                text=linkedin_data.profile.summary.strip(),
                source="linkedin",
            )
        elif personal_info.headline:
            summary = AchievementItem(
                text=personal_info.headline.strip(),
                source="linkedin",
            )

        profile = MasterProfile(
            personal_info=personal_info,
            summary=summary,
            skills=skills,
            experience=experience,
            projects=projects,
            education=education,
            certifications=certifications,
            conflicts=conflicts,
        )
        return profile

    def save_profile(self, profile: MasterProfile, output_path: str = "master_profile.json") -> Path:
        """Serialize MasterProfile to JSON file."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(profile.model_dump_json(indent=2))
        logger.info("Master profile successfully saved to %s", path)
        return path
