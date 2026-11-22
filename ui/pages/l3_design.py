"""L3 Design page for bounded, deterministic design-time L3 planning.

The page is presentation only. Every modeled value comes from the L1-L4
engines; applying an editor stores a typed plan on the in-memory digital twin.
Nothing here configures equipment, exchanges a protocol, or simulates packets.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from config.limits import (
    MAX_HA_GROUPS,
    MAX_NAT_RULES,
    MAX_OSPF_AREAS,
)
from core.exceptions import NetArchitectError
from digital_twin import DigitalTwin
from network.addressing.dual_stack import plan_dual_stack, requests_from_plan
from network.addressing.nat import (
    NatPlan,
    NatRule,
    NatType,
    analyze_nat_plan,
)
from network.routing.ha import HaGroup, HaMember, analyze_ha_groups
from network.routing.ospf import OspfArea, OspfDesign, analyze_ospf_design
from services.copilot import ha_group_request, ospf_design_request
from ui import i18n, state, theme
from ui.cache import (
    L3DesignReview,
    cached_l3_design_review,
    twin_cache_key,
    twin_payload,
)
from ui.components import (
    empty_state,
    format_error,
    page_header,
    section_header,
)
from ui.components.copilot import why_button
from ui.components.editors import bump_editor_key, editor_key
from ui.components.health import render_design_health
from ui.components.notices import queue_notice, render_notices

PAGE_TITLE = "L3 Design"
MODEL_NOTE = (
    "Modeled design rules only: no device access, protocol exchange, packet "
    "behavior, or live measurement is performed."
)

DUAL_STACK_BLOCK_KEY = "l3_ipv6_block"
DUAL_STACK_APPLY_KEY = "l3_ipv6_apply"
DUAL_STACK_CLEAR_KEY = "l3_ipv6_clear"

NAT_RULE_EDITOR_BASE = "l3_nat_rules_editor"
NAT_APPLY_KEY = "l3_nat_apply"
NAT_CLEAR_KEY = "l3_nat_clear"
NAT_COLUMNS = (
    "id",
    "name",
    "nat_type",
    "inside_zone",
    "inside_subnets",
    "outside_pools",
    "inside_hosts",
    "sessions_per_host",
)

OSPF_AREA_EDITOR_BASE = "l3_ospf_areas_editor"
OSPF_EXTERNAL_KEY = "l3_ospf_external_devices"
OSPF_REFERENCE_BANDWIDTH_KEY = "l3_ospf_reference_bandwidth"
OSPF_AREA_THRESHOLD_KEY = "l3_ospf_area_threshold"
OSPF_APPLY_KEY = "l3_ospf_apply"
OSPF_CLEAR_KEY = "l3_ospf_clear"
OSPF_WHY_KEY = "l3_why_ospf"
OSPF_COLUMNS = ("area_id", "name", "device_ids", "link_ids", "subnets")

HA_GROUP_EDITOR_BASE = "l3_ha_groups_editor"
HA_APPLY_KEY = "l3_ha_apply"
HA_CLEAR_KEY = "l3_ha_clear"
HA_WHY_SELECT_KEY = "l3_ha_why_select"
HA_WHY_KEY = "l3_why_ha_group"
HA_COLUMNS = (
    "id",
    "name",
    "virtual_ip",
    "subnet",
    "vlan_id",
    "preempt",
    "device_ids",
    "priorities",
)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _csv(value: object) -> tuple[str, ...]:
    return tuple(part for part in _text(value).split(",") if part)


def _integer(value: object, default: int = 0) -> int:
    text = _text(value)
    return int(float(text)) if text else default


def _number(value: object, default: float = 0.0) -> float:
    text = _text(value)
    return float(text) if text else default


def _boolean(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y"}


def _frame(rows: list[dict[str, object]], columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(columns))


def _findings_frame(findings: tuple[tuple[str, str], ...]) -> pd.DataFrame:
    return pd.DataFrame(findings, columns=["Code", "Explanation"])


def _scope_note() -> None:
    st.markdown(
        f'<span style="color:{theme.color("info")};font-weight:600;">'
        f"{i18n.t('l3.scope')}</span>",
        unsafe_allow_html=True,
    )


def _review(twin: DigitalTwin) -> L3DesignReview:
    return cached_l3_design_review(twin_payload(twin), twin_cache_key(twin))


def _apply(
    twin: DigitalTwin,
    *,
    field: str,
    editor_base: str,
    build,
    success: str,
) -> None:
    """Build, store, and announce one optional L3 model."""
    try:
        candidate = build()
        updated = twin.model_copy(update={field: candidate})
        state.replace_twin(updated)
    except (NetArchitectError, ValidationError, ValueError) as error:
        bump_editor_key(editor_base)
        queue_notice("error", format_error(error), title="Model not saved")
    else:
        queue_notice("success", success)
    st.rerun()


def _clear(twin: DigitalTwin, *, field: str, value: object, message: str) -> None:
    state.replace_twin(twin.model_copy(update={field: value}))
    queue_notice("info", message)
    st.rerun()


def _dual_stack_frame(twin: DigitalTwin) -> pd.DataFrame:
    plan = twin.ipv6_plan
    rows = [
        {
            "Name": item.name,
            "VLAN": str(item.vlan_id) if item.vlan_id is not None else "-",
            "IPv4": item.ipv4_network or "-",
            "IPv6": item.ipv6_network,
            "Scope": item.scope.value,
            "Origin": item.origin,
        }
        for item in (plan.assignments if plan is not None else ())
    ]
    return pd.DataFrame(
        rows,
        columns=["Name", "VLAN", "IPv4", "IPv6", "Scope", "Origin"],
    )


def _nat_frame(twin: DigitalTwin) -> pd.DataFrame:
    plan = twin.nat_plan
    rows = [
        {
            "id": item.id,
            "name": item.name,
            "nat_type": item.nat_type.value,
            "inside_zone": item.inside_zone,
            "inside_subnets": ", ".join(str(item) for item in item.inside_subnets),
            "outside_pools": ", ".join(str(item) for item in item.outside_pools),
            "inside_hosts": item.inside_hosts if item.inside_hosts is not None else 0,
            "sessions_per_host": item.sessions_per_host,
        }
        for item in (plan.rules if plan is not None else ())
    ]
    if not rows:
        rows = [
            {
                "id": "nat-1",
                "name": "Users to internet",
                "nat_type": NatType.pat_overload.value,
                "inside_zone": "users",
                "inside_subnets": "10.0.0.0/24",
                "outside_pools": "203.0.113.10/32",
                "inside_hosts": 254,
                "sessions_per_host": 1,
            }
        ]
    return _frame(rows, NAT_COLUMNS)


def _ospf_frame(twin: DigitalTwin) -> pd.DataFrame:
    design = twin.ospf_design
    rows = [
        {
            "area_id": area.area_id,
            "name": area.name,
            "device_ids": ", ".join(area.device_ids),
            "link_ids": ", ".join(area.link_ids),
            "subnets": ", ".join(str(item) for item in area.subnets),
        }
        for area in (design.areas if design is not None else ())
    ]
    if not rows:
        rows = [
            {
                "area_id": 0,
                "name": "Backbone",
                "device_ids": ", ".join(
                    device.id for device in twin.topology.devices[:2]
                ),
                "link_ids": "",
                "subnets": "",
            }
        ]
    return _frame(rows, OSPF_COLUMNS)


def _ha_frame(twin: DigitalTwin) -> pd.DataFrame:
    rows = [
        {
            "id": group.id,
            "name": group.name,
            "virtual_ip": str(group.virtual_ip),
            "subnet": str(group.subnet),
            "vlan_id": group.vlan_id or 0,
            "preempt": group.preempt,
            "device_ids": ", ".join(member.device_id for member in group.members),
            "priorities": ", ".join(str(member.priority) for member in group.members),
        }
        for group in twin.ha_groups
    ]
    if not rows:
        routers = [
            device.id
            for device in twin.topology.devices
            if device.type.value == "router"
        ][:2]
        rows = [
            {
                "id": "gw-1",
                "name": "User gateway",
                "virtual_ip": "10.0.0.1",
                "subnet": "10.0.0.0/24",
                "vlan_id": 0,
                "preempt": True,
                "device_ids": ", ".join(routers),
                "priorities": "150, 100",
            }
        ]
    return _frame(rows, HA_COLUMNS)


def _nat_plan_from_frame(edited: pd.DataFrame) -> NatPlan:
    rows = edited.to_dict("records")
    if len(rows) > MAX_NAT_RULES:
        raise ValueError(f"At most {MAX_NAT_RULES} NAT rules may be modeled.")
    rules = []
    for row in rows:
        rules.append(
            NatRule(
                id=_text(row.get("id")),
                name=_text(row.get("name")),
                nat_type=NatType(_text(row.get("nat_type"))),
                inside_zone=_text(row.get("inside_zone")),
                inside_subnets=_csv(row.get("inside_subnets")),
                outside_pools=_csv(row.get("outside_pools")),
                inside_hosts=_integer(row.get("inside_hosts"), 0),
                sessions_per_host=_integer(row.get("sessions_per_host"), 1),
            )
        )
    plan = NatPlan(rules=tuple(rules))
    analyze_nat_plan(plan)
    return plan


def _ospf_design_from_frame(
    edited: pd.DataFrame,
    *,
    external_devices: str,
    reference_bandwidth: object,
    area_threshold: object,
) -> OspfDesign:
    rows = edited.to_dict("records")
    if len(rows) > MAX_OSPF_AREAS:
        raise ValueError(f"At most {MAX_OSPF_AREAS} OSPF areas may be modeled.")
    areas = tuple(
        OspfArea(
            area_id=_integer(row.get("area_id"), 0),
            name=_text(row.get("name")),
            device_ids=_csv(row.get("device_ids")),
            link_ids=_csv(row.get("link_ids")),
            subnets=_csv(row.get("subnets")),
        )
        for row in rows
    )
    bandwidth = _number(reference_bandwidth, 0.0)
    design = OspfDesign(
        areas=areas,
        external_device_ids=_csv(external_devices),
        reference_bandwidth_mbps=bandwidth if bandwidth > 0 else None,
        area_size_threshold=_integer(area_threshold, 50) or 50,
    )
    analyze_ospf_design(design, state.peek_twin().topology)  # type: ignore[union-attr]
    return design


def _ha_groups_from_frame(edited: pd.DataFrame) -> tuple[HaGroup, ...]:
    rows = edited.to_dict("records")
    if len(rows) > MAX_HA_GROUPS:
        raise ValueError(f"At most {MAX_HA_GROUPS} gateway groups may be modeled.")
    groups = []
    for row in rows:
        device_ids = _csv(row.get("device_ids"))
        priorities = _csv(row.get("priorities"))
        if priorities and len(priorities) != len(device_ids):
            raise ValueError("Gateway priorities must match the device list length.")
        members = tuple(
            HaMember(
                device_id=device_id,
                priority=_integer(priorities[index], 100) if priorities else 100,
            )
            for index, device_id in enumerate(device_ids)
        )
        vlan_id = _integer(row.get("vlan_id"), 0)
        groups.append(
            HaGroup(
                id=_text(row.get("id")),
                name=_text(row.get("name")),
                virtual_ip=_text(row.get("virtual_ip")),
                subnet=_text(row.get("subnet")),
                vlan_id=vlan_id if vlan_id else None,
                preempt=_boolean(row.get("preempt"), True),
                members=members,
            )
        )
    return tuple(groups)


def render_dual_stack_tab(
    twin: DigitalTwin,
    review: L3DesignReview | None = None,
) -> None:
    """Render the modeled IPv6 dual-stack editor and its prefix arithmetic."""
    review = review or _review(twin)
    plan = twin.ipv6_plan
    section_header("Modeled IPv6 dual-stack")
    if plan is None:
        st.caption("No dual-stack plan is stored on the twin.")
    else:
        used, available = st.columns(2)
        used.metric("Prefixes used", plan.prefixes_used)
        available.metric("Prefixes available", plan.prefixes_available)
        st.caption(
            f"Block {plan.block}; modeled VLAN prefix length /{plan.prefix_length}; "
            f"prefix utilization {plan.utilization_percent:.2f}%. IPv6 hosts are "
            "never enumerated."
        )
        st.dataframe(_dual_stack_frame(twin), hide_index=True, width="stretch")
        if review.dual_stack_findings:
            with st.expander(f"Design findings ({len(review.dual_stack_findings)})"):
                st.dataframe(
                    _findings_frame(review.dual_stack_findings),
                    hide_index=True,
                    width="stretch",
                )

    section_header("Model dual-stack plan", divider=True)
    st.caption(
        "Auto-assigned VLAN prefixes are exactly /64 and carved sequentially "
        "from the supplied block. Requests derive from the stored IPv4 plan."
    )
    block = st.text_input(
        "IPv6 block",
        value=plan.block if plan is not None else "fd00::/48",
        key=DUAL_STACK_BLOCK_KEY,
    )

    def build() -> object:
        addressing = twin.addressing
        requests = requests_from_plan(addressing) if addressing is not None else []
        return plan_dual_stack(block, requests)

    apply_col, clear_col = st.columns(2)
    if apply_col.button("Model dual-stack plan", key=DUAL_STACK_APPLY_KEY):
        _apply(
            twin,
            field="ipv6_plan",
            editor_base=DUAL_STACK_BLOCK_KEY,
            build=build,
            success="IPv6 dual-stack plan saved to the twin.",
        )
    if clear_col.button("Clear dual-stack plan", key=DUAL_STACK_CLEAR_KEY):
        _clear(twin, field="ipv6_plan", value=None, message="Dual-stack plan cleared.")


def render_nat_tab(twin: DigitalTwin, review: L3DesignReview | None = None) -> None:
    """Render the modeled NAT/PAT editor with hand-checkable sizing."""
    review = review or _review(twin)
    section_header("Modeled NAT/PAT rules")
    if review.nat_sizings:
        st.dataframe(
            pd.DataFrame(
                review.nat_sizings,
                columns=[
                    "Rule",
                    "Type",
                    "Hosts",
                    "Pool addresses",
                    "Required addresses",
                    "Sessions",
                    "Capacity",
                    "Ports/address",
                ],
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "PAT capacity is pool addresses times 64512 usable ports "
            "(65535 - 1024 + 1). No translation is performed."
        )
    else:
        st.caption("No NAT/PAT plan is stored on the twin.")
    if review.nat_findings:
        with st.expander(f"Design findings ({len(review.nat_findings)})"):
            st.dataframe(
                _findings_frame(review.nat_findings),
                hide_index=True,
                width="stretch",
            )

    section_header("Edit NAT/PAT plan", divider=True)
    st.caption(
        "List IPv4 or IPv6 prefixes as comma-separated values. Set inside hosts "
        "to 0 to derive the modeled count from IPv4 prefixes only."
    )
    edited = st.data_editor(
        _nat_frame(twin),
        key=editor_key(NAT_RULE_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
    )
    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply NAT plan", key=NAT_APPLY_KEY):
        _apply(
            twin,
            field="nat_plan",
            editor_base=NAT_RULE_EDITOR_BASE,
            build=lambda: _nat_plan_from_frame(edited),
            success="NAT/PAT plan saved to the twin.",
        )
    if clear_col.button("Clear NAT plan", key=NAT_CLEAR_KEY):
        _clear(twin, field="nat_plan", value=None, message="NAT/PAT plan cleared.")


def render_ospf_tab(twin: DigitalTwin, review: L3DesignReview | None = None) -> None:
    """Render the modeled OSPF area editor, derived roles, and explanation."""
    review = review or _review(twin)
    section_header("Derived OSPF design")
    if review.ospf_routers:
        st.dataframe(
            pd.DataFrame(
                review.ospf_routers, columns=["Device", "Areas", "Derived role"]
            ),
            hide_index=True,
            width="stretch",
        )
        st.dataframe(
            pd.DataFrame(
                review.ospf_link_costs,
                columns=["Link", "Capacity (Mbps)", "Base", "Effective", "Formula"],
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No OSPF area design is stored on the twin.")
    if review.ospf_findings:
        with st.expander(f"Design findings ({len(review.ospf_findings)})"):
            st.dataframe(
                _findings_frame(review.ospf_findings),
                hide_index=True,
                width="stretch",
            )
    if twin.ospf_design is not None:
        why_button(
            OSPF_WHY_KEY,
            lambda: ospf_design_request(
                twin.ospf_design,  # type: ignore[arg-type]
                analyze_ospf_design(twin.ospf_design, twin.topology),  # type: ignore[arg-type]
            ),
        )

    section_header("Edit OSPF areas", divider=True)
    st.caption(
        "A device in two or more areas is an ABR. External devices and border "
        "or WAN roles are ASBRs (ASBR takes precedence)."
    )
    edited = st.data_editor(
        _ospf_frame(twin),
        key=editor_key(OSPF_AREA_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
    )
    external = st.text_input(
        "External device ids (comma separated)",
        value=(
            ", ".join(twin.ospf_design.external_device_ids)
            if twin.ospf_design is not None
            else ""
        ),
        key=OSPF_EXTERNAL_KEY,
    )
    settings_col, threshold_col = st.columns(2)
    reference = settings_col.number_input(
        "Reference bandwidth (Mbps, 0 = use Link.cost)",
        min_value=0.0,
        value=(
            twin.ospf_design.reference_bandwidth_mbps or 0.0
            if twin.ospf_design is not None
            else 0.0
        ),
        key=OSPF_REFERENCE_BANDWIDTH_KEY,
    )
    threshold = threshold_col.number_input(
        "Area size heuristic (not a protocol limit)",
        min_value=1,
        value=(
            twin.ospf_design.area_size_threshold
            if twin.ospf_design is not None
            else 50
        ),
        key=OSPF_AREA_THRESHOLD_KEY,
    )

    def build() -> object:
        return _ospf_design_from_frame(
            edited,
            external_devices=external,
            reference_bandwidth=reference,
            area_threshold=threshold,
        )

    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply OSPF design", key=OSPF_APPLY_KEY):
        _apply(
            twin,
            field="ospf_design",
            editor_base=OSPF_AREA_EDITOR_BASE,
            build=build,
            success="OSPF area design saved to the twin.",
        )
    if clear_col.button("Clear OSPF design", key=OSPF_CLEAR_KEY):
        _clear(twin, field="ospf_design", value=None, message="OSPF design cleared.")


def render_ha_tab(twin: DigitalTwin, review: L3DesignReview | None = None) -> None:
    """Render the modeled first-hop gateway editor and election summary."""
    review = review or _review(twin)
    section_header("Modeled gateway redundancy")
    if review.ha_active:
        st.dataframe(
            pd.DataFrame(review.ha_active, columns=["Group", "Nominal active"]),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "The active member has the highest priority; ties use the "
            "lexicographically lowest device id. Preempt is metadata only."
        )
    else:
        st.caption("No first-hop redundancy groups are stored on the twin.")
    if review.ha_findings:
        with st.expander(f"Design findings ({len(review.ha_findings)})"):
            st.dataframe(
                _findings_frame(review.ha_findings),
                hide_index=True,
                width="stretch",
            )
    if twin.ha_groups:
        selected = st.selectbox(
            "Group to explain",
            options=[group.id for group in twin.ha_groups],
            key=HA_WHY_SELECT_KEY,
        )
        group = next(item for item in twin.ha_groups if item.id == selected)

        def build_request():
            return ha_group_request(
                group,
                analyze_ha_groups(
                    twin.ha_groups,
                    twin.topology,
                    vlan_plan=twin.vlan_plan,
                ),
            )

        why_button(HA_WHY_KEY, build_request)

    section_header("Edit gateway groups", divider=True)
    st.caption(
        "Use comma-separated device ids and matching priorities. Leave VLAN id "
        "at 0 when the group is not bound to a VLAN."
    )
    edited = st.data_editor(
        _ha_frame(twin),
        key=editor_key(HA_GROUP_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
    )
    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply gateway groups", key=HA_APPLY_KEY):
        _apply(
            twin,
            field="ha_groups",
            editor_base=HA_GROUP_EDITOR_BASE,
            build=lambda: _ha_groups_from_frame(edited),
            success="Gateway redundancy groups saved to the twin.",
        )
    if clear_col.button("Clear gateway groups", key=HA_CLEAR_KEY):
        _clear(twin, field="ha_groups", value=(), message="Gateway groups cleared.")


def render() -> None:
    """Render the L3 Design page."""
    page_header(PAGE_TITLE, i18n.t("page.l3_design.description"))
    render_notices()
    st.info(MODEL_NOTE)
    _scope_note()

    twin = state.get_twin()
    if twin is None:
        empty_state(
            "No digital twin with a topology is loaded.",
            title="No design loaded",
            hint="Load or edit a twin on the Topology or Digital Twin page first.",
        )
        return

    review = _review(twin)
    tabs = st.tabs(
        [
            i18n.t("l3.tab.ipv6"),
            i18n.t("l3.tab.nat"),
            i18n.t("l3.tab.ospf"),
            i18n.t("l3.tab.ha"),
            i18n.t("l3.tab.findings"),
        ]
    )
    with tabs[0]:
        render_dual_stack_tab(twin, review)
    with tabs[1]:
        render_nat_tab(twin, review)
    with tabs[2]:
        render_ospf_tab(twin, review)
    with tabs[3]:
        render_ha_tab(twin, review)
    with tabs[4]:
        section_header("Design health")
        st.caption(
            "The shared health panel includes the optional L3 design checks "
            "when their plans are stored on the twin."
        )
        render_design_health(twin)


__all__ = [
    "MODEL_NOTE",
    "PAGE_TITLE",
    "render",
    "render_dual_stack_tab",
    "render_ha_tab",
    "render_nat_tab",
    "render_ospf_tab",
]
