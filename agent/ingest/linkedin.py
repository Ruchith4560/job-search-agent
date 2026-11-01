"""LinkedIn official data export ingestion and parser module."""

import csv
from datetime import datetime, timezone
import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import zipfile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RawLinkedInProfile(BaseModel):
    """Personal info parsed from Profile.csv."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    industry: Optional[str] = None
    geo_location: Optional[str] = None
    websites: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class RawLinkedInPosition(BaseModel):
    """Work experience parsed from Positions.csv."""
    company_name: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    started_on: Optional[str] = None
    finished_on: Optional[str] = None


class RawLinkedInEducation(BaseModel):
    """Education entry parsed from Education.csv."""
    school_name: str
    degree_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notes: Optional[str] = None
    activities: Optional[str] = None


class RawLinkedInSkill(BaseModel):
    """Skill entry parsed from Skills.csv."""
    name: str


class RawLinkedInCertification(BaseModel):
    """Certification parsed from Certifications.csv."""
    name: str
    authority: Optional[str] = None
    url: Optional[str] = None
    started_on: Optional[str] = None
    finished_on: Optional[str] = None
    license_number: Optional[str] = None


class RawLinkedInProject(BaseModel):
    """Project entry parsed from Projects.csv if present."""
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    started_on: Optional[str] = None
    finished_on: Optional[str] = None


class LinkedInExportData(BaseModel):
    """Container schema for all parsed LinkedIn export data."""
    profile: RawLinkedInProfile = Field(default_factory=RawLinkedInProfile)
    positions: List[RawLinkedInPosition] = Field(default_factory=list)
    education: List[RawLinkedInEducation] = Field(default_factory=list)
    skills: List[RawLinkedInSkill] = Field(default_factory=list)
    certifications: List[RawLinkedInCertification] = Field(default_factory=list)
    projects: List[RawLinkedInProject] = Field(default_factory=list)
    parsed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def normalize_col_name(col: str) -> str:
    """Normalize CSV header strings (lowercase, stripped, underscore-separated)."""
    return col.strip().lower().replace(" ", "_")


class LinkedInParser:
    """Parses official LinkedIn data export folders or ZIP files."""

    def __init__(self) -> None:
        pass

    def _read_csv_content(self, content_str: str) -> List[Dict[str, str]]:
        """Parse raw CSV string with robust dialect and delimiter detection."""
        if not content_str.strip():
            return []

        file_obj = io.StringIO(content_str)
        reader = csv.reader(file_obj)
        try:
            raw_headers = next(reader)
        except StopIteration:
            return []

        headers = [normalize_col_name(h) for h in raw_headers]
        rows = []
        for raw_row in reader:
            if not raw_row or all(not cell.strip() for cell in raw_row):
                continue
            row_dict = {}
            for i, val in enumerate(raw_row):
                if i < len(headers):
                    row_dict[headers[i]] = val.strip()
            rows.append(row_dict)
        return rows

    def _load_csv_from_disk(self, file_path: Path) -> List[Dict[str, str]]:
        """Read CSV file with multiple encoding fallbacks (utf-8-sig, utf-8, latin-1)."""
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text = file_path.read_text(encoding=enc)
                return self._read_csv_content(text)
            except UnicodeDecodeError:
                continue
        logger.warning("Could not decode CSV file %s with standard encodings.", file_path)
        return []

    def _find_file_in_dir(self, directory: Path, target_filename: str) -> Optional[Path]:
        """Search recursively for target CSV filename case-insensitively."""
        target_lower = target_filename.lower()
        for p in directory.rglob("*"):
            if p.is_file() and p.name.lower() == target_lower:
                return p
        return None

    def _extract_from_zip(self, zip_path: Path) -> Dict[str, str]:
        """Extract CSV file contents from a ZIP archive directly into memory."""
        file_contents: Dict[str, str] = {}
        with zipfile.ZipFile(zip_path, "r") as z:
            for item in z.infolist():
                if item.is_dir() or not item.filename.lower().endswith(".csv"):
                    continue
                basename = Path(item.filename).name.lower()
                raw_bytes = z.read(item.filename)
                for enc in ("utf-8-sig", "utf-8", "latin-1"):
                    try:
                        file_contents[basename] = raw_bytes.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
        return file_contents

    def parse(self, source_path: Union[str, Path]) -> LinkedInExportData:
        """Parse LinkedIn data export from a folder or ZIP file.

        Args:
            source_path: Path to directory containing LinkedIn CSVs or a .zip file.

        Returns:
            LinkedInExportData containing normalized records.
        """
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"LinkedIn data source path not found: {path}")

        csv_data_map: Dict[str, List[Dict[str, str]]] = {}

        if path.is_file() and path.suffix.lower() == ".zip":
            raw_text_map = self._extract_from_zip(path)
            for fname, content in raw_text_map.items():
                csv_data_map[fname] = self._read_csv_content(content)
        elif path.is_dir():
            target_files = [
                "profile.csv",
                "positions.csv",
                "education.csv",
                "skills.csv",
                "certifications.csv",
                "projects.csv",
                "email_addresses.csv",
                "email addresses.csv",
                "phonenumbers.csv",
                "phone numbers.csv",
            ]
            for target in target_files:
                found_path = self._find_file_in_dir(path, target)
                if found_path:
                    csv_data_map[target] = self._load_csv_from_disk(found_path)
                else:
                    logger.debug("LinkedIn file '%s' not found in %s", target, path)
        else:
            raise ValueError(f"Invalid LinkedIn data path: {path}. Must be a directory or .zip file.")

        return self._build_export_data(csv_data_map)

    def _build_export_data(self, csv_map: Dict[str, List[Dict[str, str]]]) -> LinkedInExportData:
        """Construct LinkedInExportData from parsed CSV dictionaries."""
        profile = RawLinkedInProfile()
        if "profile.csv" in csv_map and csv_map["profile.csv"]:
            row = csv_map["profile.csv"][0]
            profile = RawLinkedInProfile(
                first_name=row.get("first_name"),
                last_name=row.get("last_name"),
                headline=row.get("headline"),
                summary=row.get("summary"),
                industry=row.get("industry"),
                geo_location=row.get("geo_location") or row.get("location"),
                websites=row.get("websites"),
            )

        # Extract email address if present
        for email_key in ("email_addresses.csv", "email addresses.csv", "emails.csv"):
            if email_key in csv_map and csv_map[email_key]:
                for erow in csv_map[email_key]:
                    addr = erow.get("email_address") or erow.get("email")
                    if addr:
                        profile.email = addr
                        if erow.get("primary", "").lower() == "yes":
                            break
                if profile.email:
                    break

        # Extract phone number if present
        for phone_key in ("phonenumbers.csv", "phone numbers.csv", "phone_numbers.csv"):
            if phone_key in csv_map and csv_map[phone_key]:
                prow = csv_map[phone_key][0]
                profile.phone = prow.get("number") or prow.get("phone_number")
                if profile.phone:
                    break

        positions: List[RawLinkedInPosition] = []
        for row in csv_map.get("positions.csv", []):
            company = row.get("company_name") or row.get("company")
            title = row.get("title") or row.get("job_title")
            if company and title:
                positions.append(
                    RawLinkedInPosition(
                        company_name=company,
                        title=title,
                        description=row.get("description"),
                        location=row.get("location"),
                        started_on=row.get("started_on") or row.get("start_date"),
                        finished_on=row.get("finished_on") or row.get("end_date"),
                    )
                )

        education: List[RawLinkedInEducation] = []
        for row in csv_map.get("education.csv", []):
            school = row.get("school_name") or row.get("school")
            if school:
                education.append(
                    RawLinkedInEducation(
                        school_name=school,
                        degree_name=row.get("degree_name") or row.get("degree"),
                        start_date=row.get("start_date") or row.get("started_on"),
                        end_date=row.get("end_date") or row.get("finished_on"),
                        notes=row.get("notes"),
                        activities=row.get("activities"),
                    )
                )

        skills: List[RawLinkedInSkill] = []
        for row in csv_map.get("skills.csv", []):
            name = row.get("name") or row.get("skill")
            if name:
                skills.append(RawLinkedInSkill(name=name.strip()))

        certifications: List[RawLinkedInCertification] = []
        for row in csv_map.get("certifications.csv", []):
            name = row.get("name") or row.get("certification")
            if name:
                certifications.append(
                    RawLinkedInCertification(
                        name=name,
                        authority=row.get("authority") or row.get("issuer"),
                        url=row.get("url"),
                        started_on=row.get("started_on"),
                        finished_on=row.get("finished_on"),
                        license_number=row.get("license_number"),
                    )
                )

        projects: List[RawLinkedInProject] = []
        for row in csv_map.get("projects.csv", []):
            title = row.get("title") or row.get("project_name")
            if title:
                projects.append(
                    RawLinkedInProject(
                        title=title,
                        description=row.get("description"),
                        url=row.get("url"),
                        started_on=row.get("started_on"),
                        finished_on=row.get("finished_on"),
                    )
                )

        return LinkedInExportData(
            profile=profile,
            positions=positions,
            education=education,
            skills=skills,
            certifications=certifications,
            projects=projects,
        )
