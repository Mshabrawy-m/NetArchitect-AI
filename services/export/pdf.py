"""PDF export for a report document using ReportLab.

The PDF is a rendering of the validated report document. It contains a title
block, a section list, section content, wrapping and paginating tables, page
numbers, a header and footer stamped from an injected clock, the exact
disclosure footer, and a bounded source-value appendix.

Built-in fonts are Latin-only. When the document contains text outside Latin,
every such character is replaced with ``?`` and a visible notice points the
reader to the Markdown or JSON export for the original text. Arabic shaping and
right-to-left layout are therefore not attempted.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config.limits import MAX_REPORT_TABLE_ROWS
from services.reporting.models import (
    DISCLOSURE_TEXT,
    KeyValueBlock,
    NoteBlock,
    ParagraphBlock,
    ReportDocument,
    TableBlock,
)

from .common import enforce_size

PDF_MARGIN = 40.0
PDF_TOP_MARGIN = 54.0
PDF_BOTTOM_MARGIN = 46.0
PDF_HEADER_META = "NetArchitect AI - software model"
MAX_PDF_CELL_CHARS = 1200
NON_LATIN_NOTICE = (
    "This PDF uses a Latin-only built-in font. {count} character(s) outside "
    "Latin were replaced with '?'. Use the Markdown or JSON export for the "
    "original text."
)
_PAGE_OBJECT = re.compile(rb"/Type\s*/Page\b(?!s)")


def _pdf_date(moment: datetime) -> str:
    """Return a fixed PDF date string for deterministic metadata."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("D:%Y%m%d%H%M%S+00'00'")


def _non_latin_count(text: str) -> int:
    return sum(1 for character in text if ord(character) > 127)


def _document_strings(document: ReportDocument):
    """Yield every string the PDF renders, for the font-coverage check."""
    yield document.title
    yield document.subtitle
    yield document.twin.name
    yield from document.labels
    yield document.model_note
    if document.ai is not None:
        yield document.ai.label
        yield document.ai.text
        yield document.ai.note
    for section in document.sections:
        yield section.title
        yield section.unavailable_reason
        yield section.producer_page
        for block in section.blocks:
            if isinstance(block, (ParagraphBlock, NoteBlock)):
                yield block.text
            elif isinstance(block, KeyValueBlock):
                yield block.title
                for item in block.items:
                    yield item.key
                    yield item.value
                    yield item.unit
            elif isinstance(block, TableBlock):
                yield block.title
                yield from block.columns
                for row in block.rows:
                    yield from row
    for record in document.values:
        yield record.key
        yield record.label
        yield record.display
        yield record.unit
        yield record.provenance.step
        yield record.provenance.tool


def _safe(text: str) -> str:
    """Replace non-Latin characters and escape ReportLab markup."""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    ascii_text = "".join(
        character
        if ord(character) < 128 and (character == "\n" or character >= " ")
        else "?"
        for character in normalized
    )
    return escape(ascii_text, {'"': "&quot;"})


def _cell_text(text: str) -> str:
    if len(text) > MAX_PDF_CELL_CHARS:
        return text[:MAX_PDF_CELL_CHARS] + " [cell truncated for PDF]"
    return text


def pdf_warnings(document: ReportDocument) -> tuple[str, ...]:
    """Return visible font-coverage warnings for ``document``."""
    count = sum(_non_latin_count(text) for text in _document_strings(document))
    if count == 0:
        return ()
    return (NON_LATIN_NOTICE.format(count=count),)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            alignment=0,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#333333"),
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            "ReportMeta",
            parent=base["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#444444"),
        ),
        "label": ParagraphStyle(
            "ReportLabel",
            parent=base["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#333333"),
            leftIndent=8,
            bulletIndent=0,
        ),
        "heading": ParagraphStyle(
            "ReportHeading",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=13.5,
            leading=17,
            spaceBefore=14,
            spaceAfter=6,
            textColor=colors.HexColor("#1f3b57"),
        ),
        "subheading": ParagraphStyle(
            "ReportSubheading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            spaceBefore=8,
            spaceAfter=3,
            textColor=colors.HexColor("#1f3b57"),
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["BodyText"],
            fontSize=9,
            leading=12.5,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["BodyText"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#444444"),
            spaceAfter=3,
        ),
        "caption": ParagraphStyle(
            "ReportCaption",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#555555"),
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "ReportCell",
            parent=base["BodyText"],
            fontSize=7,
            leading=8.6,
            splitLongWords=1,
        ),
        "cell_header": ParagraphStyle(
            "ReportCellHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8.6,
            textColor=colors.white,
        ),
        "notice": ParagraphStyle(
            "ReportNotice",
            parent=base["BodyText"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#7a3e00"),
            backColor=colors.HexColor("#fff4e5"),
            borderColor=colors.HexColor("#d9a25f"),
            borderWidth=0.5,
            borderPadding=5,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "note": ParagraphStyle(
            "ReportNote",
            parent=base["BodyText"],
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#333333"),
            leftIndent=8,
            borderPadding=3,
            spaceAfter=5,
        ),
    }


def _make_table(
    columns: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    styles: dict[str, ParagraphStyle],
) -> Table:
    data = [
        [Paragraph(_safe(column), styles["cell_header"]) for column in columns]
    ]
    for row in rows:
        data.append(
            [
                Paragraph(_safe(_cell_text(cell)), styles["cell"])
                for cell in row
            ]
        )
    available = A4[0] - 2 * PDF_MARGIN
    width = available / len(columns)
    table = Table(
        data,
        colWidths=[width] * len(columns),
        repeatRows=1,
        splitByRow=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b57")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8bfc7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
            ]
        )
    )
    return table


