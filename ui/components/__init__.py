"""Small presentation helpers shared by the planning pages.

This module is a package so page-specific components (for example the
structured requirements form) can live beside the shared helpers without
duplicating them.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.csv_safe import neutralize_cell
from core.schemas.validation import Finding, Severity

SEVERITY_ORDER = {
    Severity.critical: "critical",
    Severity.error: "error",
    Severity.warning: "warning",
    Severity.info: "info",
}


def page_header(title: str, description: str = "") -> None:
    """Render the standard page title and optional one-line description."""
    st.title(title)
    if description:
        st.caption(description)


def empty_state(
    message: str,
    *,
    title: str | None = None,
    hint: str = "",
) -> None:
    """Render the standard empty state for a page or section."""
    if title:
        st.info(message, title=title)
    else:
        st.info(message)
    if hint:
        st.caption(hint)


def model_estimate_note(text: str, *, title: str = "Model scope") -> None:
    """Render the standard note that separates modeled estimates from measurements."""
    st.info(text, title=title)


def format_error(error: Exception) -> str:
    """Return a concise message for domain and validation errors."""
    if isinstance(error, ValidationError):
        parts = [
            f"{'.'.join(str(item) for item in detail['loc'])}: {detail['msg']}"
            for detail in error.errors()[:3]
        ]
        return "; ".join(parts)
    return str(error)


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize a table for a download button, neutralizing formula cells."""
    safe = frame.map(neutralize_cell)
    return safe.to_csv(index=False).encode("utf-8")


def findings_frame(findings: Sequence[Finding]) -> pd.DataFrame:
    """Return findings as a display table."""
    return pd.DataFrame(
        [
            {
                "severity": SEVERITY_ORDER[finding.severity],
                "code": finding.code,
                "entities": ", ".join(finding.affected_entities),
                "explanation": finding.explanation,
                "remediation": finding.remediation,
            }
            for finding in findings
        ],
        columns=["severity", "code", "entities", "explanation", "remediation"],
    )


def render_findings(findings: Sequence[Finding], empty_message: str) -> None:
    """Render a findings table or a success message when there are none."""
    if not findings:
        st.success(empty_message)
        return
    st.dataframe(
        findings_frame(findings),
        hide_index=True,
        width="stretch",
    )


# Imported last: the health module reuses findings_frame from this module.
from .health import render_design_health

__all__ = [
    "SEVERITY_ORDER",
    "csv_bytes",
    "empty_state",
    "findings_frame",
    "format_error",
    "model_estimate_note",
    "page_header",
    "render_design_health",
    "render_findings",
]
