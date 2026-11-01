"""Resume rendering engines for ATS-compliant HTML, DOCX, and PDF formats."""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
import jinja2
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from agent.resume.schema import ResumeData

logger = logging.getLogger(__name__)


def render_html(resume_data: ResumeData, template_name: str = "resume.html.j2") -> str:
    """Render ATS-friendly HTML from Jinja2 template.

    Args:
        resume_data: Formatted resume data.
        template_name: Filename of the template.

    Returns:
        Rendered HTML string.
    """
    templates_dir = Path(__file__).parent / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )
    template = env.get_template(template_name)
    return template.render(resume=resume_data)


def render_docx(resume_data: ResumeData, output_path: str = "data/output/resume.docx") -> Path:
    """Render editable ATS-friendly Microsoft Word document (.docx).

    Args:
        resume_data: Formatted resume data.
        output_path: Target path for the output file.

    Returns:
        Path object pointing to the written docx file.
    """
    doc = docx.Document()

    # Set 0.5 inch margins for ATS one-page optimization
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

    # Styles
    navy = RGBColor(15, 23, 42)
    sub_navy = RGBColor(30, 58, 138)

    # 1. Header: Name
    name_para = doc.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = name_para.add_run(resume_data.name.upper())
    name_run.font.name = "Calibri"
    name_run.font.size = Pt(18)
    name_run.font.bold = True
    name_run.font.color.rgb = navy
    name_para.paragraph_format.space_after = Pt(2)

    # Headline
    if resume_data.headline:
        hl_para = doc.add_paragraph()
        hl_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hl_run = hl_para.add_run(resume_data.headline)
        hl_run.font.name = "Calibri"
        hl_run.font.size = Pt(10)
        hl_run.font.bold = True
        hl_run.font.color.rgb = sub_navy
        hl_para.paragraph_format.space_after = Pt(2)

    # Contact line
    contacts = []
    if resume_data.location:
        contacts.append(resume_data.location)
    if resume_data.email:
        contacts.append(resume_data.email)
    if resume_data.phone:
        contacts.append(resume_data.phone)
    if resume_data.github_url:
        contacts.append(f"GitHub: {resume_data.github_url}")
    if resume_data.linkedin_url:
        contacts.append(f"LinkedIn: {resume_data.linkedin_url}")

    if contacts:
        contact_para = doc.add_paragraph()
        contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c_run = contact_para.add_run("  •  ".join(contacts))
        c_run.font.name = "Calibri"
        c_run.font.size = Pt(9)
        c_run.font.color.rgb = RGBColor(71, 85, 105)
        contact_para.paragraph_format.space_after = Pt(8)

    def add_section_header(title: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(title.upper())
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = navy

    # 2. Summary
    if resume_data.summary:
        add_section_header("Professional Summary")
        sp = doc.add_paragraph()
        srun = sp.add_run(resume_data.summary)
        srun.font.name = "Calibri"
        srun.font.size = Pt(9.5)
        sp.paragraph_format.space_after = Pt(6)

    # 3. Technical Skills
    if resume_data.skills_by_category:
        add_section_header("Technical Skills")
        for cat, skills in resume_data.skills_by_category.items():
            sp = doc.add_paragraph()
            sp.paragraph_format.space_after = Pt(2)
            crun = sp.add_run(f"{cat}: ")
            crun.font.name = "Calibri"
            crun.font.size = Pt(9.5)
            crun.font.bold = True
            srun = sp.add_run(", ".join(skills))
            srun.font.name = "Calibri"
            srun.font.size = Pt(9.5)

    # 4. Technical Projects
    if resume_data.projects:
        add_section_header("Technical Projects")
        for proj in resume_data.projects:
            pp = doc.add_paragraph()
            pp.paragraph_format.space_before = Pt(4)
            pp.paragraph_format.space_after = Pt(1)
            prun = pp.add_run(proj.name)
            prun.font.name = "Calibri"
            prun.font.size = Pt(10)
            prun.font.bold = True

            if proj.url:
                url_run = pp.add_run(f"  |  {proj.url}")
                url_run.font.name = "Calibri"
                url_run.font.size = Pt(8.5)
                url_run.font.color.rgb = sub_navy

            if proj.stack:
                tp = doc.add_paragraph()
                tp.paragraph_format.space_after = Pt(2)
                trun = tp.add_run(f"Tech Stack: {' • '.join(proj.stack)}")
                trun.font.name = "Calibri"
                trun.font.size = Pt(8.5)
                trun.font.bold = True
                trun.font.color.rgb = sub_navy

            for bullet in proj.bullets:
                bp = doc.add_paragraph(style="List Bullet")
                bp.paragraph_format.space_after = Pt(1)
                brun = bp.add_run(bullet)
                brun.font.name = "Calibri"
                brun.font.size = Pt(9.2)

    # 5. Experience
    if resume_data.experience:
        add_section_header("Experience & Leadership")
        for exp in resume_data.experience:
            ep = doc.add_paragraph()
            ep.paragraph_format.space_before = Pt(4)
            ep.paragraph_format.space_after = Pt(1)
            trun = ep.add_run(f"{exp.title} — {exp.company}")
            trun.font.name = "Calibri"
            trun.font.size = Pt(10)
            trun.font.bold = True

            loc_str = f" | {exp.location}" if exp.location else ""
            drun = ep.add_run(f"    ({exp.dates}{loc_str})")
            drun.font.name = "Calibri"
            drun.font.size = Pt(9)
            drun.font.color.rgb = RGBColor(100, 116, 139)

            for bullet in exp.bullets:
                bp = doc.add_paragraph(style="List Bullet")
                bp.paragraph_format.space_after = Pt(1)
                brun = bp.add_run(bullet)
                brun.font.name = "Calibri"
                brun.font.size = Pt(9.2)

    # 6. Education
    if resume_data.education:
        add_section_header("Education")
        for edu in resume_data.education:
            edp = doc.add_paragraph()
            edp.paragraph_format.space_before = Pt(2)
            edp.paragraph_format.space_after = Pt(1)
            srun = edp.add_run(f"{edu.school} — {edu.degree}")
            srun.font.name = "Calibri"
            srun.font.size = Pt(9.5)
            srun.font.bold = True
            drun = edp.add_run(f"    ({edu.dates})")
            drun.font.name = "Calibri"
            drun.font.size = Pt(9)
            drun.font.color.rgb = RGBColor(100, 116, 139)

    # 7. Certifications
    if resume_data.certifications:
        add_section_header("Certifications")
        for cert in resume_data.certifications:
            cp = doc.add_paragraph(style="List Bullet")
            cp.paragraph_format.space_after = Pt(1)
            crun = cp.add_run(cert)
            crun.font.name = "Calibri"
            crun.font.size = Pt(9.2)

    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target_path))
    logger.info("Saved DOCX resume to %s", target_path)
    return target_path


