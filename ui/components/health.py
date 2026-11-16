"""Shared design-health panel used by the Dashboard and Digital Twin pages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import streamlit as st

from core.schemas.validation import Severity
from digital_twin import DigitalTwin
from services.validation import CATEGORY_LABELS, DesignHealth
from ui.cache import cached_design_health, twin_payload

from . import findings_frame


def render_design_health(
    twin: DigitalTwin,
    *,
    include_expensive: bool = False,
    constraints: Sequence[str] | Iterable[str] = (),
) -> DesignHealth:
    """Render the single design-health panel and return its report."""
    constraint_list = tuple(constraints)
    health = cached_design_health(
        twin_payload(twin),
        include_expensive,
        constraint_list,
    )

    with st.container(border=True):
        st.subheader("Design health")
        counts = st.columns(4)
        for column, severity in zip(
            counts,
            (Severity.critical, Severity.error, Severity.warning, Severity.info),
            strict=True,
        ):
            column.metric(severity.value.capitalize(), health.count(severity))

        if health.is_valid:
            st.success(health.summary)
        else:
            st.error(health.summary)
        st.caption(f"Validated in {health.elapsed_seconds:.2f}s.")

        shown = 0
        for group in health.groups:
            if not group.findings:
                continue
            shown += len(group.findings)
            label = CATEGORY_LABELS[group.category]
            with st.expander(
                f"{label} ({len(group.findings)})",
                expanded=any(
                    finding.severity in {Severity.critical, Severity.error}
                    for finding in group.findings
                ),
            ):
                st.dataframe(
                    findings_frame(group.findings),
                    hide_index=True,
                    width="stretch",
                )
        if shown == 0:
            st.caption("No findings. Every configured check passed.")

        with st.expander("Checks and cost"):
            for note in health.notes:
                st.caption(note)
            if constraint_list:
                st.caption(
                    "Constraints are checked only in the documented forms; "
                    "unrecognized text is reported as not machine-checkable."
                )
    return health


__all__ = ["render_design_health"]
