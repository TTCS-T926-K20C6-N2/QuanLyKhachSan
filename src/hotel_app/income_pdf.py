"""PDF rendering for the monthly income report."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle


PDF_FONT_NAME = "IncomeStatisticsUnicode"


def _unicode_font_path() -> Path:
    configured_font = os.environ.get("INCOME_STATISTICS_PDF_FONT")
    candidates = [
        Path(configured_font) if configured_font else None,
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "A Unicode TrueType font is required to export Vietnamese income reports. "
        "Set INCOME_STATISTICS_PDF_FONT to its file path."
    )


def build_income_statistics_pdf(
    report_year: int,
    monthly_rows: Sequence[tuple[int, str]],
    formatted_annual_total: str,
) -> bytes:
    try:
        pdfmetrics.getFont(PDF_FONT_NAME)
    except KeyError:
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(_unicode_font_path())))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "IncomeStatisticsTitle",
        parent=styles["Title"],
        fontName=PDF_FONT_NAME,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#17324c"),
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    year_style = ParagraphStyle(
        "IncomeStatisticsYear",
        parent=styles["Normal"],
        fontName=PDF_FONT_NAME,
        fontSize=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#52667a"),
        spaceAfter=20,
    )
    table_data = [["Tháng", "Tổng tiền của tháng"]]
    table_data.extend(
        (f"Tháng {month}", total) for month, total in monthly_rows
    )
    table_data.append(("Tổng cộng", formatted_annual_total))
    report_table = Table(table_data, colWidths=(150, 365), repeatRows=1)
    report_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), PDF_FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#334b63")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f8fb")),
                ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_NAME),
                ("FONTNAME", (0, -1), (-1, -1), PDF_FONT_NAME),
                ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#17324c")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e4ebf1")),
                ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#cbd8e4")),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=48,
        bottomMargin=48,
        title=f"Thống kê thu nhập năm {report_year}",
    )
    document.build(
        [
            Paragraph("Thống kê thu nhập", title_style),
            Paragraph(f"Năm {report_year}", year_style),
            report_table,
        ]
    )
    return output.getvalue()
