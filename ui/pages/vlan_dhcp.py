"""VLAN and DHCP planner page.

Presentation only: subnet allocation, VLAN mapping, and DHCP scope rules are
delegated to :mod:`network.addressing` and :mod:`network.vlan`. The page reads
an organization from session state when one exists and otherwise starts from
an editable manual department list.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.exceptions import NetArchitectError
from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet, VlanPlan
from core.schemas.organization import Organization
from network.addressing import VlsmRequirement, allocate_vlsm, validate_addressing
from network.vlan import (
    RESERVED_VLAN_IDS,
    VlanPlanResult,
    VlanRequest,
    dhcp_scope_rows,
    plan_dhcp_scope,
    plan_vlans,
    validate_dhcp_scope,
    vlan_rows,
)
from ui import state
from ui.components import (
    csv_bytes,
    findings_frame,
    format_error,
    render_findings,
)

DEFAULT_DEPARTMENTS = pd.DataFrame(
    [
        {"department": "engineering", "required_hosts": 120},
        {"department": "sales", "required_hosts": 45},
        {"department": "operations", "required_hosts": 30},
        {"department": "finance", "required_hosts": 15},
        {"department": "guest", "required_hosts": 20},
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


def _default_departments() -> pd.DataFrame:
    organization = state.session_get("organization")
    if not isinstance(organization, Organization):
        return DEFAULT_DEPARTMENTS
    rows: list[dict[str, object]] = []
    for site in organization.sites:
        for department in site.departments:
            rows.append(
                {
                    "department": f"{site.name}: {department.name}",
                    "required_hosts": max(department.user_count, 1),
                }
            )
    if not rows:
        return DEFAULT_DEPARTMENTS
    return pd.DataFrame(rows)


def _to_requirements(frame: pd.DataFrame) -> list[VlsmRequirement]:
    requirements: list[VlsmRequirement] = []
    for position, (_, row) in enumerate(frame.iterrows(), start=1):
        name = _text(row["department"])
        raw_hosts = row["required_hosts"]
        if not name and (raw_hosts is None or pd.isna(raw_hosts)):
            continue
        if not name:
            raise ValueError(f"Department row {position} needs a name.")
        requirements.append(
            VlsmRequirement(
                name=name,
                required_hosts=_whole_number(
                    raw_hosts, f"Required hosts in row {position}"
                ),
            )
        )
    if not requirements:
        raise ValueError("Add at least one department before planning.")
    return requirements


def _build_plan(
    frame: pd.DataFrame,
    *,
    parent: str,
    reserved: int,
    start_vlan_id: int,
    lease_minutes: int,
) -> tuple[VlanPlanResult, list[DhcpScope]]:
    requirements = _to_requirements(frame)
    allocations = allocate_vlsm(
        parent,
        requirements,
        reserved_addresses=reserved,
    )
    requests = [
        VlanRequest(
            department=allocation.name,
            subnet=Subnet(name=allocation.name, network=allocation.network),
            purpose=allocation.name,
        )
        for allocation in allocations.allocations
    ]
    plan = plan_vlans(requests, start_vlan_id=start_vlan_id)

    scopes = []
    errors: list[str] = []
    for assignment in plan.assignments:
        try:
            scopes.append(
                plan_dhcp_scope(
                    Subnet(name=assignment.subnet_name, network=assignment.network),
                    name=f"{assignment.department} DHCP",
                    lease_minutes=lease_minutes,
                )
            )
        except ValueError as error:
            errors.append(f"{assignment.department}: {error}")
    if errors:
        raise ValueError("DHCP planning failed for: " + "; ".join(errors))
    return plan, scopes


def _addressing_from_plan(plan: VlanPlanResult) -> AddressingPlan:
    """Build an addressing plan with one VLAN plan per department assignment."""
    return AddressingPlan(
        vlan_plans=[
            VlanPlan(
                vlan_id=assignment.vlan_id,
                name=assignment.vlan_name,
                subnets=[
                    Subnet(
                        name=assignment.subnet_name,
                        network=assignment.network,
                    )
                ],
                purpose=assignment.purpose,
            )
            for assignment in plan.assignments
        ],
        subnets=[],
    )


def _render_results() -> None:
    plan = state.get_vlan_plan()
    scopes = state.get_dhcp_scopes()
    if plan is None or not scopes:
        st.info(
            "No VLAN plan yet. Define departments and build a plan to see VLAN, "
            "subnet, and DHCP assignments."
        )
        return

    vlan_frame = pd.DataFrame(vlan_rows(plan))
    dhcp_frame = pd.DataFrame(dhcp_scope_rows(scopes))

    columns = st.columns(4)
    columns[0].metric("VLANs", len(plan.assignments))
    columns[1].metric("Subnets", len(vlan_frame))
    columns[2].metric("DHCP scopes", len(scopes))
    columns[3].metric(
        "DHCP pool addresses",
        f"{int(dhcp_frame['pool_size'].sum()):,}",
    )

    st.subheader("VLAN plan")
    st.caption(
        "One department maps to one VLAN and one subnet. Reserved VLAN ids are "
        f"never assigned: {', '.join(str(vlan_id) for vlan_id in sorted(RESERVED_VLAN_IDS))}."
    )
    st.dataframe(vlan_frame, hide_index=True, width="stretch")
    st.download_button(
        "Download VLAN plan as CSV",
        data=csv_bytes(vlan_frame),
        file_name="vlan-plan.csv",
        mime="text/csv",
        key="vlan_plan_download",
    )

    st.subheader("DHCP scopes")
    st.dataframe(dhcp_frame, hide_index=True, width="stretch")
    st.download_button(
        "Download DHCP scopes as CSV",
        data=csv_bytes(dhcp_frame),
        file_name="dhcp-scopes.csv",
        mime="text/csv",
        key="dhcp_scope_download",
    )

    st.subheader("Validation")
    subnet_findings = validate_addressing(
        [
            Subnet(name=assignment.subnet_name, network=assignment.network)
            for assignment in plan.assignments
        ]
    ).findings
    scope_findings = [
        finding for scope in scopes for finding in validate_dhcp_scope(scope)
    ]
    findings = subnet_findings + scope_findings
    render_findings(
        findings,
        "No VLAN overlaps or DHCP scope violations detected.",
    )
    if findings:
        st.download_button(
            "Download findings as CSV",
            data=csv_bytes(findings_frame(findings)),
            file_name="vlan-dhcp-findings.csv",
            mime="text/csv",
            key="vlan_findings_download",
        )


def render() -> None:
    """Render the VLAN and DHCP planner page."""
    st.title("VLAN and DHCP planner")
    st.caption(
        "Map departments to VLANs and generate one validated DHCP scope per "
        "subnet. Address arithmetic runs in the deterministic engines."
    )

    st.subheader("Department requirements")
    st.caption(
        "Department rows come from an organization in session state when one is "
        "available; otherwise edit the manual list below."
    )
    parent = st.text_input("Parent block", value="10.0.0.0/16", key="vlan_parent")
    columns = st.columns(3)
    start_vlan_id = columns[0].number_input(
        "First VLAN id",
        min_value=1,
        max_value=4094,
        value=10,
        step=1,
        key="vlan_start_id",
    )
    reserved = columns[1].number_input(
        "Reserved addresses per subnet",
        min_value=1,
        max_value=1000,
        value=3,
        step=1,
        key="vlan_reserved",
    )
    lease_minutes = columns[2].number_input(
        "DHCP lease (minutes)",
        min_value=1,
        max_value=525600,
        value=1440,
        step=60,
        key="vlan_lease",
    )

    with st.form("vlan_plan_form"):
        frame = st.data_editor(
            _default_departments(),
            key="vlan_department_editor",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "department": st.column_config.TextColumn(
                    "Department", required=True
                ),
                "required_hosts": st.column_config.NumberColumn(
                    "Required hosts",
                    min_value=0,
                    step=1,
                    required=True,
                ),
            },
        )
        submitted = st.form_submit_button(
            "Build VLAN and DHCP plan",
            key="vlan_build_plan",
            type="primary",
        )

    if submitted:
        try:
            plan, scopes = _build_plan(
                frame,
                parent=parent,
                reserved=int(reserved),
                start_vlan_id=int(start_vlan_id),
                lease_minutes=int(lease_minutes),
            )
        except (NetArchitectError, ValidationError, ValueError) as error:
            st.error(format_error(error), title="Planning failed")
        else:
            state.set_planning(
                addressing=_addressing_from_plan(plan),
                vlan_plan=plan,
                dhcp_scopes=tuple(scopes),
            )
            st.success(
                f"Planned {len(plan.assignments)} VLANs and "
                f"{len(scopes)} DHCP scopes."
            )

    _render_results()
