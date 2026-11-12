"""IP addressing and subnetting page.

Presentation only: CIDR arithmetic, VLSM allocation, utilization, and
validation are delegated to :mod:`network.addressing`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.exceptions import NetArchitectError
from core.schemas.addressing import AddressingPlan, Subnet
from network.addressing import (
    UtilizationEntry,
    VlsmRequirement,
    VlsmResult,
    allocate_vlsm,
    allocation_rows,
    build_utilization_report,
    calculate_subnet,
    cidr_rows,
    validate_addressing,
)
from ui import state
from ui.components import csv_bytes, findings_frame, format_error, render_findings

DEFAULT_REQUIREMENTS = pd.DataFrame(
    [
        {"name": "engineering", "required_hosts": 100},
        {"name": "sales", "required_hosts": 50},
        {"name": "operations", "required_hosts": 25},
        {"name": "finance", "required_hosts": 10},
        {"name": "guest", "required_hosts": 2},
    ]
)

DEFAULT_CHECK_SUBNETS = pd.DataFrame(
    [
        {"name": "core", "network": "10.0.0.0/24"},
        {"name": "branch", "network": "10.0.0.128/25"},
        {"name": "guest", "network": "10.0.1.0/24"},
    ]
)


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def _whole_number(value: object, label: str) -> int:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError(f"{label} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a whole number.") from error
    if number < 0 or not number.is_integer():
        raise ValueError(f"{label} must be a non-negative whole number.")
    return int(number)


def _to_requirements(frame: pd.DataFrame) -> list[VlsmRequirement]:
    requirements: list[VlsmRequirement] = []
    for position, (_, row) in enumerate(frame.iterrows(), start=1):
        name = _text(row["name"])
        raw_hosts = row["required_hosts"]
        if not name and (raw_hosts is None or pd.isna(raw_hosts)):
            continue
        if not name:
            raise ValueError(f"Requirement row {position} needs a name.")
        requirements.append(
            VlsmRequirement(
                name=name,
                required_hosts=_whole_number(
                    raw_hosts, f"Required hosts in row {position}"
                ),
            )
        )
    if not requirements:
        raise ValueError("Add at least one requirement before allocating.")
    return requirements


def _render_cidr() -> None:
    st.subheader("CIDR calculator")
    st.caption(
        "IPv4 and IPv6 prefixes use the standard-library ipaddress module. "
        "IPv4 /31 and /32 and IPv6 /127 and /128 follow their point-to-point "
        "and host-route rules."
    )
    network = st.text_input(
        "Network or host prefix",
        value="192.168.1.0/24",
        key="ip_cidr_input",
    )
    if st.button("Calculate prefix", key="ip_cidr_calculate", type="primary"):
        try:
            state.session_set(state.CIDR_KEY, calculate_subnet(network))
        except ValueError as error:
            st.error(f"Invalid prefix: {error}", title="Calculation failed")

    info = state.session_get(state.CIDR_KEY)
    if info is None:
        st.info("Enter a prefix and calculate to see its properties.")
        return

    columns = st.columns(4)
    columns[0].metric("Prefix", f"/{info.prefix_length}")
    columns[1].metric("Total addresses", f"{info.total_addresses:,}")
    columns[2].metric("Usable hosts", f"{info.usable_host_count:,}")
    columns[3].metric("IP version", f"IPv{info.version}")
    if info.special_case:
        st.caption(
            "Special prefix rule: "
            + info.special_case.replace("_", " ")
            + ". Network and broadcast exclusions are adjusted accordingly."
        )

    frame = pd.DataFrame(cidr_rows(info))
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download CIDR result as CSV",
        data=csv_bytes(frame),
        file_name="cidr-result.csv",
        mime="text/csv",
        key="ip_cidr_download",
    )


def _render_vlsm_result(result: VlsmResult) -> None:
    columns = st.columns(3)
    columns[0].metric("Allocations", len(result.allocations))
    columns[1].metric("Addresses allocated", f"{result.allocated_addresses:,}")
    columns[2].metric("Addresses remaining", f"{result.remaining_addresses:,}")

    frame = pd.DataFrame(allocation_rows(result))
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download VLSM plan as CSV",
        data=csv_bytes(frame),
        file_name="vlsm-plan.csv",
        mime="text/csv",
        key="vlsm_download",
    )

    report = build_utilization_report(
        [
            UtilizationEntry(
                name=allocation.name,
                network=allocation.network,
                used_addresses=allocation.required_hosts,
            )
            for allocation in result.allocations
        ],
        parent=result.parent,
    )
    st.markdown("**Utilization**")
    st.caption(
        f"Parent {report.parent} uses {report.parent_used_addresses:,} of "
        f"{report.parent_total_addresses:,} addresses "
        f"({report.parent_utilization_percent}%)."
    )
    for row in report.subnets[:24]:
        st.progress(
            min(100, round(row.utilization_percent)),
            text=(
                f"{row.name}: {row.used_addresses:,} of "
                f"{row.usable_addresses:,} usable addresses "
                f"({row.utilization_percent}%)"
            ),
        )
    if len(report.subnets) > 24:
        st.caption(f"{len(report.subnets) - 24} more subnets are in the CSV.")


def _render_vlsm() -> None:
    st.subheader("VLSM planner")
    st.caption(
        "Requirements are sorted largest-first. Each block reserves network, "
        "broadcast, and gateway addresses; the prefix is the smallest that fits "
        "the request. Allocation stops with a clear error if the parent is too "
        "small."
    )

    parent = st.text_input("Parent block", value="192.168.1.0/24", key="vlsm_parent")
    reserved = st.number_input(
        "Reserved addresses per subnet",
        min_value=1,
        max_value=1000,
        value=3,
        step=1,
        key="vlsm_reserved",
    )
    with st.form("vlsm_form"):
        frame = st.data_editor(
            DEFAULT_REQUIREMENTS,
            key="vlsm_requirements",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "name": st.column_config.TextColumn("Requirement", required=True),
                "required_hosts": st.column_config.NumberColumn(
                    "Required hosts",
                    min_value=0,
                    step=1,
                    required=True,
                ),
            },
        )
        submitted = st.form_submit_button(
            "Allocate subnets", key="vlsm_allocate", type="primary"
        )

    if submitted:
        try:
            requirements = _to_requirements(frame)
            result = allocate_vlsm(
                parent,
                requirements,
                reserved_addresses=int(reserved),
            )
            state.session_set(state.VLSM_KEY, result)
        except (NetArchitectError, ValidationError, ValueError) as error:
            st.error(format_error(error), title="Allocation failed")
        else:
            _store_vlsm_subnets(result)

    result = state.session_get(state.VLSM_KEY)
    if not isinstance(result, VlsmResult):
        st.info("No VLSM plan yet. Set a parent block and allocate the requirements.")
        return
    st.caption(f"Last allocation: {len(result.allocations)} subnets in {result.parent}.")
    _render_vlsm_result(result)


def _store_vlsm_subnets(result: VlsmResult) -> None:
    """Write the VLSM allocations into the twin's standalone subnets.

    Existing VLAN-tagged subnets are preserved. If the new subnets would
    overlap an existing VLAN subnet (or reuse a name), the twin is left
    unchanged and the user is told why instead of losing the existing plan.
    """
    existing = state.get_addressing()
    subnets = [
        Subnet(
            name=allocation.name,
            network=allocation.network,
            description=(
                f"VLSM allocation: {allocation.required_hosts} required hosts, "
                f"gateway {allocation.gateway}."
            ),
        )
        for allocation in result.allocations
    ]
    try:
        plan = AddressingPlan(
            vlan_plans=list(existing.vlan_plans) if existing is not None else [],
            subnets=subnets,
        )
    except ValidationError as error:
        st.warning(
            "The VLSM plan was calculated but was not stored in the digital "
            f"twin because it conflicts with the existing addressing plan: "
            f"{format_error(error)}",
            title="Not stored in twin",
        )
        return
    state.set_addressing(plan)


def _to_subnets(frame: pd.DataFrame) -> list[Subnet]:
    subnets: list[Subnet] = []
    for position, (_, row) in enumerate(frame.iterrows(), start=1):
        name = _text(row["name"])
        network = _text(row["network"])
        if not name and not network:
            continue
        if not name:
            raise ValueError(f"Subnet row {position} needs a name.")
        if not network:
            raise ValueError(f"Subnet row {position} needs a network.")
        subnets.append(Subnet(name=name, network=network))
    if not subnets:
        raise ValueError("Add at least one subnet to check.")
    return subnets


def _render_check() -> None:
    st.subheader("Subnet check")
    st.caption(
        "Checks a manually entered plan for overlapping prefixes. Findings use "
        "the shared severity, affected-entity, explanation, and remediation "
        "contract."
    )
    with st.form("subnet_check_form"):
        frame = st.data_editor(
            DEFAULT_CHECK_SUBNETS,
            key="subnet_check_editor",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "name": st.column_config.TextColumn("Subnet", required=True),
                "network": st.column_config.TextColumn("Network", required=True),
            },
        )
        submitted = st.form_submit_button("Check subnets", key="subnet_check_run")

    if submitted:
        try:
            subnets = _to_subnets(frame)
            state.session_set(state.CHECK_KEY, validate_addressing(subnets))
        except (ValidationError, ValueError) as error:
            st.error(format_error(error), title="Check failed")

    report = state.session_get(state.CHECK_KEY)
    if report is None:
        st.info("No subnet check yet.")
        return

    st.caption(report.summary)
    render_findings(
        report.findings,
        "No overlaps detected in the checked subnets.",
    )
    if report.findings:
        check_frame = findings_frame(report.findings)
        st.download_button(
            "Download findings as CSV",
            data=csv_bytes(check_frame),
            file_name="addressing-findings.csv",
            mime="text/csv",
            key="addressing_findings_download",
        )


def render() -> None:
    """Render the IP addressing page."""
    st.title("IP addressing and subnetting")
    st.caption(
        "Deterministic IPv4 and IPv6 planning. All arithmetic runs in the "
        "addressing engine; the page only presents inputs and results."
    )

    cidr_tab, vlsm_tab, check_tab = st.tabs(
        ["CIDR calculator", "VLSM planner", "Subnet check"]
    )
    with cidr_tab:
        _render_cidr()
    with vlsm_tab:
        _render_vlsm()
    with check_tab:
        _render_check()
