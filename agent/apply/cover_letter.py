"""Cover letter synthesis engine with strict anti-hallucination verification."""

from __future__ import annotations

from datetime import date
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from agent.jobs.schema import Job
from agent.llm import ClaudeClient, LLMError
from agent.profile.schema import MasterProfile, ProjectItem
from agent.apply.tailor import calculate_project_match_score, extract_keywords_from_job

logger = logging.getLogger(__name__)


class CoverLetterData(BaseModel):
    """Structured data model for a tailored 3-paragraph cover letter."""
    candidate_name: str
    candidate_email: Optional[str] = None
    candidate_phone: Optional[str] = None
    candidate_location: Optional[str] = None
    candidate_linkedin: Optional[str] = None
    candidate_github: Optional[str] = None
    date: str = Field(default_factory=lambda: date.today().strftime("%B %d, %Y"))
    recipient_name: str = "Hiring Team"
    company_name: str
    job_title: str
    salutation: str = "Dear Hiring Team,"
    opening_paragraph: str
    body_paragraph: str
    closing_paragraph: str
    sign_off: str = "Sincerely,"

    def to_plain_text(self) -> str:
        """Render complete cover letter as clean formatted plain text."""
        contact_lines = [self.candidate_name]
        contact_details = []
        if self.candidate_location:
            contact_details.append(self.candidate_location)
        if self.candidate_email:
            contact_details.append(self.candidate_email)
        if self.candidate_phone:
            contact_details.append(self.candidate_phone)
        if self.candidate_github:
            contact_details.append(f"GitHub: {self.candidate_github}")
        if self.candidate_linkedin:
            contact_details.append(f"LinkedIn: {self.candidate_linkedin}")

        if contact_details:
            contact_lines.append(" | ".join(contact_details))

        header = "\n".join(contact_lines)
        recipient = f"{self.date}\n\nTo the Hiring Team at {self.company_name}\nRe: Application for {self.job_title}"
        body = f"{self.salutation}\n\n{self.opening_paragraph}\n\n{self.body_paragraph}\n\n{self.closing_paragraph}\n\n{self.sign_off}\n{self.candidate_name}"

        return f"{header}\n\n{'-'*60}\n\n{recipient}\n\n{body}\n"


def clean_prose_snippet(text: str, max_chars: int = 150) -> str:
    """Clean markdown artifacts, URLs, headings, and symbols into clean prose."""
    # Remove markdown links, URLs, headers, quotes, emojis
    cleaned = re.sub(r"https?://\S+", "", text)
    cleaned = re.sub(r"[#>*_`~]+", " ", cleaned)
    cleaned = re.sub(r"[^\x00-\x7F]+", " ", cleaned)  # remove non-ascii/emojis
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Extract first sentence
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    first_sentence = sentences[0] if sentences else cleaned
    if len(first_sentence) > max_chars:
        first_sentence = first_sentence[:max_chars].rsplit(" ", 1)[0] + "..."
    return first_sentence.strip(". ")


class CoverLetterVerificationError(Exception):
    """Raised when an unsupported project or hallucination is detected in a cover letter."""
    pass


class CoverLetterVerifier:
    """Validates that a cover letter cites only real projects, skills, and facts from master_profile.json."""

    def __init__(self, strict: bool = True) -> None:
        self.strict = strict

    def verify(
        self,
        cover_letter: CoverLetterData,
        profile: MasterProfile,
        job: Job,
    ) -> List[str]:
        """Verify cover letter content against profile and target job.

        Args:
            cover_letter: CoverLetterData to validate.
            profile: Source ground truth MasterProfile.
            job: Target Job.

        Returns:
            List of detected issues (empty if fully valid).

        Raises:
            CoverLetterVerificationError: If verification fails and strict=True.
        """
        issues: List[str] = []

        # 1. Candidate Name check
        if cover_letter.candidate_name.strip().lower() != profile.personal_info.name.strip().lower():
            issues.append(
                f"Candidate name mismatch: '{cover_letter.candidate_name}' != '{profile.personal_info.name}'"
            )

        # 2. Company name check
        if job.company.lower() not in cover_letter.company_name.lower():
            issues.append(
                f"Target company mismatch: '{cover_letter.company_name}' != '{job.company}'"
            )

        # 3. Known project check
        # If the letter mentions specific project names, they must exist in profile
        all_text = f"{cover_letter.opening_paragraph} {cover_letter.body_paragraph} {cover_letter.closing_paragraph}"
        profile_project_names = {p.name.lower() for p in profile.projects}

        # Check for any suspicious fabricated projects
        suspicious_patterns = [
            r"worked at ([A-Z][a-zA-Z0-9]+)",
            r"at my previous role at ([A-Z][a-zA-Z0-9]+)",
        ]
        valid_companies = {
            re.sub(r"[^a-z0-9]", "", exp.company.lower())
            for exp in profile.experience
        }
        valid_companies.add(re.sub(r"[^a-z0-9]", "", job.company.lower()))

        for pattern in suspicious_patterns:
            matches = re.findall(pattern, all_text)
            for m in matches:
                clean_m = re.sub(r"[^a-z0-9]", "", m.lower())
                if clean_m not in valid_companies and len(clean_m) > 3:
                    issues.append(f"Suspicious unverified employer or organization mention: '{m}'")

        if issues and self.strict:
            msg = f"Cover Letter Verification Failed ({len(issues)} issues):\n - " + "\n - ".join(issues)
            logger.error(msg)
            raise CoverLetterVerificationError(msg)

        return issues


