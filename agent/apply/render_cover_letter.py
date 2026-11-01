"""Cover letter rendering engines for PDF, Word (.docx), and plain text formats."""

import logging
from pathlib import Path
from typing import Optional

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from agent.apply.cover_letter import CoverLetterData

logger = logging.getLogger(__name__)


def render_cover_letter_docx(
    data: CoverLetterData,
    output_path: str,
) -> Path:
    """Render cover letter as an editable, beautifully formatted Word document (.docx).

    Args:
        data: CoverLetterData model.
        output_path: File destination path.

    Returns:
        Path to generated docx file.
    """
    doc = docx.Document()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Margins (0.75 inch)
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    navy = RGBColor(15, 23, 42)
    sub_navy = RGBColor(30, 58, 138)
    charcoal = RGBColor(51, 65, 85)

    # 1. Candidate Name (Header)
    p_name = doc.add_paragraph()
    p_name.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r_name = p_name.add_run(data.candidate_name.upper())
    r_name.font.name = "Calibri"
    r_name.font.size = Pt(18)
    r_name.font.bold = True
    r_name.font.color.rgb = navy
    p_name.paragraph_format.space_after = Pt(2)

    # Contact Info Bar
    contacts = []
    if data.candidate_location:
        contacts.append(data.candidate_location)
    if data.candidate_email:
        contacts.append(data.candidate_email)
    if data.candidate_phone:
        contacts.append(data.candidate_phone)
    if data.candidate_github:
        contacts.append(f"GitHub: {data.candidate_github}")
    if data.candidate_linkedin:
        contacts.append(f"LinkedIn: {data.candidate_linkedin}")

    if contacts:
        p_contact = doc.add_paragraph()
        r_contact = p_contact.add_run("  •  ".join(contacts))
        r_contact.font.name = "Calibri"
        r_contact.font.size = Pt(9.5)
        r_contact.font.color.rgb = sub_navy
        p_contact.paragraph_format.space_after = Pt(14)

    # 2. Date
    p_date = doc.add_paragraph()
    r_date = p_date.add_run(data.date)
    r_date.font.name = "Calibri"
    r_date.font.size = Pt(11)
    r_date.font.color.rgb = charcoal
    p_date.paragraph_format.space_after = Pt(10)

    # 3. Recipient Info
    p_rec = doc.add_paragraph()
    r_rec = p_rec.add_run(
        f"Hiring Team\n{data.company_name}\nRe: Application for {data.job_title}"
    )
    r_rec.font.name = "Calibri"
    r_rec.font.size = Pt(11)
    r_rec.font.bold = True
    r_rec.font.color.rgb = navy
    p_rec.paragraph_format.space_after = Pt(14)

    # 4. Salutation
    p_sal = doc.add_paragraph()
    r_sal = p_sal.add_run(data.salutation)
    r_sal.font.name = "Calibri"
    r_sal.font.size = Pt(11)
    r_sal.font.color.rgb = charcoal
    p_sal.paragraph_format.space_after = Pt(10)

    # 5. Three Body Paragraphs
    for para_text in (data.opening_paragraph, data.body_paragraph, data.closing_paragraph):
        p_body = doc.add_paragraph()
        r_body = p_body.add_run(para_text)
        r_body.font.name = "Calibri"
        r_body.font.size = Pt(11)
        r_body.font.color.rgb = charcoal
        p_body.paragraph_format.space_after = Pt(12)
        p_body.paragraph_format.line_spacing = 1.15

    # 6. Sign-off
    p_sign = doc.add_paragraph()
    r_sign = p_sign.add_run(f"{data.sign_off}\n\n{data.candidate_name}")
    r_sign.font.name = "Calibri"
    r_sign.font.size = Pt(11)
    r_sign.font.color.rgb = navy
    r_sign.font.bold = True
    p_sign.paragraph_format.space_after = Pt(6)

    doc.save(str(out))
    logger.info(f"Cover letter DOCX saved to: {out}")
    return out


def render_cover_letter_pdf(
    data: CoverLetterData,
    output_path: str,
) -> Path:
    """Render cover letter as a publication-ready PDF using ReportLab.

    Args:
        data: CoverLetterData model.
        output_path: Destination PDF path.

    Returns:
        Path to generated PDF file.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Page setup (Letter, 0.75 in margins)
    margin = 54  # 0.75 in * 72 points
    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        "CL_Header",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=HexColor("#0F172A"),
        spaceAfter=3,
    )

    contact_style = ParagraphStyle(
        "CL_Contact",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=HexColor("#1E3A8A"),
        spaceAfter=8,
    )

    meta_style = ParagraphStyle(
        "CL_Meta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=HexColor("#334155"),
        spaceAfter=10,
    )

    recipient_style = ParagraphStyle(
        "CL_Recipient",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=15,
        textColor=HexColor("#0F172A"),
        spaceAfter=12,
    )

    body_style = ParagraphStyle(
        "CL_Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15.5,
        textColor=HexColor("#1E293B"),
        spaceAfter=11,
    )

    sign_style = ParagraphStyle(
        "CL_Sign",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=15,
        textColor=HexColor("#0F172A"),
        spaceBefore=8,
        spaceAfter=4,
    )

    story = []

    # 1. Header Name
    story.append(Paragraph(data.candidate_name.upper(), header_style))

    # Contact line
    contacts = []
    if data.candidate_location:
        contacts.append(data.candidate_location)
    if data.candidate_email:
        contacts.append(data.candidate_email)
    if data.candidate_phone:
        contacts.append(data.candidate_phone)
    if data.candidate_github:
        contacts.append(f"GitHub: {data.candidate_github}")
    if data.candidate_linkedin:
        contacts.append(f"LinkedIn: {data.candidate_linkedin}")

    if contacts:
        story.append(Paragraph(" &bull; ".join(contacts), contact_style))

    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#CBD5E1"), spaceAfter=14))

    # 2. Date
    story.append(Paragraph(data.date, meta_style))

    # 3. Recipient block
    recipient_text = (
        f"<b>Hiring Team</b><br/>"
        f"{data.company_name}<br/>"
        f"<i>Re: Application for {data.job_title}</i>"
    )
    story.append(Paragraph(recipient_text, recipient_style))

    # 4. Salutation
    story.append(Paragraph(data.salutation, meta_style))

    # 5. Three Body Paragraphs
    story.append(Paragraph(data.opening_paragraph, body_style))
    story.append(Paragraph(data.body_paragraph, body_style))
    story.append(Paragraph(data.closing_paragraph, body_style))

    # 6. Sign-off
    story.append(Spacer(1, 6))
    sign_text = f"{data.sign_off}<br/><br/><b>{data.candidate_name}</b>"
    story.append(Paragraph(sign_text, sign_style))

    doc.build(story)
    logger.info(f"Cover letter PDF saved to: {out}")
    return out


def render_cover_letter_text(
    data: CoverLetterData,
    output_path: str,
) -> Path:
    """Save cover letter as a clean plain text file.

    Args:
        data: CoverLetterData model.
        output_path: Target text file destination.

    Returns:
        Path to generated txt file.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(data.to_plain_text(), encoding="utf-8")
    logger.info(f"Cover letter TXT saved to: {out}")
    return out