def _source_caption(provenance) -> Paragraph:
    return Paragraph(
        _safe(
            f"Source: {provenance.step} / {provenance.tool} / "
            f"twin {provenance.twin_version}"
        ),
        _STYLES["caption"],
    )


def _block_flowables(block, styles) -> list:
    if isinstance(block, ParagraphBlock):
        return [Paragraph(_safe(block.text), styles["body"])]
    if isinstance(block, NoteBlock):
        prefix = {
            "info": "Note",
            "warning": "Warning",
            "limitation": "Limitation",
        }[block.severity]
        return [
            Paragraph(
                _safe(f"{prefix}: {block.text}"),
                styles["note"],
            )
        ]
    if isinstance(block, KeyValueBlock):
        flowables: list = []
        if block.title:
            flowables.append(Paragraph(_safe(block.title), styles["subheading"]))
        rows = tuple(
            (item.key, f"{item.value} {item.unit}".strip(), item.provenance.step)
            for item in block.items
        )
        flowables.append(_make_table(("Key", "Value", "Step"), rows, styles))
        flowables.append(Spacer(1, 4))
        return flowables
    if isinstance(block, TableBlock):
        flowables = []
        if block.title:
            flowables.append(Paragraph(_safe(block.title), styles["subheading"]))
        flowables.append(_make_table(block.columns, block.rows, styles))
        if block.truncated:
            flowables.append(
                Paragraph(_safe(block.truncation_note()), styles["caption"])
            )
        flowables.append(_source_caption(block.provenance))
        flowables.append(Spacer(1, 4))
        return flowables
    raise TypeError(f"Unsupported report block: {type(block).__name__}")


_STYLES = _styles()


def _value_appendix(document: ReportDocument, styles) -> list:
    flowables: list = [
        PageBreak(),
        Paragraph("Appendix: source values", styles["heading"]),
        Paragraph(
            _safe(
                "Every number printed in this report is listed here with the "
                "step, tool, and twin fingerprint that produced it. The JSON "
                "export carries the complete registry."
            ),
            styles["body"],
        ),
    ]
    rows = tuple(
        (
            record.key,
            record.label,
            record.display,
            f"{record.provenance.step} / {record.provenance.tool}",
        )
        for record in document.values[:MAX_REPORT_TABLE_ROWS]
    )
    flowables.append(_make_table(("Key", "Label", "Value", "Source"), rows, styles))
    if len(document.values) > MAX_REPORT_TABLE_ROWS:
        flowables.append(
            Paragraph(
                _safe(
                    f"Showing first {MAX_REPORT_TABLE_ROWS} of "
                    f"{len(document.values)} values. The JSON export contains "
                    "every record."
                ),
                styles["caption"],
            )
        )
    return flowables