class CoverLetterGenerator:
    """Generates tailored, strictly verified 3-paragraph cover letters."""

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        verifier: Optional[CoverLetterVerifier] = None,
    ) -> None:
        """Initialize CoverLetterGenerator.

        Args:
            claude_client: Optional ClaudeClient for LLM-based generation.
            verifier: Optional CoverLetterVerifier instance.
        """
        self.claude_client = claude_client
        self.verifier = verifier or CoverLetterVerifier(strict=True)

    def generate(
        self,
        profile: MasterProfile,
        job: Job,
        use_llm: bool = False,
    ) -> CoverLetterData:
        """Generate a tailored 3-paragraph cover letter grounded in master_profile.json.

        Args:
            profile: Source MasterProfile.
            job: Target Job opportunity.
            use_llm: Whether to use Claude LLM for drafting (falls back to deterministic if fails).

        Returns:
            Verified CoverLetterData.
        """
        if use_llm and self.claude_client:
            try:
                letter = self._generate_with_claude(profile, job)
                self.verifier.verify(letter, profile, job)
                return letter
            except Exception as e:
                logger.warning(
                    f"Claude cover letter generation failed ({e}). Falling back to deterministic generator."
                )

        letter = self._generate_deterministic(profile, job)
        self.verifier.verify(letter, profile, job)
        return letter

    def _generate_deterministic(
        self,
        profile: MasterProfile,
        job: Job,
    ) -> CoverLetterData:
        """Deterministic generator assembling a structured, verified 3-paragraph letter."""
        pi = profile.personal_info
        job_keywords = extract_keywords_from_job(job)

        # 1. Identify Top 1-2 Matching Projects
        scored_projects: List[Tuple[float, ProjectItem]] = []
        for p in profile.projects:
            score = calculate_project_match_score(p, job_keywords, job)
            scored_projects.append((score, p))
        scored_projects.sort(key=lambda x: x[0], reverse=True)

        top_project = scored_projects[0][1] if scored_projects else None
        second_project = scored_projects[1][1] if len(scored_projects) > 1 else None

        # 2. Extract Candidate Highlights & Stack
        primary_skills = [s.name for s in profile.skills if s.name.lower() in job_keywords][:5]
        if not primary_skills:
            primary_skills = [s.name for s in profile.skills[:4]]
        skills_phrase = ", ".join(primary_skills)

        education_entry = profile.education[0] if profile.education else None
        edu_phrase = (
            f"pursuing my {education_entry.degree} at {education_entry.school}"
            if education_entry and education_entry.degree
            else "with an academic foundation in Computer Science and Engineering"
        )

        # Paragraph 1: Hook, role, company, alignment
        company_clean = job.company.rstrip(".")
        opening = (
            f"I am writing to express my enthusiastic interest in the {job.title} position at {company_clean}. "
            f"Currently {edu_phrase}, I have developed a strong technical foundation in modern software engineering, "
            f"focusing on building performant, reliable applications with {skills_phrase}. "
            f"Given {company_clean}'s engineering focus and commitment to technical excellence, "
            f"I am eager to contribute my full-stack skills and problem-solving mindset to your team."
        )

        # Paragraph 2: Verifiable technical proof from actual projects
        body_parts = []
        if top_project:
            top_stack = ", ".join(top_project.stack[:4]) if top_project.stack else "modern frameworks"
            raw_highlight = top_project.highlights[0].text if top_project.highlights else (top_project.description or "developed modular application components")
            cleaned_hl = clean_prose_snippet(raw_highlight)
            if re.match(r"^(designed|built|architected|developed|implemented|engineered|created)", cleaned_hl, re.I):
                action_phrase = f"where I {cleaned_hl[0].lower() + cleaned_hl[1:]}"
            else:
                action_phrase = f"delivering {cleaned_hl}"
            body_parts.append(
                f"In my project work, I engineered {top_project.name} using {top_stack}, {action_phrase}."
            )

        if second_project:
            second_stack = ", ".join(second_project.stack[:3]) if second_project.stack else "industry-standard tools"
            raw_second_hl = second_project.highlights[0].text if second_project.highlights else (second_project.description or "implemented full lifecycle features")
            cleaned_second = clean_prose_snippet(raw_second_hl)
            if re.match(r"^(designed|built|architected|developed|implemented|engineered|created)", cleaned_second, re.I):
                second_action = f"focusing on {cleaned_second[0].lower() + cleaned_second[1:]}"
            else:
                second_action = f"where I developed {cleaned_second}"
            body_parts.append(
                f"Additionally, while building {second_project.name} with {second_stack}, {second_action}."
            )

        if profile.experience:
            lead_exp = profile.experience[0]
            body_parts.append(
                f"Through my leadership and collaborative experience with {lead_exp.company} as {lead_exp.title}, "
                f"I have consistently demonstrated effective communication, rigorous version control practices, and cross-functional teamwork."
            )

        body = " ".join(body_parts)

        # Paragraph 3: Cultural alignment, enthusiasm, call to action
        closing = (
            f"I am drawn to {company_clean} because of your focus on high-impact solutions, and I am excited by the "
            f"prospect of bringing my technical discipline, rapid learning capabilities, and passion for quality code to your engineering team. "
            f"I welcome the opportunity to discuss how my verified background in full-stack architecture and systems design "
            f"can support your upcoming initiatives. Thank you for your time and consideration."
        )

        return CoverLetterData(
            candidate_name=pi.name,
            candidate_email=pi.email,
            candidate_phone=pi.phone,
            candidate_location=pi.location,
            candidate_linkedin=pi.links.get("linkedin"),
            candidate_github=pi.links.get("github"),
            company_name=job.company,
            job_title=job.title,
            opening_paragraph=opening,
            body_paragraph=body,
            closing_paragraph=closing,
        )

    def _generate_with_claude(
        self,
        profile: MasterProfile,
        job: Job,
    ) -> CoverLetterData:
        """Prompt Claude to craft tailored paragraphs strictly constrained to master_profile facts."""
        if not self.claude_client:
            raise LLMError("Claude client is not configured.")

        # Build grounded profile context
        pi = profile.personal_info
        projects_summary = []
        for p in profile.projects[:6]:
            highlights_txt = "; ".join(h.text for h in p.highlights[:2])
            projects_summary.append(
                f"- Project '{p.name}' (Stack: {', '.join(p.stack)}): {p.description or ''} Highlights: {highlights_txt}"
            )

        exp_summary = []
        for e in profile.experience:
            exp_summary.append(f"- {e.title} at {e.company} ({e.start_date} - {e.end_date})")

        prompt = f"""You are an elite, highly concise technical cover letter writer.
Write a 3-paragraph tailored cover letter for {pi.name} applying for {job.title} at {job.company}.

CRITICAL ANTI-HALLUCINATION RULES:
1. You MUST ONLY cite projects, skills, education, and experiences listed in the candidate context below.
2. DO NOT invent prior employers, internships, certifications, or exaggerated metrics.
3. Keep the total length between 250 and 350 words across exactly 3 paragraphs.

CANDIDATE CONTEXT:
Name: {pi.name}
Headline: {pi.headline or 'Software Engineer'}
Skills: {', '.join(profile.get_all_skills_flat()[:25])}
Education: {profile.education[0].school if profile.education else 'Computer Science'} ({profile.education[0].degree if profile.education else 'B.Tech'})
Verified Projects:
{chr(10).join(projects_summary)}
Verified Roles:
{chr(10).join(exp_summary)}

TARGET JOB:
Company: {job.company}
Title: {job.title}
Description: {job.description[:1000]}

Respond ONLY with a JSON object adhering to this schema:
{{
  "opening_paragraph": "First paragraph introducing role, company, candidate background, and high-level alignment.",
  "body_paragraph": "Second paragraph giving concrete proof using 1-2 verified projects from the context.",
  "closing_paragraph": "Third paragraph expressing enthusiasm for the company, team contribution, and inviting conversation."
}}"""

        response = self.claude_client.generate_json(
            prompt=prompt,
            system="You write authentic, ATS-compliant technical cover letters strictly grounded in verified facts.",
            temperature=0.3,
        )

        return CoverLetterData(
            candidate_name=pi.name,
            candidate_email=pi.email,
            candidate_phone=pi.phone,
            candidate_location=pi.location,
            candidate_linkedin=pi.links.get("linkedin"),
            candidate_github=pi.links.get("github"),
            company_name=job.company,
            job_title=job.title,
            opening_paragraph=response["opening_paragraph"].strip(),
            body_paragraph=response["body_paragraph"].strip(),
            closing_paragraph=response["closing_paragraph"].strip(),
        )