def render_pdf(resume_data: ResumeData, output_path: str = "data/output/resume.pdf") -> Path:
    """Render publication-grade ATS-friendly PDF resume using ReportLab.

    Args:
        resume_data: Formatted resume data.
        output_path: Target path for the output file.

    Returns:
        Path object pointing to the written pdf file.
    """
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(target_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=32,
        bottomMargin=32,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=HexColor("#0f172a"),
        alignment=1,  # Center
        spaceAfter=2,
    )
    headline_style = ParagraphStyle(
        "Headline",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=12,
        textColor=HexColor("#1e3a8a"),
        alignment=1,  # Center
        spaceAfter=3,
    )
    contact_style = ParagraphStyle(
        "Contact",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=HexColor("#475569"),
        alignment=1,  # Center
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=HexColor("#0f172a"),
        spaceBefore=7,
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=HexColor("#334155"),
        spaceAfter=2,
    )
    bold_body = ParagraphStyle(
        "BoldBody",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=HexColor("#0f172a"),
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=11.5,
        textColor=HexColor("#334155"),
        leftIndent=12,
        spaceAfter=1.5,
    )
    stack_style = ParagraphStyle(
        "Stack",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=HexColor("#1e3a8a"),
        spaceAfter=2,
    )

    story = []

    # 1. Header
    story.append(Paragraph(resume_data.name.upper(), title_style))
    if resume_data.headline:
        story.append(Paragraph(resume_data.headline, headline_style))

    contact_parts = []
    if resume_data.location:
        contact_parts.append(resume_data.location)
    if resume_data.email:
        contact_parts.append(resume_data.email)
    if resume_data.phone:
        contact_parts.append(resume_data.phone)
    if resume_data.github_url:
        contact_parts.append(f"GitHub: {resume_data.github_url}")
    if resume_data.linkedin_url:
        contact_parts.append(f"LinkedIn: {resume_data.linkedin_url}")

    if contact_parts:
        story.append(Paragraph(" • ".join(contact_parts), contact_style))

    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#1a365d"), spaceAfter=5))

    def add_section(name: str) -> None:
        story.append(Paragraph(name.upper(), section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cbd5e1"), spaceAfter=3))

    # 2. Summary
    if resume_data.summary:
        add_section("Professional Summary")
        story.append(Paragraph(resume_data.summary, body_style))

    # 3. Technical Skills
    if resume_data.skills_by_category:
        add_section("Technical Skills")
        for cat, skills in resume_data.skills_by_category.items():
            text = f"<b>{cat}:</b> {', '.join(skills)}"
            story.append(Paragraph(text, body_style))

    # 4. Technical Projects
    if resume_data.projects:
        add_section("Technical Projects")
        for proj in resume_data.projects:
            header_text = f"<b>{proj.name}</b>"
            if proj.url:
                header_text += f" <font color='#1e3a8a'>({proj.url})</font>"
            story.append(Paragraph(header_text, body_style))

            if proj.stack:
                story.append(Paragraph(f"Tech Stack: {' • '.join(proj.stack)}", stack_style))

            for bullet in proj.bullets:
                story.append(Paragraph(f"• {bullet}", bullet_style))

    # 5. Experience
    if resume_data.experience:
        add_section("Experience & Leadership")
        for exp in resume_data.experience:
            loc_str = f" | {exp.location}" if exp.location else ""
            line = f"<b>{exp.title}</b> — {exp.company} <font color='#64748b'><i>({exp.dates}{loc_str})</i></font>"
            story.append(Paragraph(line, body_style))

            for bullet in exp.bullets:
                story.append(Paragraph(f"• {bullet}", bullet_style))

    # 6. Education
    if resume_data.education:
        add_section("Education")
        for edu in resume_data.education:
            ed_line = f"<b>{edu.school}</b> — {edu.degree} <font color='#64748b'>({edu.dates})</font>"
            story.append(Paragraph(ed_line, body_style))
            if edu.notes:
                story.append(Paragraph(f"<font color='#64748b'>{edu.notes}</font>", body_style))

    # 7. Certifications
    if resume_data.certifications:
        add_section("Certifications")
        for cert in resume_data.certifications:
            story.append(Paragraph(f"• {cert}", bullet_style))

    doc.build(story)
    logger.info("Saved PDF resume to %s", target_path)
    return target_path
