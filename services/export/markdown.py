"""Markdown export for a report document.

The Markdown export is a readable rendering of the same typed document the JSON
export round-trips. It never re-derives a value: numbers, tables, notes, and
provenance are copied from :class:`~services.reporting.models.ReportDocument`.

The export is deterministic for a fixed document: there is no clock read, no
dictionary iteration over unordered data, and every list is already ordered by
the builder.
"""

from __future__ import annotations

from config.limits import MAX_REPORT_TABLE_ROWS
from services.reporting.models import (
    KeyValueBlock,
    NoteBlock,
    ParagraphBlock,
    ReportDocument,
    TableBlock,
)

from .common import enforce_size


def _escape_cell(value: str) -> str:
    """Escape one Markdown table cell."""
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _table_header(columns: tuple[str, ...]) -> list[str]:
    return [
        "| " + " | ".join(_escape_cell(column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]


def _source_line(provenance) -> str:
    return (
        f"_Source: {provenance.step} / {provenance.tool} / "
        f"twin `{provenance.twin_version}`._"
    )


def _key_value_block(block: KeyValueBlock) -> list[str]:
    lines: list[str] = []
    if block.title:
        lines.extend([f"**{block.title}**", ""])
    lines.extend(_table_header(("Key", "Value", "Source")))
    for item in block.items:
        source = f"{item.provenance.step} / {item.provenance.tool}"
        lines.append(
            "| "
            + " | ".join(
                _escape_cell(value)
                for value in (item.key, f"{item.value} {item.unit}".strip(), source)
            )
            + " |"
        )
    lines.append("")
    return lines


def _table_block(block: TableBlock) -> list[str]:
    lines: list[str] = []
    if block.title:
        lines.extend([f"**{block.title}**", ""])
    lines.extend(_table_header(block.columns))
    for row in block.rows:
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in row) + " |")
    lines.append("")
    if block.truncated:
        lines.extend([f"_{block.truncation_note()}_", ""])
    lines.append(_source_line(block.provenance))
    lines.append("")
    return lines


def _note_block(block: NoteBlock) -> list[str]:
    label = {
        "info": "Note",
        "warning": "Warning",
        "limitation": "Limitation",
    }[block.severity]
    return [f"> **{label}:** {block.text}", ""]


def _block_lines(block) -> list[str]:
    if isinstance(block, ParagraphBlock):
        return [block.text, ""]
    if isinstance(block, NoteBlock):
        return _note_block(block)
    if isinstance(block, KeyValueBlock):
        return _key_value_block(block)
    if isinstance(block, TableBlock):
        return _table_block(block)
    raise TypeError(f"Unsupported report block: {type(block).__name__}")


def _section_lines(document: ReportDocument) -> list[str]:
    lines: list[str] = []
    for index, section in enumerate(document.sections, start=1):
        lines.extend([f"## {index}. {section.title}", ""])
        if section.status.value == "not_run":
            lines.extend(
                [
                    "This section was not run.",
                    "",
                    f"- Reason: {section.unavailable_reason}",
                    f"- Produced on: {section.producer_page}",
                    "",
                ]
            )
            continue
        for block in section.blocks:
            lines.extend(_block_lines(block))
    return lines


def _ai_lines(document: ReportDocument) -> list[str]:
    if document.ai is None:
        return []
    lines = ["## AI-generated explanation", ""]
    lines.append(f"> {document.ai.label}")
    lines.append("")
    if document.ai.text:
        lines.extend([document.ai.text, ""])
    else:
        lines.append("No AI-written explanation is included.")
        lines.append("")
    if document.ai.note:
        lines.extend([f"_{document.ai.note}_", ""])
    return lines


def _values_lines(document: ReportDocument) -> list[str]:
    if not document.values:
        return []
    lines = ["## Value provenance appendix", ""]
    lines.extend(
        _table_header(
            ("Key", "Label", "Value", "Unit", "Step", "Tool", "Twin version")
        )
    )
    shown = document.values[:MAX_REPORT_TABLE_ROWS]
    for record in shown:
        lines.append(
            "| "
            + " | ".join(
                _escape_cell(value)
                for value in (
                    record.key,
                    record.label,
                    record.display,
                    record.unit,
                    record.provenance.step,
                    record.provenance.tool,
                    record.provenance.twin_version,
                )
            )
            + " |"
        )
    lines.append("")
    if len(document.values) > len(shown):
        lines.extend(
            [
                (
                    f"_Showing first {len(shown)} of {len(document.values)} values. "
                    "The JSON export contains every record._"
                ),
                "",
            ]
        )
    lines.append(
        "_This appendix is the report's sourced-number registry. The JSON export "
        "contains the same records in machine-readable form._"
    )
    lines.append("")
    return lines


def to_markdown(document: ReportDocument) -> bytes:
    """Render ``document`` as UTF-8 Markdown bytes."""
    lines: list[str] = [
        f"# {document.title}",
        "",
    ]
    if document.subtitle:
        lines.extend([document.subtitle, ""])
    lines.extend(
        [
            f"- **Twin:** {document.twin.name}",
            f"- **Twin fingerprint:** `{document.twin.fingerprint}`",
            f"- **Twin created at:** {document.twin.created_at.isoformat()}",
            f"- **Report generated at:** {document.generated_at.isoformat()}",
            f"- **Report schema version:** {document.schema_version}",
            "",
            "## Disclosure labels",
            "",
        ]
    )
    for label in document.labels:
        lines.append(f"- {label}")
    lines.extend(["", "## Contents", ""])
    for index, section in enumerate(document.sections, start=1):
        state = "available" if section.status.value == "available" else "not run"
        lines.append(f"{index}. {section.title} ({state})")
    lines.append("")
    lines.extend(_section_lines(document))
    lines.extend(_ai_lines(document))
    lines.extend(_values_lines(document))
    lines.extend(["---", "", document.model_note, ""])
    payload = "\n".join(lines).encode("utf-8")
    return enforce_size(payload, kind="Markdown")


__all__ = ["to_markdown"]
