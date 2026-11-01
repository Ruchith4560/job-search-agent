"""Tests for LinkedIn data export parser."""

import io
from pathlib import Path
import zipfile
import pytest

from agent.ingest.linkedin import LinkedInParser


def test_parse_directory_csvs(tmp_path: Path) -> None:
    # Create sample CSVs in temp directory
    profile_csv = tmp_path / "Profile.csv"
    profile_csv.write_text("First Name,Last Name,Headline,Geo Location\nJane,Doe,Senior Backend Engineer,Hyderabad\n", encoding="utf-8")

    positions_csv = tmp_path / "Positions.csv"
    positions_csv.write_text(
        'Company Name,Title,Description,Location,Started On,Finished On\n'
        'Acme Corp,Software Engineer,"Developed REST APIs in Python\nBuilt microservices",Remote,Jan 2022,Dec 2023\n',
        encoding="utf-8",
    )

    education_csv = tmp_path / "Education.csv"
    education_csv.write_text(
        "School Name,Degree Name,Start Date,End Date\n"
        "State University,B.Tech in Computer Science,2018,2022\n",
        encoding="utf-8",
    )

    skills_csv = tmp_path / "Skills.csv"
    skills_csv.write_text("Name\nPython\nDocker\nFastAPI\nPostgreSQL\n", encoding="utf-8")

    parser = LinkedInParser()
    data = parser.parse(tmp_path)

    assert data.profile.first_name == "Jane"
    assert data.profile.last_name == "Doe"
    assert data.profile.headline == "Senior Backend Engineer"
    assert len(data.positions) == 1
    assert data.positions[0].company_name == "Acme Corp"
    assert len(data.education) == 1
    assert data.education[0].school_name == "State University"
    assert len(data.skills) == 4
    skill_names = [s.name for s in data.skills]
    assert "Python" in skill_names
    assert "FastAPI" in skill_names


def test_parse_zip_file(tmp_path: Path) -> None:
    zip_file_path = tmp_path / "linkedin_export.zip"

    # Create in-memory zip
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Profile.csv", "First Name,Last Name,Headline\nAlex,Smith,Cloud Architect\n")
        z.writestr("Skills.csv", "Name\nAWS\nKubernetes\nTerraform\n")
        z.writestr("Certifications.csv", "Name,Authority\nAWS Solutions Architect,Amazon Web Services\n")

    zip_file_path.write_bytes(buffer.getvalue())

    parser = LinkedInParser()
    data = parser.parse(zip_file_path)

    assert data.profile.first_name == "Alex"
    assert data.profile.headline == "Cloud Architect"
    assert len(data.skills) == 3
    assert len(data.certifications) == 1
    assert data.certifications[0].name == "AWS Solutions Architect"


def test_missing_files_graceful(tmp_path: Path) -> None:
    # Empty directory
    parser = LinkedInParser()
    data = parser.parse(tmp_path)

    assert data.profile.first_name is None
    assert len(data.positions) == 0
    assert len(data.skills) == 0
