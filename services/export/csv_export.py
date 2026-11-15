"""CSV table export and in-memory ZIP bundle for a report document.

Only the tables named in :data:`CSV_TABLE_IDS` are exported. Values are copied
from the report's bounded tables; a table that omitted source rows keeps its
``Showing first N of M rows`` note in the bundle README rather than injecting a
non-data row into the CSV itself.

Encoding is UTF-8 with the RFC 4180 CRLF row terminator. The optional UTF-8 BOM
is documented in :data:`CSV_ENCODING_NOTE` and is off by default so spreadsheet
importers that do not strip a BOM receive clean headers.
"""

from __future__ import annotations

import codecs
import csv
import io
from dataclasses import dataclass

from services.reporting.models import ReportDocument, TableBlock

from .common import stable_zip

CSV_ENCODING_NOTE = (
    "CSV files are UTF-8 with CRLF row terminators. A UTF-8 BOM is written only "
    "when the caller requests it, for spreadsheet tools that need one."
)

# stable table id -> exported file name
CSV_TABLE_IDS: dict[str, str] = {
    "ip_plan": "ip_plan.csv",
    "vlan_assignments": "vlan_assignments.csv",
    "dhcp_scopes": "dhcp_scopes.csv",
    "routing_table": "routing_table.csv",
    "link_utilization": "link_utilization.csv",
    "findings": "findings.csv",
    "optimization_candidates": "optimization_candidates.csv",
}


@dataclass(frozen=True)
class CsvTable:
    """One exported CSV table with its source row count."""

    table_id: str
    filename: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    total_rows: int

    @property
    def truncated(self) -> bool:
        """Return whether the source table had more rows than were exported."""
        return self.total_rows > len(self.rows)

    def truncation_note(self) -> str:
        """Return the visible truncation note, or an empty string."""
        if not self.truncated:
            return ""
        return f"Showing first {len(self.rows)} of {self.total_rows} rows."

    def to_bytes(self, *, bom: bool = False) -> bytes:
        """Render one CSV table as UTF-8 bytes."""
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        payload = buffer.getvalue().encode("utf-8")
        if bom:
            payload = codecs.BOM_UTF8 + payload
        return payload


def _from_table(table: TableBlock) -> CsvTable:
    return CsvTable(
        table_id=table.id,
        filename=CSV_TABLE_IDS[table.id],
        columns=table.columns,
        rows=table.rows,
        total_rows=table.total_rows,
    )


def csv_tables(document: ReportDocument) -> tuple[CsvTable, ...]:
    """Return the supported tables present in ``document``, in document order."""
    return tuple(
        _from_table(table)
        for table in document.tables()
        if table.id in CSV_TABLE_IDS
    )


def _readme(document: ReportDocument, tables: tuple[CsvTable, ...], *, bom: bool) -> str:
    lines = [
        "NetArchitect AI report tables",
        "",
        f"Report: {document.title}",
        f"Twin: {document.twin.name}",
        f"Twin fingerprint: {document.twin.fingerprint}",
        f"Generated at: {document.generated_at.isoformat()}",
        "",
        CSV_ENCODING_NOTE,
        f"BOM: {'written' if bom else 'not written'}",
        "",
        "Tables in this archive:",
    ]
    if tables:
        for table in tables:
            lines.append(f"- {table.filename}: {len(table.rows)} rows")
            note = table.truncation_note()
            if note:
                lines.append(f"  {note}")
    else:
        lines.append("- None. This report has no IP plan, VLAN, DHCP, routing,")
        lines.append("  link utilization, findings, or optimization candidate table.")
    lines.extend(["", document.model_note, ""])
    return "\n".join(lines)


def to_csv_bundle(document: ReportDocument, *, bom: bool = False) -> bytes:
    """Build an in-memory ZIP containing the supported CSV tables and a README."""
    tables = csv_tables(document)
    files = [(table.filename, table.to_bytes(bom=bom)) for table in tables]
    files.append(("README.txt", _readme(document, tables, bom=bom).encode("utf-8")))
    return stable_zip(files, kind="CSV bundle")


__all__ = [
    "CSV_ENCODING_NOTE",
    "CSV_TABLE_IDS",
    "CsvTable",
    "csv_tables",
    "to_csv_bundle",
]
