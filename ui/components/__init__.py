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


def metric_tile(
    label: str,
    value: str | float,
    *,
    help: str | None = None,
    delta: str | float | None = None,
) -> None:
    """Render one metric using the shared bordered-tile treatment."""
    st.metric(label, value, delta=delta, help=help, border=True)


def status_badge(status: str, *, label: str | None = None) -> None:
    """Render a text status with a semantic color; never color-only."""
    colors = {
        "done": "green",
        "complete": "green",
        "ok": "green",
        "incomplete": "grey",
        "stale": "orange",
        "warning": "orange",
        "warn": "orange",
        "critical": "red",
        "error": "red",
        "info": "blue",
    }
    normalized = status.lower()
    text = label or status.replace("_", " ").capitalize()
    st.badge(text, color=colors.get(normalized, "blue"))


def section_header(
    title: str,
    *,
    description: str = "",
    divider: bool = False,
) -> None:
    """Render a consistent section heading and optional one-line description."""
    st.subheader(title, divider=divider)
    if description:
        st.caption(description)


def callout(
    text: str,
    *,
    kind: str = "info",
    title: str | None = None,
) -> None:
    """Render an information, warning, or model-estimate callout."""
    if kind == "warn":
        st.warning(text, title=title or "Review required")
    elif kind == "model_estimate":
        st.info(text, title=title or "Model estimate")
    elif kind == "info":
        st.info(text, title=title or "Note")
    else:
        raise ValueError(f"Unsupported callout kind: {kind!r}")


def key_value_list(
    values: Sequence[tuple[str, object]],
    *,
    key_header: str = "Field",
    value_header: str = "Value",
) -> None:
    """Render key/value properties as a full-width, readable table."""
    rows = [
        {key_header: key, value_header: "" if value is None else str(value)}
        for key, value in values
    ]
    st.dataframe(rows, hide_index=True, width="stretch")


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
    "callout",
    "csv_bytes",
    "empty_state",
    "findings_frame",
    "format_error",
    "key_value_list",
    "metric_tile",
    "model_estimate_note",
    "page_header",
    "render_design_health",
    "render_findings",
    "section_header",
    "status_badge",
]
