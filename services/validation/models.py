"""Typed result of the unified design-health validation pass.

The individual engines already return :class:`~core.schemas.validation.Finding`
objects. This module adds only the cross-cutting presentation layer: a stable
category per finding, severity ordering, and a bounded cost/coverage note.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.validation import Finding, Severity


class ValidationCategory(str, Enum):
    """Category of a design-health finding."""

    schema = "schema"
    topology = "topology"
    addressing = "addressing"
    vlan = "vlan"
    dhcp = "dhcp"
    routing = "routing"
    capacity = "capacity"
    redundancy = "redundancy"
    security = "security"
    constraints = "constraints"
    references = "references"


# Presentation order: structural problems first, then data consistency.
CATEGORY_ORDER: tuple[ValidationCategory, ...] = (
    ValidationCategory.schema,
    ValidationCategory.topology,
    ValidationCategory.addressing,
    ValidationCategory.vlan,
    ValidationCategory.dhcp,
    ValidationCategory.routing,
    ValidationCategory.capacity,
    ValidationCategory.redundancy,
    ValidationCategory.security,
    ValidationCategory.constraints,
    ValidationCategory.references,
)

CATEGORY_LABELS: dict[ValidationCategory, str] = {
    ValidationCategory.schema: "Schema",
    ValidationCategory.topology: "Topology connectivity",
    ValidationCategory.addressing: "IP addressing",
    ValidationCategory.vlan: "VLAN consistency",
    ValidationCategory.dhcp: "DHCP pools",
    ValidationCategory.routing: "Routing reachability",
    ValidationCategory.capacity: "Capacity and utilization",
    ValidationCategory.redundancy: "Redundancy",
    ValidationCategory.security: "Design-time security",
    ValidationCategory.constraints: "User-defined constraints",
    ValidationCategory.references: "Stale references",
}

SEVERITY_RANK: dict[Severity, int] = {
    Severity.critical: 0,
    Severity.error: 1,
    Severity.warning: 2,
    Severity.info: 3,
}

CATEGORY_INDEX: dict[ValidationCategory, int] = {
    category: index for index, category in enumerate(CATEGORY_ORDER)
}

BASIC_CHECK_NOTE = (
    "Basic checks cover schema and references, addressing, VLAN, DHCP, "
    "per-demand routing, one capacity evaluation, and supplied design-time "
    "security findings."
)
EXPENSIVE_CHECK_NOTE = (
    "Expensive checks add all-pairs reachability (one Dijkstra search per "
    "device) and redundancy analysis (one removal analysis per device and link)."
)
SKIPPED_EXPENSIVE_NOTE = (
    "All-pairs reachability and redundancy analysis were skipped. They run one "
    "Dijkstra search per device and one removal analysis per device and link, so "
    "enable expensive checks only when a full structural review is needed."
)


def finding_sort_key(
    item: tuple[ValidationCategory, Finding],
) -> tuple[int, int, str, tuple[str, ...]]:
    """Return the deterministic display order for a categorized finding."""
    category, finding = item
    return (
        SEVERITY_RANK[finding.severity],
        CATEGORY_INDEX[category],
        finding.code,
        tuple(finding.affected_entities),
    )


class CategoryFindings(BaseModel):
    """Findings for one validation category, severity-sorted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: ValidationCategory
    findings: tuple[Finding, ...] = Field(default_factory=tuple)


class DesignHealth(BaseModel):
    """The complete deterministic health report for one digital twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[Finding, ...] = Field(
        default_factory=tuple,
        description="Every finding, sorted by severity then category.",
    )
    groups: tuple[CategoryFindings, ...] = Field(
        default_factory=tuple,
        description="Findings grouped by category, in presentation order.",
    )
    include_expensive: bool = Field(
        description="Whether all-pairs routing and redundancy checks ran.",
    )
    is_valid: bool = Field(
        description="False when any finding is an error or critical.",
    )
    summary: str = Field(default="", description="One-line human-readable summary.")
    notes: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Coverage and cost notes for the checks that ran.",
    )
    elapsed_seconds: float = Field(
        default=0.0,
        ge=0,
        description="Wall-clock time spent building this report, in seconds.",
    )

    @property
    def by_category(self) -> dict[ValidationCategory, tuple[Finding, ...]]:
        """Return findings keyed by category, including empty categories."""
        return {group.category: group.findings for group in self.groups}

    def findings_for(self, category: ValidationCategory) -> tuple[Finding, ...]:
        """Return the severity-sorted findings for one category."""
        for group in self.groups:
            if group.category is category:
                return group.findings
        return ()

    def findings_in(
        self,
        categories: Iterable[ValidationCategory],
    ) -> tuple[Finding, ...]:
        """Return severity-sorted findings restricted to the given categories."""
        wanted = set(categories)
        selected: list[tuple[ValidationCategory, Finding]] = [
            (group.category, finding)
            for group in self.groups
            if group.category in wanted
            for finding in group.findings
        ]
        selected.sort(key=finding_sort_key)
        return tuple(finding for _, finding in selected)

    def count(self, severity: Severity) -> int:
        """Return the number of findings at one severity."""
        return sum(1 for finding in self.findings if finding.severity is severity)


__all__ = [
    "BASIC_CHECK_NOTE",
    "CATEGORY_LABELS",
    "CATEGORY_ORDER",
    "EXPENSIVE_CHECK_NOTE",
    "SEVERITY_RANK",
    "SKIPPED_EXPENSIVE_NOTE",
    "CategoryFindings",
    "DesignHealth",
    "ValidationCategory",
    "finding_sort_key",
]