def _build_story(document: ReportDocument, styles, *, generated_at: datetime) -> list:
    story: list = [
        Paragraph(_safe(document.title), styles["title"]),
    ]
    if document.subtitle:
        story.append(Paragraph(_safe(document.subtitle), styles["subtitle"]))
    story.extend(
        [
            Paragraph(_safe(f"Twin: {document.twin.name}"), styles["meta"]),
            Paragraph(
                _safe(f"Twin fingerprint: {document.twin.fingerprint}"),
                styles["meta"],
            ),
            Paragraph(
                _safe(f"Generated at: {generated_at.isoformat()}"),
                styles["meta"],
            ),
            Paragraph(
                _safe(f"Report schema version: {document.schema_version}"),
                styles["meta"],
            ),
            Spacer(1, 6),
        ]
    )
    for label in document.labels:
        story.append(Paragraph(_safe(label), styles["label"], bulletText="-"))
    story.append(Spacer(1, 6))
    for warning in pdf_warnings(document):
        story.append(Paragraph(_safe(warning), styles["notice"]))
    story.append(Paragraph("Contents", styles["heading"]))
    for index, section in enumerate(document.sections, start=1):
        state = "available" if section.status.value == "available" else "not run"
        story.append(
            Paragraph(
                _safe(f"{index}. {section.title} ({state})"),
                styles["body"],
            )
        )
    for index, section in enumerate(document.sections, start=1):
        story.append(Paragraph(_safe(f"{index}. {section.title}"), styles["heading"]))
        if section.status.value == "not_run":
            story.extend(
                [
                    Paragraph(
                        _safe(
                            f"This section was not run. Reason: "
                            f"{section.unavailable_reason}"
                        ),
                        styles["body"],
                    ),
                    Paragraph(
                        _safe(f"Produced on: {section.producer_page}"),
                        styles["caption"],
                    ),
                ]
            )
            continue
        for block in section.blocks:
            story.extend(_block_flowables(block, styles))
    if document.ai is not None:
        story.append(Paragraph("AI-generated explanation", styles["heading"]))
        story.append(Paragraph(_safe(document.ai.label), styles["caption"]))
        if document.ai.text:
            story.append(Paragraph(_safe(document.ai.text), styles["body"]))
        else:
            story.append(
                Paragraph("No AI-written explanation is included.", styles["body"])
            )
        if document.ai.note:
            story.append(Paragraph(_safe(document.ai.note), styles["caption"]))
    story.extend(_value_appendix(document, styles))
    return story


def _numbered_canvas(
    *,
    header_meta: str,
    header_title: str,
    footer_text: str,
    pdf_date: str,
):
    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setDateFormatter(lambda *formats: pdf_date)
            self._saved_page_states: list[dict] = []

        def showPage(self) -> None:
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int) -> None:
            width, height = A4
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#444444"))
            self.drawString(PDF_MARGIN, height - 30, _safe(header_title))
            self.drawRightString(width - PDF_MARGIN, height - 30, _safe(header_meta))
            self.setStrokeColor(colors.HexColor("#b8bfc7"))
            self.setLineWidth(0.4)
            self.line(PDF_MARGIN, height - 34, width - PDF_MARGIN, height - 34)
            self.line(PDF_MARGIN, 34, width - PDF_MARGIN, 34)
            self.setFont("Helvetica", 7)
            self.drawString(PDF_MARGIN, 24, _safe(footer_text))
            self.drawRightString(
                width - PDF_MARGIN,
                24,
                _safe(f"Page {self._pageNumber} of {total}"),
            )
            self.restoreState()

    return NumberedCanvas


def pdf_page_count(data: bytes) -> int:
    """Return the number of page objects in a PDF byte stream."""
    return len(_PAGE_OBJECT.findall(data))


def to_pdf(
    document: ReportDocument,
    *,
    generated_at: datetime | None = None,
) -> bytes:
    """Render ``document`` as deterministic PDF bytes."""
    moment = generated_at or document.generated_at
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=PDF_TOP_MARGIN,
        bottomMargin=PDF_BOTTOM_MARGIN,
        title=document.title,
        author="NetArchitect AI",
        subject="Network design report",
        creator="NetArchitect AI",
        pageCompression=0,
        invariant=1,
    )
    doc.build(
        _build_story(document, _STYLES, generated_at=moment),
        canvasmaker=_numbered_canvas(
            header_meta=(
                f"{PDF_HEADER_META} | Generated {moment.isoformat()}"
            ),
            header_title=f"NetArchitect AI - {document.title}",
            footer_text=DISCLOSURE_TEXT,
            pdf_date=_pdf_date(moment),
        ),
    )
    return enforce_size(buffer.getvalue(), kind="PDF")


__all__ = [
    "MAX_PDF_CELL_CHARS",
    "NON_LATIN_NOTICE",
    "pdf_page_count",
    "pdf_warnings",
    "to_pdf",
]
