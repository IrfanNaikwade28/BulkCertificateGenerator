"""Renders the predefined certificate template to a PDF file with ReportLab."""

import io
import logging
import os
import uuid
from datetime import date
from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

import templates.certificate_layout as layout

logger = logging.getLogger(__name__)


def _centered_width(text: str, font: str, size: float) -> float:
    return (A4[0] - pdfmetrics.stringWidth(text, font, size)) / 2


def _fit_size(text: str, font: str, max_size: float, min_size: float, max_width: float) -> float:
    """Shrink the font size until the text fits inside max_width."""
    size = max_size
    while size > min_size and pdfmetrics.stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def render_certificate(
    *,
    recipient_name: str,
    recipient_email: str,
    certificate_title: str,
    event_name: str,
    issue_date: date,
    certificate_id: uuid.UUID,
    output_path: Path,
) -> int:
    """Render one certificate and write it atomically to output_path.

    Returns the file size in bytes. Raises on any rendering or I/O error;
    callers must treat that as a per-recipient failure.
    """
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageTitle=certificate_title)
    width, height = A4

    _draw_border(pdf, width, height)
    _draw_heading(pdf, width, height, certificate_title)
    _draw_recipient(pdf, width, height, recipient_name)
    _draw_body(pdf, width, height, event_name, issue_date)
    _draw_signature(pdf, width, height)
    _draw_footer(pdf, width, height, certificate_id, recipient_email)

    pdf.showPage()
    pdf.save()
    data = buffer.getvalue()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")
    temp_path.write_bytes(data)
    os.replace(temp_path, output_path)
    return len(data)


def _draw_border(pdf: canvas.Canvas, width: float, height: float) -> None:
    pdf.setStrokeColor(layout.ACCENT_DARK)
    pdf.setLineWidth(3)
    pdf.rect(
        layout.BORDER_OUTER_MARGIN,
        layout.BORDER_OUTER_MARGIN,
        width - 2 * layout.BORDER_OUTER_MARGIN,
        height - 2 * layout.BORDER_OUTER_MARGIN,
    )
    pdf.setStrokeColor(layout.ACCENT_GOLD)
    pdf.setLineWidth(1)
    pdf.rect(
        layout.BORDER_INNER_MARGIN,
        layout.BORDER_INNER_MARGIN,
        width - 2 * layout.BORDER_INNER_MARGIN,
        height - 2 * layout.BORDER_INNER_MARGIN,
    )


def _draw_heading(
    pdf: canvas.Canvas, width: float, height: float, certificate_title: str
) -> None:
    max_width = width - 2 * layout.BORDER_INNER_MARGIN - 40
    size = _fit_size(
        certificate_title,
        layout.TITLE_FONT,
        layout.TITLE_MAX_SIZE,
        layout.TITLE_MIN_SIZE,
        max_width,
    )
    pdf.setFillColor(layout.ACCENT_DARK)
    pdf.setFont(layout.TITLE_FONT, size)
    pdf.drawString(
        _centered_width(certificate_title, layout.TITLE_FONT, size),
        height - 150,
        certificate_title,
    )

    pdf.setFillColor(layout.MUTED)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(
        _centered_width(layout.PRESENTED_BY, "Helvetica", 12), height - 210, layout.PRESENTED_BY
    )


def _draw_recipient(pdf: canvas.Canvas, width: float, height: float, name: str) -> None:
    max_width = width - 2 * layout.BORDER_INNER_MARGIN - 80
    size = _fit_size(name, layout.NAME_FONT, layout.NAME_MAX_SIZE, layout.NAME_MIN_SIZE, max_width)
    x = _centered_width(name, layout.NAME_FONT, size)
    y = height - 270

    pdf.setFillColor(layout.INK)
    pdf.setFont(layout.NAME_FONT, size)
    pdf.drawString(x, y, name)

    name_width = pdfmetrics.stringWidth(name, layout.NAME_FONT, size)
    pdf.setStrokeColor(layout.ACCENT_GOLD)
    pdf.setLineWidth(1.5)
    pdf.line((width - name_width) / 2, y - 12, (width + name_width) / 2, y - 12)


def _draw_body(
    pdf: canvas.Canvas, width: float, height: float, event_name: str, issue_date: date
) -> None:
    recognition_text = layout.RECOGNITION_TEXT.format(event_name=event_name)
    pdf.setFillColor(layout.MUTED)
    pdf.setFont("Helvetica", 12)
    for index, line in enumerate(simpleSplit(recognition_text, "Helvetica", 12, width - 200)):
        pdf.drawString(
            _centered_width(line, "Helvetica", 12), height - 320 - index * 18, line
        )

    issued = f"Issued on: {issue_date.strftime('%d %B %Y')}"
    pdf.setFillColor(layout.INK)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(_centered_width(issued, "Helvetica", 11), height - 400, issued)


def _draw_signature(pdf: canvas.Canvas, width: float, height: float) -> None:
    line_width = 160
    line_x = width - layout.BORDER_INNER_MARGIN - 60 - line_width
    line_y = 150

    pdf.setStrokeColor(layout.INK)
    pdf.setLineWidth(1)
    pdf.line(line_x, line_y, line_x + line_width, line_y)

    pdf.setFillColor(layout.INK)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(line_x, line_y - 16, layout.ISSUER_NAME)
    pdf.setFillColor(layout.MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(line_x, line_y - 30, layout.ISSUER_TITLE)


def _draw_footer(
    pdf: canvas.Canvas, width: float, height: float, certificate_id: uuid.UUID, email: str
) -> None:
    pdf.setFillColor(layout.MUTED)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(
        layout.BORDER_INNER_MARGIN + 12, 60, f"Certificate ID: {certificate_id}"
    )
    pdf.drawString(layout.BORDER_INNER_MARGIN + 12, 48, f"Issued to: {email}")
    footer_width = pdfmetrics.stringWidth(layout.FOOTER_NOTE, "Helvetica", 8)
    pdf.drawString(width - layout.BORDER_INNER_MARGIN - 12 - footer_width, 60, layout.FOOTER_NOTE)
