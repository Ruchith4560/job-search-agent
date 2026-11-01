"""Tests for HTML, DOCX, and PDF resume rendering engines."""

from pathlib import Path
import docx
from agent.resume.render import render_docx, render_html, render_pdf
from agent.resume.schema import (
    ResumeData,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
)


def sample_resume() -> ResumeData:
    return ResumeData(
        name="Ruchith Macha",
        headline="Full Stack Software Engineer",
        email="macharuchith1@gmail.com",
        phone="6305239230",
        location="Hyderabad, India",
        github_url="https://github.com/Ruchith4560",
        summary="Computer Science undergraduate passionate about building scalable web applications.",
        skills_by_category={
            "Languages": ["Python", "Java", "TypeScript"],
            "Frameworks": ["React", "FastAPI", "Spring Boot"],
        },
        experience=[
            ResumeExperience(
                company="IEEE Student Branch",
                title="Content Specialist",
                dates="Jun 2025 – Present",
                location="Hyderabad",
                bullets=["Published technical articles for 500+ student members"],
            )
        ],
        projects=[
            ResumeProject(
                name="Smart AI Healthcare System",
                url="https://github.com/Ruchith4560/smart-ai-healthcare-system",
                stack=["React", "FastAPI", "Python"],
                bullets=["Built doctor appointment booking system with sub-200ms latency"],
            )
        ],
        education=[
            ResumeEducation(
                school="Anurag University",
                degree="Bachelor of Technology",
                dates="2024 – 2028",
            )
        ],
        certifications=["HP Power Lab 2.0 Assessment (Unstop)"],
    )


def test_render_html() -> None:
    data = sample_resume()
    html = render_html(data)
    assert "Ruchith Macha" in html
    assert "Smart AI Healthcare System" in html
    assert "macharuchith1@gmail.com" in html
    assert "FastAPI" in html


def test_render_docx(tmp_path: Path) -> None:
    data = sample_resume()
    docx_file = tmp_path / "test_resume.docx"
    rendered = render_docx(data, output_path=str(docx_file))

    assert rendered.is_file()
    assert rendered.stat().st_size > 0

    # Verify we can parse it back with python-docx
    doc = docx.Document(str(rendered))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "RUCHITH MACHA" in full_text
    assert "Anurag University" in full_text
    assert "Smart AI Healthcare System" in full_text


def test_render_pdf(tmp_path: Path) -> None:
    data = sample_resume()
    pdf_file = tmp_path / "test_resume.pdf"
    rendered = render_pdf(data, output_path=str(pdf_file))

    assert rendered.is_file()
    assert rendered.stat().st_size > 500  # Non-trivial PDF size
