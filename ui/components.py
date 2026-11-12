"""Small presentation helpers shared by the planning pages."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.schemas.validation import Finding, Severity

SEVERITY_ORDER = {
    Severity.critical: "critical",
    Severity.error: "error",
    Severity.warning: "warning",
    Severity.info: "info",
}


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
    """Serialize a table for a download button."""
    return frame.to_csv(index=False).encode("utf-8")


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
