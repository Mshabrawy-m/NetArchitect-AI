"""Project progress strip derived only from read-only session accessors.

The six steps describe workflow completion, not pass/fail. A step is ``Done``
when the matching result exists, ``Incomplete`` when it does not, and ``Stale``
when a stored result was produced from a different twin revision. No engine is
run here and no session value is created, migrated, or replaced.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from simulation import twin_fingerprint
from ui import state
from ui.components import status_badge
from ui.navigation import PAGE_FILES

DONE = "done"
INCOMPLETE = "incomplete"
STALE = "stale"

_STEP_PAGES: tuple[tuple[str, str], ...] = (
    ("Design", "AI Network Designer"),
    ("Addressing", "IP Addressing & Subnetting"),
    ("Validate", "Digital Twin"),
    ("Simulate", "Simulation Lab"),
    ("Optimize", "Optimization Center"),
    ("Report", "Reports & Documentation"),
)


@dataclass(frozen=True)
class ProgressStep:
    """One workflow step with its real-session evidence."""

    key: str
    label: str
    status: str
    page_file: str
    detail: str


def _source_status(
    fingerprint: str,
    current_fingerprint: str,
    *,
    has_result: bool,
    can_be_stale: bool = True,
) -> str:
    """Classify a stored result against the current twin fingerprint."""
    if not has_result:
        return INCOMPLETE
    if can_be_stale and fingerprint and fingerprint != current_fingerprint:
        return STALE
    return DONE


def build_progress() -> tuple[ProgressStep, ...]:
    """Compute the six progress steps from bounded, read-only session data."""
    twin = state.peek_twin()
    current = twin_fingerprint(twin) if twin is not None else ""

    topology = twin.topology if twin is not None else None
    devices = len(topology.devices) if topology is not None else 0
    links = len(topology.links) if topology is not None else 0
    design_status = DONE if devices > 0 else INCOMPLETE
    design_detail = (
        f"{devices} devices, {links} links in this session."
        if devices > 0
        else "No design twin with devices is loaded."
    )

    addressing = twin.addressing if twin is not None else None
    subnet_count = len(addressing.subnets) if addressing is not None else 0
    vlan_count = len(addressing.vlan_plans) if addressing is not None else 0
    vlsm = state.peek_addressing_result()
    has_addressing = subnet_count > 0 or vlan_count > 0
    addressing_status = DONE if has_addressing else INCOMPLETE
    if has_addressing:
        addressing_detail = f"{subnet_count} subnet(s), {vlan_count} VLAN plan(s) saved in the twin."
    elif vlsm is not None:
        addressing_detail = f"{len(vlsm.allocations)} VLSM block(s) computed but not saved in the twin."
    else:
        addressing_detail = "No addressing plan in the current twin."

    check = state.peek_addressing_check()
    flows = state.peek_security_flows()
    check_fingerprint = (
        state.peek_addressing_check_fingerprint(check) if check is not None else ""
    )
    validate_status = _source_status(
        check_fingerprint,
        current,
        has_result=check is not None or bool(flows),
    )
    if check is not None:
        findings = len(check.findings)
        validate_detail = (
            f"Subnet check retained with {findings} finding(s)."
            if validate_status == DONE
            else "Subnet check was run on a different twin revision."
        )
    elif flows:
        validate_detail = f"{len(flows)} modeled flow check(s) retained."
    else:
        validate_detail = "No validation result retained in this session."

    scenarios = state.peek_simulation_runs()
    scenario = scenarios[-1] if scenarios else None
    simulate_status = _source_status(
        scenario.baseline_twin.fingerprint if scenario is not None else "",
        current,
        has_result=scenario is not None,
    )
    if scenario is None:
        simulate_detail = "No scenario run retained in this session."
    elif simulate_status == DONE:
        simulate_detail = f"Latest run: {scenario.scenario.name}."
    else:
        simulate_detail = "Latest scenario run used a different twin revision."

    optimizations = state.peek_optimization_runs()
    optimization = optimizations[-1] if optimizations else None
    optimization_fingerprint = (
        state.peek_optimization_source_fingerprint(optimization)
        if optimization is not None
        else ""
    )
    optimize_status = _source_status(
        optimization_fingerprint,
        current,
        has_result=optimization is not None,
    )
    if optimization is None:
        optimize_detail = "No optimization run retained in this session."
    elif optimize_status == DONE:
        optimize_detail = f"{optimization.algorithm.value} run retained."
    else:
        optimize_detail = "Latest optimization run used a different twin revision."

    report_times = state.peek_report_times()
    report_status = _source_status(
        current,
        current,
        has_result=current in report_times,
        can_be_stale=False,
    )
    if report_status == INCOMPLETE and report_times:
        report_status = STALE
    if report_status == DONE:
        report_detail = "Report prepared for the current twin."
    elif report_status == STALE:
        report_detail = "Report was prepared for a different twin revision."
    else:
        report_detail = "No report prepared in this session."

    statuses = (
        design_status,
        addressing_status,
        validate_status,
        simulate_status,
        optimize_status,
        report_status,
    )
    details = (
        design_detail,
        addressing_detail,
        validate_detail,
        simulate_detail,
        optimize_detail,
        report_detail,
    )
    return tuple(
        ProgressStep(
            key=label.lower(),
            label=label,
            status=status,
            page_file=PAGE_FILES[page],
            detail=detail,
        )
        for (label, page), status, detail in zip(
            _STEP_PAGES, statuses, details, strict=True
        )
    )


def render_progress(*, compact: bool = False) -> None:
    """Render the progress strip above the selected page."""
    steps = build_progress()
    with st.container(border=True):
        st.caption("Project progress")
        columns = st.columns(len(steps))
        for index, (column, step) in enumerate(zip(columns, steps, strict=True)):
            with column:
                st.page_link(
                    step.page_file,
                    label=f"{index + 1}. {step.label}",
                    help=step.detail,
                )
                status_badge(step.status)
                if not compact:
                    st.caption(step.detail)


__all__ = ["DONE", "INCOMPLETE", "STALE", "ProgressStep", "build_progress", "render_progress"]
