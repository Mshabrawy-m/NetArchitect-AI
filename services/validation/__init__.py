"""Unified deterministic validation for a digital twin.

Use :func:`build_design_health` as the single entry point. It aggregates the
existing schema, addressing, VLAN, DHCP, routing, capacity, and redundancy
checks; pages and tests must not re-implement those checks.
"""

from .constraints import constraint_findings
from .health import build_design_health, categorize_twin_finding
from .models import (
    BASIC_CHECK_NOTE,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    EXPENSIVE_CHECK_NOTE,
    SEVERITY_RANK,
    SKIPPED_EXPENSIVE_NOTE,
    CategoryFindings,
    DesignHealth,
    ValidationCategory,
    finding_sort_key,
)

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
    "build_design_health",
    "categorize_twin_finding",
    "constraint_findings",
    "finding_sort_key",
]
