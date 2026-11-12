"""Validation finding domain models.

Findings produced by validation rules and a report that aggregates them.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Severity levels for a validation finding."""

    info = "info"  # Informational note, no action required.
    warning = "warning"  # Potential issue worth attention.
    error = "error"  # A problem that should be fixed.
    critical = "critical"  # A blocking problem that invalidates the design.


class Finding(BaseModel):
    """A single validation finding about one or more entities."""

    severity: Severity = Field(description="Severity of the finding.")
    code: str = Field(description="Stable machine-readable code identifying the rule.")
    affected_entities: list[str] = Field(
        default_factory=list,
        description="Ids of entities the finding concerns.",
    )
    explanation: str = Field(description="Human-readable explanation of the finding.")
    remediation: str = Field(
        default="",
        description="Suggested remediation, if any.",
    )


class ValidationReport(BaseModel):
    """An aggregate validation report over a set of findings."""

    findings: list[Finding] = Field(
        default_factory=list,
        description="Findings produced by validation.",
    )
    is_valid: bool = Field(
        default=True,
        description="Whether the validated artifact is considered valid.",
    )
    summary: str = Field(
        default="",
        description="Human-readable summary of the report.",
    )
