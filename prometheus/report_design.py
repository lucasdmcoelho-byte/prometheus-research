"""Visual primitives for the single PROMETHEUS PDF reporting engine.

This module deliberately contains presentation concerns only.  It does not
derive research facts, scores, recommendations, or editorial decisions.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle


PAGE_SIZE = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 17 * mm
MARGIN_BOTTOM = 17 * mm
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN_X
GRID_COLUMNS = 12
GRID_GUTTER = 2.2 * mm

PALETTE = {
    "paper": colors.HexColor("#F7F4EE"),
    "white": colors.HexColor("#FFFFFF"),
    "navy": colors.HexColor("#10233F"),
    "navy_2": colors.HexColor("#193A5A"),
    "blue": colors.HexColor("#2D5D7B"),
    "amber": colors.HexColor("#D79A2B"),
    "amber_soft": colors.HexColor("#F4E7C8"),
    "green": colors.HexColor("#237A57"),
    "green_soft": colors.HexColor("#DCECE4"),
    "red": colors.HexColor("#B3473D"),
    "red_soft": colors.HexColor("#F1DEDA"),
    "ink": colors.HexColor("#1C2733"),
    "slate": colors.HexColor("#5B6675"),
    "muted": colors.HexColor("#7B8490"),
    "line": colors.HexColor("#D8D3C9"),
    "card": colors.HexColor("#EFECE5"),
}


@lru_cache(maxsize=1)
def register_report_fonts() -> dict[str, str]:
    """Use ReportLab's stable WinAnsi core family for searchable Portuguese.

    The previous DejaVu TrueType subset rendered correctly but produced a
    broken ToUnicode map with ReportLab 5 in the supported desktop runtime.
    The report uses only Portuguese/WinAnsi glyphs, so the core family gives
    deterministic rendering and clean copy/search extraction.
    """
    return {
        "regular": "Helvetica",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
        "bold_italic": "Helvetica-BoldOblique",
    }


@lru_cache(maxsize=1)
def report_styles() -> dict[str, ParagraphStyle]:
    fonts = register_report_fonts()
    sample = getSampleStyleSheet()
    return {
        "cover_eyebrow": ParagraphStyle(
            "CoverEyebrow",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=7.5,
            leading=9,
            textColor=PALETTE["amber"],
            spaceAfter=4,
        ),
        "cover_ticker": ParagraphStyle(
            "CoverTicker",
            parent=sample["Title"],
            fontName=fonts["bold"],
            fontSize=30,
            leading=32,
            textColor=PALETTE["white"],
            spaceAfter=4,
        ),
        "cover_company": ParagraphStyle(
            "CoverCompany",
            parent=sample["BodyText"],
            fontName=fonts["regular"],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#E8EDF2"),
        ),
        "h1": ParagraphStyle(
            "ReportH1",
            parent=sample["Heading1"],
            fontName=fonts["bold"],
            fontSize=17,
            leading=20,
            textColor=PALETTE["navy"],
            spaceBefore=2,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=sample["Heading2"],
            fontName=fonts["bold"],
            fontSize=10.5,
            leading=13,
            textColor=PALETTE["navy_2"],
            spaceBefore=6,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "kicker": ParagraphStyle(
            "ReportKicker",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=6.8,
            leading=8,
            textColor=PALETTE["amber"],
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=sample["BodyText"],
            fontName=fonts["regular"],
            fontSize=8.5,
            leading=11.2,
            textColor=PALETTE["ink"],
            spaceAfter=5,
            allowWidows=0,
            allowOrphans=0,
        ),
        "body_bold": ParagraphStyle(
            "ReportBodyBold",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=8.5,
            leading=11.2,
            textColor=PALETTE["ink"],
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=sample["BodyText"],
            fontName=fonts["regular"],
            fontSize=7.1,
            leading=9.2,
            textColor=PALETTE["slate"],
            spaceAfter=3,
            allowWidows=0,
            allowOrphans=0,
        ),
        "small_bold": ParagraphStyle(
            "ReportSmallBold",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=7.1,
            leading=9.2,
            textColor=PALETTE["ink"],
            spaceAfter=2,
        ),
        "micro": ParagraphStyle(
            "ReportMicro",
            parent=sample["BodyText"],
            fontName=fonts["regular"],
            fontSize=7.0,
            leading=8.3,
            textColor=PALETTE["slate"],
            spaceAfter=1.5,
            allowWidows=0,
            allowOrphans=0,
        ),
        "table_header": ParagraphStyle(
            "ReportTableHeader",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=7.0,
            leading=8.3,
            textColor=PALETTE["white"],
            spaceAfter=0,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=6.2,
            leading=7.5,
            textColor=PALETTE["muted"],
            alignment=TA_LEFT,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=sample["BodyText"],
            fontName=fonts["bold"],
            fontSize=13,
            leading=15,
            textColor=PALETTE["navy"],
            alignment=TA_LEFT,
        ),
        "metric_note": ParagraphStyle(
            "MetricNote",
            parent=sample["BodyText"],
            fontName=fonts["regular"],
            fontSize=6.2,
            leading=7.5,
            textColor=PALETTE["slate"],
            alignment=TA_LEFT,
        ),
        "center": ParagraphStyle(
            "ReportCenter",
            parent=sample["BodyText"],
            fontName=fonts["regular"],
            fontSize=7.2,
            leading=9,
            textColor=PALETTE["ink"],
            alignment=TA_CENTER,
        ),
    }


def grid_widths(spans: Sequence[int], total_width: float = CONTENT_WIDTH, gutter: float = GRID_GUTTER) -> list[float]:
    """Return physical widths for spans on the canonical 12-column grid."""

    if not spans or any(span <= 0 for span in spans) or sum(spans) != GRID_COLUMNS:
        raise ValueError("Grid spans must be positive and sum to 12")
    usable = total_width - gutter * (len(spans) - 1)
    unit = usable / GRID_COLUMNS
    return [unit * span for span in spans]


def section_heading(title: str, eyebrow: str | None = None) -> list[Any]:
    styles = report_styles()
    flows: list[Any] = []
    if eyebrow:
        flows.append(Paragraph(eyebrow.upper(), styles["kicker"]))
    flows.append(Paragraph(title, styles["h1"]))
    return flows


def metric_cards(cards: Sequence[tuple[str, str, str]], total_width: float = CONTENT_WIDTH) -> Table:
    """Create 3 or 4 equal metric cards on the 12-column grid."""

    if len(cards) not in {2, 3, 4}:
        raise ValueError("Metric card rows support 2, 3, or 4 cards")
    spans = {2: [6, 6], 3: [4, 4, 4], 4: [3, 3, 3, 3]}[len(cards)]
    styles = report_styles()
    cells = []
    for label, value, note in cards:
        cells.append([
            Paragraph(label.upper(), styles["metric_label"]),
            Spacer(1, 2),
            Paragraph(value, styles["metric_value"]),
            Spacer(1, 1),
            Paragraph(note, styles["metric_note"]),
        ])
    table = Table([cells], colWidths=grid_widths(spans, total_width), hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALETTE["card"]),
        ("BOX", (0, 0), (-1, -1), 0.45, PALETTE["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, PALETTE["paper"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def callout(title: str, body: str, tone: str = "neutral", width: float = CONTENT_WIDTH) -> Table:
    styles = report_styles()
    background = {
        "positive": PALETTE["green_soft"],
        "negative": PALETTE["red_soft"],
        "warning": PALETTE["amber_soft"],
        "neutral": PALETTE["card"],
    }.get(tone, PALETTE["card"])
    accent = {
        "positive": PALETTE["green"],
        "negative": PALETTE["red"],
        "warning": PALETTE["amber"],
        "neutral": PALETTE["blue"],
    }.get(tone, PALETTE["blue"])
    content = [[Paragraph(title.upper(), styles["small_bold"])], [Paragraph(body, styles["body"])]]
    table = Table(content, colWidths=[width], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
    ]))
    return table


def bullet_paragraphs(items: Iterable[str], style_name: str = "body", limit: int | None = None) -> list[Paragraph]:
    styles = report_styles()
    selected = list(items)
    if limit is not None:
        selected = selected[:limit]
    return [Paragraph(f"- {item}", styles[style_name]) for item in selected]


def table_style(header_background: Any | None = None, compact: bool = False) -> TableStyle:
    fonts = register_report_fonts()
    header = header_background or PALETTE["navy"]
    font_size = 6.4 if compact else 7.1
    padding = 2 if compact else 5
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header),
        ("TEXTCOLOR", (0, 0), (-1, 0), PALETTE["white"]),
        ("FONTNAME", (0, 0), (-1, 0), fonts["bold"]),
        ("FONTNAME", (0, 1), (-1, -1), fonts["regular"]),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEADING", (0, 0), (-1, -1), font_size + 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALETTE["white"], PALETTE["paper"]]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, PALETTE["line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ])
