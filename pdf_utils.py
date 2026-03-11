"""
PDF generation utilities for the r/books pipeline.

Converts markdown reports and comment data into styled PDFs
using reportlab's Platypus engine.
"""

import io
import re
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)

# WIP: make prettier!

# ── Colour palette ────────────────────────────────────────────────────────────
ACCENT   = HexColor("#e94560")
DARK     = HexColor("#1a1a2e")
MID_GREY = HexColor("#556677")
LIGHT_BG = HexColor("#f7f8fa")
WHITE    = HexColor("#ffffff")


def _get_styles():
    """Build custom paragraph styles."""
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "PDFTitle", parent=base["Title"],
            fontSize=22, leading=26, textColor=DARK,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "PDFSubtitle", parent=base["Normal"],
            fontSize=11, leading=14, textColor=MID_GREY,
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "PDFH1", parent=base["Heading1"],
            fontSize=16, leading=20, textColor=DARK,
            spaceBefore=16, spaceAfter=8,
            borderWidth=0, borderPadding=0,
        ),
        "h2": ParagraphStyle(
            "PDFH2", parent=base["Heading2"],
            fontSize=13, leading=16, textColor=ACCENT,
            spaceBefore=12, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "PDFH3", parent=base["Heading3"],
            fontSize=11, leading=14, textColor=DARK,
            spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "PDFBody", parent=base["Normal"],
            fontSize=10, leading=14, textColor=DARK,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "PDFBullet", parent=base["Normal"],
            fontSize=10, leading=14, textColor=DARK,
            leftIndent=16, spaceAfter=3,
            bulletIndent=6, bulletFontSize=10,
        ),
        "comment_author": ParagraphStyle(
            "CommentAuthor", parent=base["Normal"],
            fontSize=9, leading=12, textColor=ACCENT,
            fontName="Helvetica-Bold",
        ),
        "comment_body": ParagraphStyle(
            "CommentBody", parent=base["Normal"],
            fontSize=9, leading=12, textColor=DARK,
            leftIndent=8, spaceAfter=4,
        ),
        "footer": ParagraphStyle(
            "PDFFooter", parent=base["Normal"],
            fontSize=8, leading=10, textColor=MID_GREY,
            alignment=TA_CENTER,
        ),
    }
    return styles


def _sanitize(text: str) -> str:
    """Escape XML-special characters for reportlab Paragraphs."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _md_to_flowables(md_text: str, styles: dict) -> list:
    """Convert basic markdown to a list of reportlab flowables."""
    flowables = []
    lines = md_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            flowables.append(Spacer(1, 4))
            i += 1
            continue

        # Headings
        if stripped.startswith("### "):
            text = _sanitize(stripped[4:])
            flowables.append(Paragraph(text, styles["h3"]))
        elif stripped.startswith("## "):
            text = _sanitize(stripped[3:])
            flowables.append(Paragraph(text, styles["h2"]))
        elif stripped.startswith("# "):
            text = _sanitize(stripped[2:])
            flowables.append(Paragraph(text, styles["h1"]))
        elif stripped.startswith("---") or stripped.startswith("==="):
            flowables.append(HRFlowable(
                width="100%", thickness=1, color=MID_GREY,
                spaceAfter=8, spaceBefore=8,
            ))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            text = _sanitize(stripped[2:])
            # Convert **bold** to <b>bold</b>
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            flowables.append(Paragraph(f"• {text}", styles["bullet"]))
        elif re.match(r"^\d+\.\s", stripped):
            text = _sanitize(re.sub(r"^\d+\.\s*", "", stripped))
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            num = re.match(r"^(\d+)\.", stripped).group(1)
            flowables.append(Paragraph(f"{num}. {text}", styles["bullet"]))
        else:
            # Regular paragraph — collect consecutive non-empty, non-heading lines
            para_lines = [stripped]
            while i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if (not next_line or next_line.startswith("#") or
                    next_line.startswith("- ") or next_line.startswith("* ") or
                    next_line.startswith("---") or re.match(r"^\d+\.\s", next_line)):
                    break
                para_lines.append(next_line)
                i += 1

            text = _sanitize(" ".join(para_lines))
            # Convert **bold** and *italic*
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
            flowables.append(Paragraph(text, styles["body"]))

        i += 1

    return flowables


def _add_header_footer(canvas, doc, title="r/books Analysis"):
    """Draw header line and footer on each page."""
    canvas.saveState()
    w, h = A4

    # Header line
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(2)
    canvas.line(20 * mm, h - 18 * mm, w - 20 * mm, h - 18 * mm)

    # Footer
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(
        w / 2, 12 * mm,
        f"{title}  •  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  •  Page {doc.page}"
    )

    canvas.restoreState()


# _______________________________________________________________________________

def markdown_to_pdf(md_text: str, title: str = "Report",
                    subtitle: str = "") -> bytes:
    """
    Convert a markdown string into a styled PDF.

    Returns the PDF as bytes (suitable for st.download_button).
    """
    buf = io.BytesIO()
    styles = _get_styles()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=24 * mm, bottomMargin=20 * mm,
    )

    story = []

    # Title block
    story.append(Paragraph(_sanitize(title), styles["title"]))
    if subtitle:
        story.append(Paragraph(_sanitize(subtitle), styles["subtitle"]))
    story.append(HRFlowable(
        width="100%", thickness=2, color=ACCENT,
        spaceAfter=12, spaceBefore=4,
    ))

    # Convert markdown body
    story.extend(_md_to_flowables(md_text, styles))

    # Build
    doc.build(
        story,
        onFirstPage=lambda c, d: _add_header_footer(c, d, title),
        onLaterPages=lambda c, d: _add_header_footer(c, d, title),
    )

    return buf.getvalue()