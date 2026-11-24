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
from core.exceptions import LLMAuthenticationError, LLMForbiddenError
from core.schemas.validation import Finding, Severity
from ui import i18n

SEVERITY_ORDER = {
    Severity.critical: "critical",
    Severity.error: "error",
    Severity.warning: "warning",
    Severity.info: "info",
}


def page_header(title: str, description: str = "") -> None:
    """Render the standard page title and optional one-line description."""
    st.title(i18n.tx(title))
    if description:
        st.caption(i18n.tx(description))


def empty_state(
    message: str,
    *,
    title: str | None = None,
    hint: str = "",
) -> None:
    """Render the standard empty state for a page or section."""
    translated = i18n.tx(message)
    if title:
        st.info(translated, title=i18n.tx(title))
    else:
        st.info(translated)
    if hint:
        st.caption(i18n.tx(hint))


def metric_tile(
    label: str,
    value: str | float,
    *,
    help: str | None = None,
    delta: str | float | None = None,
) -> None:
    """Render one metric using the shared bordered-tile treatment."""
    st.metric(
        i18n.tx(label),
        value,
        delta=delta,
        help=i18n.tx(help) if help else None,
        border=True,
    )


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
    text = i18n.tx(label) if label else i18n.status_label(normalized)
    st.badge(text, color=colors.get(normalized, "blue"))


def section_header(
    title: str,
    *,
    description: str = "",
    divider: bool = False,
) -> None:
    """Render a consistent section heading and optional one-line description."""
    st.subheader(i18n.tx(title), divider=divider)
    if description:
        st.caption(i18n.tx(description))


def callout(
    text: str,
    *,
    kind: str = "info",
    title: str | None = None,
) -> None:
    """Render an information, warning, or model-estimate callout."""
    translated = i18n.tx(text)
    if kind == "warn":
        st.warning(translated, title=i18n.tx(title or i18n.t("common.review_required")))
    elif kind == "model_estimate":
        st.info(translated, title=i18n.tx(title or i18n.t("common.model_estimate")))
    elif kind == "info":
        st.info(translated, title=i18n.tx(title or i18n.t("common.note")))
    else:
        raise ValueError(f"Unsupported callout kind: {kind!r}")


def key_value_list(
    values: Sequence[tuple[str, object]],
    *,
    key_header: str | None = None,
    value_header: str | None = None,
) -> None:
    """Render key/value properties as a full-width, readable table."""
    first_header = i18n.tx(key_header) if key_header else i18n.t("common.field")
    second_header = i18n.tx(value_header) if value_header else i18n.t("common.value")
    rows = [
        {
            first_header: i18n.tx(key),
            second_header: "" if value is None else i18n.tx(str(value)),
        }
        for key, value in values
    ]
    st.dataframe(rows, hide_index=True, width="stretch")


def model_estimate_note(text: str, *, title: str = "Model scope") -> None:
    """Render the standard note that separates modeled estimates from measurements."""
    st.info(i18n.tx(text), title=i18n.tx(title))


def format_error(error: Exception) -> str:
    """Return a concise message for domain and validation errors."""
    if isinstance(error, LLMAuthenticationError):
        return i18n.t("error.llm.authentication", status=error.status_code)
    if isinstance(error, LLMForbiddenError):
        return i18n.t("error.llm.forbidden", status=error.status_code)
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
        st.success(i18n.tx(empty_message))
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
