"""Consistency checking for a report document (Phase 11a).

The checker treats the document's ``values`` appendix as the authoritative list
of sourced numbers. Every numeric token printed in prose, key/value items, or
table cells must match one of those recorded values. A tampered or fabricated
number therefore produces an ``orphan_number`` finding instead of passing
silently.

The checker also verifies that the required disclosure labels are present and
that every table and key/value item carries step, tool, and twin version.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .formatting import numeric_tokens, parse_display
from .models import (
    REQUIRED_LABELS,
    KeyValueBlock,
    NoteBlock,
    ParagraphBlock,
    ReportDocument,
    SectionStatus,
    TableBlock,
)


class ConsistencyCode(str, Enum):
    """Stable finding codes returned by the checker."""

    orphan_number = "orphan_number"
    missing_label = "missing_label"
    missing_provenance = "missing_provenance"
    empty_section = "empty_section"


class ConsistencySeverity(str, Enum):
    """Severity of a consistency finding."""

    error = "error"
    warning = "warning"


class ConsistencyFinding(BaseModel):
    """One consistency problem in a report document."""

    model_config = ConfigDict(extra="forbid")

    code: ConsistencyCode
    severity: ConsistencySeverity
    section_id: str = ""
    message: str
    token: str = ""


class ConsistencyReport(BaseModel):
    """Result of checking one report document."""

    model_config = ConfigDict(extra="forbid")

    findings: tuple[ConsistencyFinding, ...] = Field(default_factory=tuple)
    checked_numbers: int = Field(default=0, ge=0)
    checked_values: int = Field(default=0, ge=0)

    @property
    def ok(self) -> bool:
        """Return whether the report has no error-severity findings."""
        return not any(
            finding.severity is ConsistencySeverity.error
            for finding in self.findings
        )

    @property
    def errors(self) -> tuple[ConsistencyFinding, ...]:
        """Return only error-severity findings."""
        return tuple(
            finding
            for finding in self.findings
            if finding.severity is ConsistencySeverity.error
        )

    def summary(self) -> str:
        """Return a one-line result summary."""
        if self.ok:
            return (
                f"Consistent: {self.checked_numbers} numbers match "
                f"{self.checked_values} sourced values."
            )
        return (
            f"{len(self.errors)} consistency error(s) across "
            f"{self.checked_numbers} checked numbers."
        )


def _allowed_numbers(document: ReportDocument) -> set[float]:
    allowed: set[float] = set()
    for record in document.values:
        if record.numeric is not None:
            allowed.add(round(float(record.numeric), 6))
        parsed = parse_display(record.display)
        if parsed is not None:
            allowed.add(round(parsed, 6))
    return allowed


def check_consistency(document: ReportDocument) -> ConsistencyReport:
    """Check every printed number against the document's sourced values."""
    allowed = _allowed_numbers(document)
    findings: list[ConsistencyFinding] = []
    checked = 0

    def check_text(text: str, *, section_id: str, location: str) -> None:
        nonlocal checked
        for token in numeric_tokens(text):
            checked += 1
            if round(float(token), 6) in allowed:
                continue
            findings.append(
                ConsistencyFinding(
                    code=ConsistencyCode.orphan_number,
                    severity=ConsistencySeverity.error,
                    section_id=section_id,
                    token=token,
                    message=(
                        f"Number {token} in {location} does not match any "
                        f"sourced value."
                    ),
                )
            )

    def check_provenance(provenance, *, section_id: str, location: str) -> None:
        if not provenance.twin_version:
            findings.append(
                ConsistencyFinding(
                    code=ConsistencyCode.missing_provenance,
                    severity=ConsistencySeverity.warning,
                    section_id=section_id,
                    message=f"{location} has no twin version in its provenance.",
                )
            )

    for label in REQUIRED_LABELS:
        if label not in document.labels:
            findings.append(
                ConsistencyFinding(
                    code=ConsistencyCode.missing_label,
                    severity=ConsistencySeverity.error,
                    message=f"Required disclosure label is missing: {label!r}",
                )
            )

    check_text(document.model_note, section_id="document", location="disclosure")
    if document.ai is not None and document.ai.text:
        check_text(document.ai.text, section_id="ai", location="AI explanation")

    for record in document.values:
        check_provenance(
            record.provenance,
            section_id="values",
            location=f"value {record.key!r}",
        )

    for section in document.sections:
        if section.status is SectionStatus.not_run:
            continue
        if not section.blocks:
            findings.append(
                ConsistencyFinding(
                    code=ConsistencyCode.empty_section,
                    severity=ConsistencySeverity.warning,
                    section_id=section.id,
                    message="Section is marked available but contains no blocks.",
                )
            )
            continue
        for index, block in enumerate(section.blocks, start=1):
            location = f"section {section.id!r} block {index}"
            if isinstance(block, ParagraphBlock):
                check_text(block.text, section_id=section.id, location=location)
                if block.provenance is not None:
                    check_provenance(
                        block.provenance,
                        section_id=section.id,
                        location=location,
                    )
            elif isinstance(block, NoteBlock):
                check_text(block.text, section_id=section.id, location=location)
            elif isinstance(block, KeyValueBlock):
                for item in block.items:
                    check_text(
                        item.value,
                        section_id=section.id,
                        location=f"{location} key {item.key!r}",
                    )
                    check_provenance(
                        item.provenance,
                        section_id=section.id,
                        location=f"{location} key {item.key!r}",
                    )
            elif isinstance(block, TableBlock):
                check_provenance(
                    block.provenance,
                    section_id=section.id,
                    location=f"table {block.id!r}",
                )
                for row_index, row in enumerate(block.rows, start=1):
                    for cell in row:
                        check_text(
                            cell,
                            section_id=section.id,
                            location=f"table {block.id!r} row {row_index}",
                        )

    return ConsistencyReport(
        findings=tuple(findings),
        checked_numbers=checked,
        checked_values=len(document.values),
    )


__all__ = [
    "ConsistencyCode",
    "ConsistencyFinding",
    "ConsistencyReport",
    "ConsistencySeverity",
    "check_consistency",
]
