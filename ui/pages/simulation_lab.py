"""Simulation Lab page.

The page is presentation only. Flow evaluation, scenario validation, history,
and exports are delegated to :mod:`simulation`; the baseline twin is read and
edited through :mod:`ui.state`.

Every number shown here is a *modeled estimate* from the assumptions entered on
this page. Nothing is packet-level or hardware-accurate, and no simulated
result is written back to the twin.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping, Sequence

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

from config.limits import (
    MAX_COPILOT_TEXT_CHARS,
    MAX_N2_PAIRS,
    MAX_SCENARIOS,
    MAX_SHARED_RISK_GROUPS,
    MAX_SHARED_RISK_MEMBERS,
    MAX_SIMULATION_RUNTIME_SECONDS,
)
from config.settings import get_settings
from core.exceptions import InputError, NetArchitectError
from core.inputs import parse_json_text
from core.schemas.routing import TrafficDemand
from core.schemas.scenario import Scenario, ScenarioType
from digital_twin import DigitalTwin, SharedRiskGroup, validate_twin
from services.copilot import interpret_scenario, route_request, simulation_request
from services.llm import GroqProvider
from simulation import (
    DEFAULT_COMPARISON_MODES,
    MODEL_NOTE,
    FailureSweepDepth,
    FailureSweepResult,
    FailureSweepStopReason,
    RoutingMode,
    RoutingModeComparison,
    ScenarioRun,
    compare_routing_modes,
    compare_runs,
    failure_sweep_rows,
    failure_sweep_to_csv,
    failure_sweep_to_json,
    link_comparison_rows,
    metric_rows,
    path_change_rows,
    plan_failure_sweep,
    run_failure_sweep,
    run_scenario,
    run_to_csv,
    run_to_json_bytes,
    unserved_rows,
    validate_scenario,
)
from simulation.models import CongestionThresholds, SimulationAssumptions
from ui import formatting, i18n, state, theme
from ui.components import csv_bytes, format_error, model_estimate_note, page_header
from ui.components.copilot import why_button
from ui.components.editors import bump_editor_key, editor_key
from ui.components.feedback import working

VIEW_RUN_KEY = "simulation_view_run"
FLASH_KEY = "simulation_flash"
HISTORY_SELECT_KEY = "simulation_history_select"
COMPARE_LEFT_KEY = "simulation_compare_left"
COMPARE_RIGHT_KEY = "simulation_compare_right"
SHOW_UNCHANGED_PATHS_KEY = "simulation_show_unchanged_paths"
SWEEP_CANCEL_KEY = "simulation_sweep_cancel"
SWEEP_CURSOR_KEY = "simulation_sweep_cursor_value"
SWEEP_SLICE_KEY = "simulation_sweep_slice_size"
COPILOT_SENTENCE_KEY = "simulation_copilot_sentence"
COPILOT_RESULT_KEY = "simulation_copilot_result"
COPILOT_PREVIEW_KEY = "simulation_copilot_preview"
ROUTE_EXPLANATION_SELECT_KEY = "copilot_why_route_demand"

ROUTING_MODE_LABELS: dict[RoutingMode, str] = {
    RoutingMode.single_path: "Single path (legacy)",
    RoutingMode.ecmp: "Equal-cost multipath (ECMP)",
    RoutingMode.capacity_aware: "Capacity-aware admission",
}
ROUTING_MODE_OPTIONS = [ROUTING_MODE_LABELS[mode] for mode in RoutingMode]
ROUTING_MODE_BY_LABEL = {label: mode for mode, label in ROUTING_MODE_LABELS.items()}
SWEEP_DEPTH_LABELS: dict[FailureSweepDepth, str] = {
    FailureSweepDepth.n1: "N-1 (one link or device)",
    FailureSweepDepth.n2: "N-2 (pairs from a chosen subset)",
}
SWEEP_DEPTH_OPTIONS = [
    SWEEP_DEPTH_LABELS[depth] for depth in FailureSweepDepth
]
SWEEP_DEPTH_BY_LABEL = {label: depth for depth, label in SWEEP_DEPTH_LABELS.items()}

SCENARIO_LABELS: dict[ScenarioType, str] = {
    ScenarioType.single_link_failure: "Single link failure",
    ScenarioType.multiple_link_failures: "Multiple link failures",
    ScenarioType.node_failure: "Node failure",
    ScenarioType.bandwidth_reduction: "Bandwidth reduction",
    ScenarioType.increased_traffic_demand: "Increased traffic demand",
    ScenarioType.new_department: "New department",
    ScenarioType.network_expansion: "Network expansion",
    ScenarioType.routing_cost_change: "Routing-cost change",
    ScenarioType.redundancy_recovery_test: "Redundancy / recovery test",
}
SCENARIO_OPTIONS = list(SCENARIO_LABELS.values())
SCENARIO_TYPES = {label: kind for kind, label in SCENARIO_LABELS.items()}

LINK_SCENARIOS = {
    ScenarioType.single_link_failure,
    ScenarioType.multiple_link_failures,
    ScenarioType.bandwidth_reduction,
    ScenarioType.routing_cost_change,
    ScenarioType.redundancy_recovery_test,
}
NODE_SCENARIOS = {
    ScenarioType.node_failure,
    ScenarioType.redundancy_recovery_test,
}
EXPANSION_SCENARIOS = {
    ScenarioType.new_department,
    ScenarioType.network_expansion,
}

LEVEL_COLORS = {
    "normal": theme.color("state_normal"),
    "warning": theme.color("state_warning"),
    "critical": theme.color("state_critical"),
    "overloaded": theme.color("state_overloaded"),
    "not present": theme.color("state_absent"),
}
LINK_COLORS = {
    "normal": theme.color("link_undirected"),
    "warning": theme.color("util_medium"),
    "critical": theme.color("util_high"),
    "overloaded": theme.color("critical"),
    "failed": theme.color("critical"),
}
ROLE_COLORS = {
    "core": theme.color("role_core"),
    "distribution": theme.color("role_distribution"),
    "aggregation": theme.color("role_aggregation"),
    "access": theme.color("role_access"),
    "border": theme.color("role_border"),
    "edge": theme.color("role_edge"),
    "wan": theme.color("role_border"),
    "dmz": theme.color("role_wan"),
}
EXPANSION_TEMPLATE = json.dumps(
    {"devices": [], "links": [], "demands": []},
    indent=2,
)


def _flash(level: str, message: str) -> None:
    messages = state.session_get(FLASH_KEY, [])
    state.session_set(FLASH_KEY, [*messages, (level, message)])


def _render_flash() -> None:
    for level, message in state.session_pop(FLASH_KEY, []):
        getattr(st, level)(message)


def _multi_select(
    label: str,
    options: list[str],
    key: str,
    help_text: str,
) -> list[str]:
    current = state.session_get(key, [])
    valid = [value for value in current if value in options]
    if valid != current:
        state.session_set(key, valid)
    return st.multiselect(label, options=options, key=key, help=help_text)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "scenario"


def _scenario_label(run: ScenarioRun) -> str:
    kind = SCENARIO_LABELS.get(run.scenario.type, run.scenario.type.value)
    return (
        f"{run.scenario.name} [{kind}] - served "
        f"{run.scenario_state.served_demand_count}/"
        f"{run.scenario_state.demand_count}, max utilization "
        f"{run.scenario_state.max_utilization_percent:.2f}%"
    )


# ---------------------------------------------------------------------------
# Demand editor
# ---------------------------------------------------------------------------


def _demand_frame(twin: DigitalTwin) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": demand.name,
                "source": demand.source,
                "destination": demand.destination,
                "bandwidth_mbps": demand.bandwidth_mbps,
                "priority": demand.priority,
            }
            for demand in twin.demands
        ],
        columns=["name", "source", "destination", "bandwidth_mbps", "priority"],
    )


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def _number(value: object, label: str, entity: str) -> float:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError(f"{entity}: {label} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{entity}: {label} must be a number.") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{entity}: {label} must be a non-negative number.")
    return number


def _apply_demands(twin: DigitalTwin, edited: pd.DataFrame) -> tuple[int, bool]:
    known_devices = {device.id for device in twin.topology.devices}
    demands: list[TrafficDemand] = []
    for _, row in edited.iterrows():
        name = _text(row["name"])
        if not name:
            raise ValueError("Every demand row needs a non-empty name.")
        source = _text(row["source"])
        destination = _text(row["destination"])
        if not source or not destination:
            raise ValueError(f"Demand {name!r} needs both endpoints.")
        unknown = sorted(
            endpoint
            for endpoint in (source, destination)
            if endpoint not in known_devices
        )
        if unknown:
            raise ValueError(
                f"Demand {name!r} references unknown device(s): "
                + ", ".join(unknown)
            )
        priority = _number(row["priority"], "priority", f"Demand {name!r}")
        if priority != int(priority):
            raise ValueError(f"Demand {name!r}: priority must be a whole number.")
        demands.append(
            TrafficDemand(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=_number(
                    row["bandwidth_mbps"],
                    "bandwidth",
                    f"Demand {name!r}",
                ),
                priority=int(priority),
            )
        )

    names = [demand.name for demand in demands]
    if len(set(names)) != len(names):
        raise ValueError("Demand names must be unique.")

    changed = tuple(demands) != tuple(twin.demands)
    if changed:
        state.set_demands(tuple(demands))
    return len(demands), changed


def _render_demand_editor(twin: DigitalTwin) -> None:
    st.subheader("Traffic demands")
    st.caption(
        "Demands are stored on the baseline digital twin and are the flows the "
        "model routes. Editing them here changes the baseline for every "
        "scenario. Bandwidth is a stated assumption, not measured traffic."
    )
    device_options = sorted(
        {device.id for device in twin.topology.devices}
        | {demand.source for demand in twin.demands}
        | {demand.destination for demand in twin.demands}
    )
    with st.form("simulation_demand_form"):
        edited = st.data_editor(
            _demand_frame(twin),
            key=editor_key("simulation_demand_editor"),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "name": st.column_config.TextColumn(
                    "Demand name", required=True
                ),
                "source": st.column_config.SelectboxColumn(
                    "Source",
                    options=device_options,
                    required=True,
                ),
                "destination": st.column_config.SelectboxColumn(
                    "Destination",
                    options=device_options,
                    required=True,
                ),
                "bandwidth_mbps": st.column_config.NumberColumn(
                    "Bandwidth (Mbps)",
                    min_value=0.0,
                    format="%.2f",
                ),
                "priority": st.column_config.NumberColumn(
                    "Priority",
                    min_value=0,
                    step=1,
                    format="%d",
                ),
            },
        )
        applied = st.form_submit_button(
            "Apply demand changes",
            key="simulation_apply_demands",
        )
    if applied:
        try:
            count, changed = _apply_demands(twin, edited)
        except (NetArchitectError, ValidationError, ValueError) as error:
            bump_editor_key("simulation_demand_editor")
            _flash("error", f"Demand changes rejected: {format_error(error)}")
            st.rerun()
        else:
            if changed:
                _flash(
                    "success",
                    f"The twin now has {count} traffic demand(s).",
                )
                st.rerun()
            else:
                st.info("No demand changes to apply.")


# ---------------------------------------------------------------------------
# Shared-risk groups (modeled correlated failures)
# ---------------------------------------------------------------------------


def _srg_frame(twin: DigitalTwin) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": group.id,
                "name": group.name,
                "device_ids": ", ".join(group.device_ids),
                "link_ids": ", ".join(group.link_ids),
                "rationale": group.rationale,
            }
            for group in twin.shared_risk_groups
        ],
        columns=["id", "name", "device_ids", "link_ids", "rationale"],
    )


def _parse_id_list(value: object, *, known: set[str], label: str) -> tuple[str, ...]:
    text = _text(value)
    if not text:
        return ()
    ids = tuple(
        dict.fromkeys(
            part.strip()
            for part in re.split(r"[,\n]+", text)
            if part.strip()
        )
    )
    if len(ids) > MAX_SHARED_RISK_MEMBERS:
        raise ValueError(
            f"{label} may name at most {MAX_SHARED_RISK_MEMBERS} entities."
        )
    unknown = sorted(set(ids) - known)
    if unknown:
        raise ValueError(f"Unknown {label}: " + ", ".join(unknown))
    return ids


def _apply_shared_risk_groups(twin: DigitalTwin, edited: pd.DataFrame) -> int:
    groups: list[SharedRiskGroup] = []
    seen: set[str] = set()
    known_devices = {device.id for device in twin.topology.devices}
    known_links = {link.id for link in twin.topology.links}
    for _, row in edited.iterrows():
        group_id = _text(row["id"])
        if not group_id:
            raise ValueError("Every shared-risk group needs a non-empty id.")
        if group_id in seen:
            raise ValueError(f"Duplicate shared-risk group id: {group_id!r}.")
        seen.add(group_id)
        groups.append(
            SharedRiskGroup(
                id=group_id,
                name=_text(row["name"]),
                device_ids=_parse_id_list(
                    row["device_ids"], known=known_devices, label="devices"
                ),
                link_ids=_parse_id_list(
                    row["link_ids"], known=known_links, label="links"
                ),
                rationale=_text(row["rationale"]),
            )
        )
    if len(groups) > MAX_SHARED_RISK_GROUPS:
        raise ValueError(
            f"At most {MAX_SHARED_RISK_GROUPS} shared-risk groups are allowed."
        )
    candidate = twin.model_copy(update={"shared_risk_groups": tuple(groups)})
    report = validate_twin(candidate)
    if not report.is_valid:
        first = next(
            finding for finding in report.findings
            if finding.severity.value in {"error", "critical"}
        )
        raise ValueError(first.explanation)
    changed = tuple(groups) != twin.shared_risk_groups
    if changed:
        state.replace_twin(candidate)
    return len(groups)


def _render_shared_risk_editor(twin: DigitalTwin) -> None:
    st.subheader(i18n.t("simulation.shared_risk.title"))
    st.caption(i18n.t("simulation.shared_risk.caption"))
    with st.form("simulation_shared_risk_form"):
        edited = st.data_editor(
            _srg_frame(twin),
            key=editor_key("simulation_shared_risk_editor"),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "id": st.column_config.TextColumn(
                    i18n.t("simulation.shared_risk.id"), required=True
                ),
                "name": st.column_config.TextColumn(
                    i18n.t("simulation.shared_risk.name")
                ),
                "device_ids": st.column_config.TextColumn(
                    i18n.t("simulation.shared_risk.devices"),
                    help="Comma-separated device ids.",
                ),
                "link_ids": st.column_config.TextColumn(
                    i18n.t("simulation.shared_risk.links"),
                    help="Comma-separated link ids.",
                ),
                "rationale": st.column_config.TextColumn(
                    "Rationale",
                ),
            },
        )
        columns = st.columns(2)
        with columns[0]:
            applied = st.form_submit_button(
                i18n.t("simulation.shared_risk.apply"),
                key="simulation_apply_shared_risk_groups",
                type="primary",
            )
        with columns[1]:
            cleared = st.form_submit_button(
                i18n.t("simulation.shared_risk.clear"),
                key="simulation_clear_shared_risk_groups",
            )
    if cleared:
        if twin.shared_risk_groups:
            state.replace_twin(
                twin.model_copy(update={"shared_risk_groups": ()})
            )
            _flash("success", "Shared-risk groups cleared from the twin.")
            st.rerun()
        st.info("No shared-risk groups are stored on the twin.")
        return
    if not applied:
        return
    try:
        count = _apply_shared_risk_groups(twin, edited)
    except (NetArchitectError, ValidationError, ValueError) as error:
        bump_editor_key("simulation_shared_risk_editor")
        _flash("error", f"Shared-risk groups rejected: {format_error(error)}")
        st.rerun()
        return
    if count == len(twin.shared_risk_groups):
        st.info("No shared-risk group changes to apply.")
    else:
        _flash("success", f"The twin now has {count} shared-risk group(s).")
        st.rerun()


# ---------------------------------------------------------------------------
# Scenario and assumptions form
# ---------------------------------------------------------------------------


def _render_bandwidth_parameters() -> None:
    mode = st.radio(
        "Reduction mode",
        ("Percent reduction", "Mbps reduction"),
        horizontal=True,
        key="simulation_bandwidth_mode",
    )
    st.number_input(
        "Reduction amount",
        min_value=0.001,
        value=25.0 if mode == "Percent reduction" else 50.0,
        step=0.1,
        key="simulation_bandwidth_value",
    )


def _render_traffic_parameters(twin: DigitalTwin) -> None:
    st.number_input(
        "Traffic factor",
        min_value=0.001,
        value=2.0,
        step=0.1,
        key="simulation_traffic_factor",
        help="A factor of 2 doubles the selected demand bandwidths.",
    )
    demand_names = [demand.name for demand in twin.demands]
    _multi_select(
        "Demands to increase (empty means all)",
        demand_names,
        "simulation_traffic_demands",
        "Only these demands are multiplied; leave empty to apply the factor "
        "to every demand in the twin.",
    )


def _render_routing_parameters() -> None:
    mode = st.radio(
        "Cost change mode",
        ("Absolute cost", "Cost factor"),
        horizontal=True,
        key="simulation_cost_mode",
    )
    st.number_input(
        "New value",
        min_value=0.001,
        value=5.0 if mode == "Absolute cost" else 2.0,
        step=0.1,
        key="simulation_cost_value",
        help="A cost factor multiplies each affected link's current cost.",
    )


def _render_expansion_parameters() -> None:
    st.text_area(
        "Expansion entities (JSON)",
        value=EXPANSION_TEMPLATE,
        height=220,
        key="simulation_expansion_json",
        help=(
            "Provide a JSON object with 'devices', 'links', and 'demands' "
            "arrays. Entries use the domain schemas, for example a link needs "
            "'id', 'endpoints', 'capacity_mbps', 'cost', and 'directed'."
        ),
    )


def _render_scenario_fields(twin: DigitalTwin) -> None:
    link_ids = sorted(link.id for link in twin.topology.links)
    device_ids = sorted(device.id for device in twin.topology.devices)
    columns = st.columns(2)
    with columns[0]:
        st.text_input(
            "Scenario id",
            value="scenario-1",
            key="simulation_scenario_id",
        )
    with columns[1]:
        st.text_input(
            "Scenario name",
            value="What-if scenario",
            key="simulation_scenario_name",
        )
    st.text_area(
        "Description",
        value="",
        height=70,
        key="simulation_scenario_description",
    )
    kind_label = st.selectbox(
        "Scenario type",
        SCENARIO_OPTIONS,
        key="simulation_scenario_type",
    )
    kind = SCENARIO_TYPES[kind_label]

    if kind in LINK_SCENARIOS:
        _multi_select(
            "Affected links",
            link_ids,
            "simulation_affected_links",
            "The scenario fails or changes these links; the stored twin is "
            "never modified.",
        )
    if kind in NODE_SCENARIOS:
        _multi_select(
            "Affected devices",
            device_ids,
            "simulation_affected_nodes",
            "The scenario removes these devices and their attached links from "
            "the derived scenario twin.",
        )
    if kind is ScenarioType.bandwidth_reduction:
        _render_bandwidth_parameters()
    elif kind is ScenarioType.increased_traffic_demand:
        _render_traffic_parameters(twin)
    elif kind in EXPANSION_SCENARIOS:
        _render_expansion_parameters()
    elif kind is ScenarioType.routing_cost_change:
        _render_routing_parameters()


def _render_assumptions() -> tuple[float, float, float, str, RoutingMode]:
    with st.expander("Assumptions and congestion thresholds", expanded=False):
        st.caption(
            "Utilization bands are percentages. Latency is estimated only when "
            "every hop on a path has an explicit one-way delay assumption."
        )
        routing_mode = st.selectbox(
            i18n.t("simulation.routing_mode"),
            options=tuple(RoutingMode),
            format_func=lambda mode: i18n.t(
                f"simulation.routing_mode.{mode.value}"
            ),
            key="simulation_routing_mode",
            help=i18n.t("simulation.routing_mode.help"),
        )
        columns = st.columns(3)
        with columns[0]:
            warning = st.number_input(
                "Warning at or above (%)",
                min_value=0.1,
                value=70.0,
                step=1.0,
                key="simulation_warning_percent",
            )
        with columns[1]:
            critical = st.number_input(
                "Critical at or above (%)",
                min_value=0.1,
                value=90.0,
                step=1.0,
                key="simulation_critical_percent",
            )
        with columns[2]:
            overload = st.number_input(
                "Overloaded above (%)",
                min_value=0.1,
                value=100.0,
                step=1.0,
                key="simulation_overload_percent",
            )
        delay_text = st.text_area(
            "Per-link one-way delay assumptions (JSON object of link id -> ms)",
            value="{}",
            height=90,
            key="simulation_link_delays",
        )
    return (
        float(warning),
        float(critical),
        float(overload),
        delay_text,
        routing_mode,
    )


def _parse_assumptions(
    warning: float,
    critical: float,
    overload: float,
    delay_text: str,
    routing_mode: RoutingMode | str | None = None,
) -> SimulationAssumptions:
    try:
        delays = parse_json_text(
            delay_text or "{}", label="Link delay assumptions"
        )
    except InputError as error:
        raise ValueError(
            "Link delay assumptions must be a bounded JSON object."
        ) from error
    if not isinstance(delays, dict):
        raise TypeError("Link delay assumptions must be a JSON object.")
    return SimulationAssumptions(
        thresholds=CongestionThresholds(
            warning_percent=warning,
            critical_percent=critical,
            overload_percent=overload,
        ),
        link_delay_ms=delays,
        routing_mode=(
            RoutingMode.single_path
            if routing_mode is None
            else RoutingMode(routing_mode)
        ),
    )


def _current_assumptions() -> SimulationAssumptions:
    """Build the current assumptions from committed widget state."""
    return _parse_assumptions(
        float(state.session_get("simulation_warning_percent", 70.0)),
        float(state.session_get("simulation_critical_percent", 90.0)),
        float(state.session_get("simulation_overload_percent", 100.0)),
        str(state.session_get("simulation_link_delays", "{}")),
        state.session_get("simulation_routing_mode", RoutingMode.single_path),
    )


def _parse_expansion() -> dict[str, object]:
    raw = state.session_get("simulation_expansion_json", EXPANSION_TEMPLATE)
    try:
        expansion = parse_json_text(raw or "{}", label="Expansion entities")
    except InputError as error:
        raise ValueError(
            "Expansion entities must be a bounded JSON object."
        ) from error
    if not isinstance(expansion, dict):
        raise TypeError("Expansion entities must be a JSON object.")
    return expansion


def _build_scenario() -> Scenario:
    kind_label = state.session_get(
        "simulation_scenario_type",
        SCENARIO_OPTIONS[0],
    )
    kind = SCENARIO_TYPES[kind_label]
    links = (
        list(state.session_get("simulation_affected_links", []))
        if kind in LINK_SCENARIOS
        else []
    )
    nodes = (
        list(state.session_get("simulation_affected_nodes", []))
        if kind in NODE_SCENARIOS
        else []
    )
    parameters: dict[str, object] = {}
    if kind is ScenarioType.bandwidth_reduction:
        mode = state.session_get(
            "simulation_bandwidth_mode",
            "Percent reduction",
        )
        value = float(state.session_get("simulation_bandwidth_value", 25.0))
        parameters["percent" if mode == "Percent reduction" else "mbps"] = value
    elif kind is ScenarioType.increased_traffic_demand:
        parameters["factor"] = float(
            state.session_get("simulation_traffic_factor", 2.0)
        )
        selected = list(state.session_get("simulation_traffic_demands", []))
        if selected:
            parameters["demand_names"] = selected
    elif kind in EXPANSION_SCENARIOS:
        parameters["expansion"] = _parse_expansion()
    elif kind is ScenarioType.routing_cost_change:
        mode = state.session_get("simulation_cost_mode", "Absolute cost")
        value = float(state.session_get("simulation_cost_value", 5.0))
        parameters["cost" if mode == "Absolute cost" else "cost_factor"] = value

    return Scenario(
        id=_text(state.session_get("simulation_scenario_id", "scenario-1")),
        name=_text(state.session_get("simulation_scenario_name", "What-if scenario")),
        type=kind,
        description=_text(state.session_get("simulation_scenario_description", "")),
        affected_links=links,
        affected_nodes=nodes,
        parameters=parameters,
    )


def _copilot_provider():
    """Build a bounded provider, or ``None`` on the deterministic no-key path."""
    key = state.get_llm_session_key() or get_settings().GROQ_API_KEY.strip()
    if not key:
        return None
    return GroqProvider.from_settings(
        api_key=key,
        budget=state.get_llm_budget(),
    )


def _apply_interpreted_scenario(scenario: Scenario) -> None:
    """Fill the manual form only after the user confirms an editable preview."""
    state.session_set("simulation_scenario_id", scenario.id)
    state.session_set("simulation_scenario_name", scenario.name)
    state.session_set("simulation_scenario_description", scenario.description)
    state.session_set("simulation_scenario_type", SCENARIO_LABELS[scenario.type])
    state.session_set("simulation_affected_links", list(scenario.affected_links))
    state.session_set("simulation_affected_nodes", list(scenario.affected_nodes))
    factor = scenario.parameters.get("factor")
    if factor is not None:
        state.session_set("simulation_traffic_factor", float(factor))
    demand_names = scenario.parameters.get("demand_names")
    if demand_names is not None:
        state.session_set("simulation_traffic_demands", list(demand_names))


def _render_copilot_interpretation(twin: DigitalTwin) -> None:
    st.subheader("Describe a scenario")
    st.caption(
        "One short sentence in English or Arabic becomes an editable scenario "
        "draft. Deterministic parsing runs first and needs no API key; free-form "
        "sentences use the optional AI interpreter. Nothing is run until you "
        "confirm the scenario in the form below."
    )
    st.text_input(
        "Scenario sentence",
        key=COPILOT_SENTENCE_KEY,
        max_chars=MAX_COPILOT_TEXT_CHARS,
        placeholder="fail link ab  ·  scale traffic by 50%  ·  عطل الجهاز a",
    )
    if st.button("Interpret sentence", key="simulation_copilot_interpret"):
        sentence = str(state.session_get(COPILOT_SENTENCE_KEY, ""))
        try:
            result = interpret_scenario(
                sentence,
                twin,
                provider=_copilot_provider(),
                cache=state.get_copilot_cache(),
                trace=state.get_copilot_trace(),
            )
        except (NetArchitectError, ValidationError, ValueError) as error:
            st.error(format_error(error), title="Interpretation failed")
            return
        state.session_set(COPILOT_RESULT_KEY, result)
        state.session_set(
            COPILOT_PREVIEW_KEY,
            result.scenario.model_dump_json(indent=2) if result.scenario else "",
        )

    result = state.session_get(COPILOT_RESULT_KEY)
    if result is None:
        return
    for clarification in result.clarifications:
        st.info(clarification.question)
    if result.scenario is None:
        st.caption(
            f"Interpretation source: {result.source.value}. No scenario was run."
        )
        return

    source_label = {
        "deterministic": "deterministic parser",
        "ai": "AI draft (audited)",
        "unavailable": "unavailable",
    }.get(result.source.value, result.source.value)
    st.caption(
        f"Draft from {source_label} · prompt {result.prompt_id} v{result.prompt_version}"
        + (" · cache hit" if result.cache_hit else "")
    )
    edited = st.text_area(
        "Editable scenario (JSON)",
        key=COPILOT_PREVIEW_KEY,
        height=180,
    )
    if st.button(
        "Use in scenario form",
        key="simulation_copilot_apply",
        type="primary",
    ):
        try:
            scenario = Scenario.model_validate_json(edited)
            validate_scenario(twin, scenario)
        except (NetArchitectError, ValidationError, ValueError) as error:
            st.error(format_error(error), title="Scenario draft rejected")
            return
        _apply_interpreted_scenario(scenario)
        st.success(
            "The scenario was copied into the form. Review it below, then run "
            "it explicitly with 'Run scenario'."
        )
        st.rerun()


def _render_scenario_builder(twin: DigitalTwin) -> None:
    st.subheader("Scenario")
    st.caption(
        "A scenario is validated against the baseline twin before anything is "
        "applied. Invalid or unknown references are rejected, not ignored."
    )
    with st.form("simulation_scenario_form"):
        _render_scenario_fields(twin)
        assumption_values = _render_assumptions()
        columns = st.columns(2)
        with columns[0]:
            validate_only = st.form_submit_button(
                "Validate scenario",
                key="simulation_validate_scenario",
            )
        with columns[1]:
            run_now = st.form_submit_button(
                "Run scenario",
                key="simulation_run_scenario",
                type="primary",
            )

    if not validate_only and not run_now:
        return

    try:
        assumptions = _parse_assumptions(*assumption_values)
        scenario = _build_scenario()
        validate_scenario(twin, scenario)
    except (NetArchitectError, ValidationError, TypeError, ValueError) as error:
        st.error(format_error(error), title="Scenario rejected")
        return

    if validate_only:
        st.success(
            f"Scenario {scenario.name!r} is valid against the baseline twin.",
            title="Validation passed",
        )
        return

    history = state.get_simulation_history()
    if len(history) >= MAX_SCENARIOS:
        st.error(
            f"The history holds the maximum {MAX_SCENARIOS} scenario runs. "
            "Delete one below before running another.",
            title="History full",
        )
        return
    try:
        with working(i18n.t("loading.scenario")):
            run = run_scenario(twin, scenario, assumptions)
        state.add_simulation_run(run)
    except (NetArchitectError, ValidationError, ValueError) as error:
        st.error(format_error(error), title="Scenario run failed")
        return
    state.session_set(VIEW_RUN_KEY, run)
    _flash(
        "success",
        f"Ran {scenario.name!r}: {run.comparison.summary}",
    )
    st.rerun()


# ---------------------------------------------------------------------------
# Routing-mode comparison and failure sweeps
# ---------------------------------------------------------------------------


def _comparison_rows(comparison: RoutingModeComparison) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for result in comparison.results:
        state_value = result.state
        rows.append(
            {
                "Routing mode": result.mode.value,
                "Served demands": (
                    f"{state_value.served_demand_count}/{state_value.demand_count}"
                ),
                "Served ratio": round(state_value.served_demand_ratio, 4),
                "Served Mbps": round(state_value.served_demand_mbps, 2),
                "Max utilization (%)": round(state_value.max_utilization_percent, 2),
                "Overloaded links": state_value.overloaded_link_count,
            }
        )
    return rows


def _render_mode_comparison(twin: DigitalTwin) -> None:
    st.subheader(i18n.t("simulation.mode_compare.title"))
    st.caption(i18n.t("simulation.mode_compare.caption"))
    use_scenario = st.toggle(
        "Apply the current scenario to the comparison",
        key="simulation_mode_compare_use_scenario",
        value=False,
    )
    run_clicked = st.button(
        i18n.t("simulation.mode_compare.run"),
        key="simulation_mode_compare_run",
        type="primary",
    )
    if run_clicked:
        scenario = None
        if use_scenario:
            try:
                scenario = _build_scenario()
                validate_scenario(twin, scenario)
            except (NetArchitectError, ValidationError, TypeError, ValueError) as error:
                st.error(format_error(error), title="Scenario rejected")
                return
        try:
            with working(i18n.t("loading.mode_compare")):
                comparison = compare_routing_modes(
                    twin,
                    _current_assumptions(),
                    modes=DEFAULT_COMPARISON_MODES,
                    scenario=scenario,
                    max_runtime_seconds=MAX_SIMULATION_RUNTIME_SECONDS,
                )
            state.add_mode_comparison(comparison)
        except (NetArchitectError, ValidationError, RuntimeError, ValueError) as error:
            st.error(format_error(error), title="Mode comparison failed")
            return
        _flash("success", "Routing-mode comparison saved for this session.")

    comparisons = state.peek_mode_comparisons()
    if not comparisons:
        st.info("Run a routing-mode comparison to see the side-by-side result.")
        return
    comparison = comparisons[-1]
    st.dataframe(
        pd.DataFrame(_comparison_rows(comparison)),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Twin {comparison.twin.fingerprint}; "
        f"scenario {comparison.scenario_id or 'baseline'}. {comparison.model_note}"
    )
    st.download_button(
        i18n.t("simulation.mode_compare.download"),
        data=json.dumps(
            comparison.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8"),
        file_name="routing-mode-comparison.json",
        mime="application/json",
        key="simulation_download_mode_compare",
    )


def _cancel_sweep() -> None:
    state.session_set(SWEEP_CANCEL_KEY, True)


def _sweep_cancelled() -> bool:
    return bool(state.session_get(SWEEP_CANCEL_KEY, False))


def _merge_sweep_results(
    pieces: Sequence[FailureSweepResult],
    stop_reason: FailureSweepStopReason,
) -> FailureSweepResult:
    """Merge bounded slices into one ranked, reportable sweep result."""
    if not pieces:  # pragma: no cover - callers seed an empty piece
        raise ValueError("At least one sweep slice is required.")
    first = pieces[0]
    cases = sorted(
        (case for piece in pieces for case in piece.cases),
        key=lambda case: (
            -case.impact.impact_score,
            -case.impact.newly_unserved_count,
            case.plan.case_id,
        ),
    )
    ranked = tuple(
        case.model_copy(update={"rank": index + 1})
        for index, case in enumerate(cases)
    )
    warnings = tuple(
        dict.fromkeys(warning for piece in pieces for warning in piece.warnings)
    )
    return first.model_copy(
        update={
            "start": 0,
            "limit": None,
            "evaluated_cases": len(ranked),
            "stop_reason": stop_reason,
            "cases": ranked,
            "warnings": warnings,
        }
    )


def _run_sweep_fragment(
    twin: DigitalTwin,
    *,
    depth: FailureSweepDepth,
    selected_links: Sequence[str],
    selected_devices: Sequence[str],
    max_pairs: int,
    slice_size: int,
) -> None:
    """Run bounded slices in this fragment; no worker or thread is used."""
    try:
        plan = plan_failure_sweep(
            twin,
            depth,
            selected_link_ids=selected_links,
            selected_device_ids=selected_devices,
            max_pairs=max_pairs,
        )
    except (NetArchitectError, ValidationError, ValueError) as error:
        state.session_set("simulation_sweep_running", False)
        state.session_set(SWEEP_CANCEL_KEY, False)
        st.error(format_error(error), title="Failure sweep rejected")
        return

    total = plan.total_cases
    pieces = list(state.session_get("simulation_sweep_pieces", []))
    cursor = state.get_sweep_cursor("simulation_sweep", 0)
    if total == 0 and not pieces:
        pieces = [
            run_failure_sweep(
                twin,
                _current_assumptions(),
                depth=depth,
                selected_link_ids=selected_links,
                selected_device_ids=selected_devices,
                max_pairs=max_pairs,
                start=0,
                limit=1,
                max_runtime_seconds=MAX_SIMULATION_RUNTIME_SECONDS,
            )
        ]
    if _sweep_cancelled() and not pieces:
        pieces = [
            run_failure_sweep(
                twin,
                _current_assumptions(),
                depth=depth,
                selected_link_ids=selected_links,
                selected_device_ids=selected_devices,
                max_pairs=max_pairs,
                start=cursor,
                limit=1,
                max_runtime_seconds=MAX_SIMULATION_RUNTIME_SECONDS,
                should_cancel=lambda: True,
            )
        ]
        cursor += len(pieces[0].cases)

    progress = st.progress(
        min(cursor / total, 1.0) if total else 0.0,
        text=f"Evaluated {cursor} of {total} modeled failure cases...",
    )
    deadline = time.perf_counter() + MAX_SIMULATION_RUNTIME_SECONDS
    stop_reason = pieces[-1].stop_reason
    while cursor < total and not _sweep_cancelled():
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            stop_reason = FailureSweepStopReason.runtime_limit
            break
        try:
            piece = run_failure_sweep(
                twin,
                _current_assumptions(),
                depth=depth,
                selected_link_ids=selected_links,
                selected_device_ids=selected_devices,
                max_pairs=max_pairs,
                start=cursor,
                limit=min(slice_size, total - cursor),
                max_runtime_seconds=remaining,
                should_cancel=_sweep_cancelled,
            )
        except (NetArchitectError, ValidationError, ValueError) as error:
            state.session_set("simulation_sweep_running", False)
            state.session_set(SWEEP_CANCEL_KEY, False)
            st.error(format_error(error), title="Failure sweep failed")
            return
        if not piece.cases:
            stop_reason = piece.stop_reason
            break
        pieces.append(piece)
        cursor += len(piece.cases)
        stop_reason = piece.stop_reason
        state.session_set("simulation_sweep_pieces", pieces)
        state.set_sweep_cursor("simulation_sweep", cursor)
        progress.progress(
            cursor / total,
            text=f"Evaluated {cursor} of {total} modeled failure cases...",
        )
        if stop_reason is not FailureSweepStopReason.completed:
            break

    if _sweep_cancelled():
        stop_reason = FailureSweepStopReason.cancelled
    if not pieces:
        pieces = [
            run_failure_sweep(
                twin,
                _current_assumptions(),
                depth=depth,
                selected_link_ids=selected_links,
                selected_device_ids=selected_devices,
                max_pairs=max_pairs,
                start=0,
                limit=1,
                should_cancel=lambda: True,
            )
        ]
    result = _merge_sweep_results(pieces, stop_reason)
    state.add_simulation_sweep(result)
    state.session_set("simulation_sweep_running", False)
    state.session_set(SWEEP_CANCEL_KEY, False)
    state.session_set("simulation_sweep_pieces", [])
    state.set_sweep_cursor("simulation_sweep", 0)
    progress.progress(
        1.0,
        text=f"Finished {result.evaluated_cases} of {result.total_cases} cases.",
    )
    st.rerun()


@st.fragment
def _render_failure_sweep(twin: DigitalTwin) -> None:
    st.subheader(i18n.t("simulation.sweep.title"))
    st.caption(i18n.t("simulation.sweep.caption"))
    link_ids = sorted(link.id for link in twin.topology.links)
    device_ids = sorted(device.id for device in twin.topology.devices)
    depth_label = st.radio(
        i18n.t("simulation.sweep.depth"),
        SWEEP_DEPTH_OPTIONS,
        key="simulation_sweep_depth",
        horizontal=True,
    )
    depth = SWEEP_DEPTH_BY_LABEL[depth_label]
    selected_links: list[str] = []
    selected_devices: list[str] = []
    max_pairs = 1
    if depth is FailureSweepDepth.n2:
        selected_links = st.multiselect(
            i18n.t("simulation.sweep.subset_links"),
            link_ids,
            key="simulation_sweep_links",
        )
        selected_devices = st.multiselect(
            i18n.t("simulation.sweep.subset_devices"),
            device_ids,
            key="simulation_sweep_devices",
        )
        max_pairs = st.slider(
            i18n.t("simulation.sweep.max_pairs"),
            min_value=1,
            max_value=MAX_N2_PAIRS,
            value=min(50, MAX_N2_PAIRS),
            key="simulation_sweep_max_pairs",
        )
    slice_size = st.slider(
        i18n.t("simulation.sweep.slice"),
        min_value=1,
        max_value=25,
        value=5,
        key=SWEEP_SLICE_KEY,
    )
    running = bool(state.session_get("simulation_sweep_running", False))
    columns = st.columns(2)
    with columns[0]:
        start_clicked = st.button(
            i18n.t("simulation.sweep.run"),
            key="simulation_sweep_run",
            type="primary",
            disabled=running,
        )
    with columns[1]:
        st.button(
            i18n.t("simulation.sweep.cancel"),
            key="simulation_sweep_cancel_button",
            on_click=_cancel_sweep,
            disabled=not running,
        )
    if start_clicked:
        state.session_set("simulation_sweep_running", True)
        state.session_set(SWEEP_CANCEL_KEY, False)
        state.session_set("simulation_sweep_pieces", [])
        state.set_sweep_cursor("simulation_sweep", 0)
        running = True
    if running:
        _run_sweep_fragment(
            twin,
            depth=depth,
            selected_links=selected_links,
            selected_devices=selected_devices,
            max_pairs=max_pairs,
            slice_size=slice_size,
        )

    sweeps = state.peek_simulation_sweeps()
    if not sweeps:
        st.info(i18n.t("simulation.sweep.no_result"))
        return
    result = sweeps[-1]
    rows = failure_sweep_rows(result)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No failure case was evaluated.")
    st.caption(
        f"Showing {result.shown_cases} of {result.total_cases} modeled failure "
        f"cases. Stop reason: {result.stop_reason.value}. "
        f"Twin {result.baseline.fingerprint}. {result.model_note}"
    )
    if result.warnings:
        st.warning(" ".join(result.warnings), title="Sweep warnings")
    download_columns = st.columns(2)
    with download_columns[0]:
        st.download_button(
            i18n.t("simulation.sweep.download_json"),
            data=failure_sweep_to_json(result, indent=2).encode("utf-8"),
            file_name="failure-sweep.json",
            mime="application/json",
            key="simulation_download_sweep_json",
        )
    with download_columns[1]:
        st.download_button(
            i18n.t("simulation.sweep.download_csv"),
            data=failure_sweep_to_csv(result).encode("utf-8"),
            file_name="failure-sweep.csv",
            mime="text/csv",
            key="simulation_download_sweep_csv",
        )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def _active_run() -> ScenarioRun | None:
    run = state.session_get(VIEW_RUN_KEY)
    if isinstance(run, ScenarioRun):
        return run
    runs = state.get_simulation_runs()
    return runs[-1] if runs else None


def _row_color(row: pd.Series) -> list[str]:
    color = LEVEL_COLORS.get(str(row.get("Scenario congestion", "")))
    if color is None:
        return [""] * len(row)
    return [f"background-color: {color}"] * len(row)


def _scenario_level_labels(
    link_ids: Sequence[str],
    after: Mapping[str, object],
) -> list[str]:
    """Return visible congestion labels so bar colors are never the only cue."""
    labels: list[str] = []
    for link_id in link_ids:
        link = after.get(link_id)
        level = getattr(getattr(link, "level", None), "value", None)
        labels.append(str(level) if level is not None else "failed")
    return labels


def _render_headline_metrics(run: ScenarioRun) -> None:
    baseline = run.baseline_state
    scenario = run.scenario_state
    comparison = run.comparison
    columns = st.columns(5)
    columns[0].metric(
        "Served demands",
        f"{scenario.served_demand_count}/{scenario.demand_count}",
        delta=formatting.signed_int(
            scenario.served_demand_count - baseline.served_demand_count
        ),
    )
    columns[1].metric(
        "Max utilization",
        formatting.percent(scenario.max_utilization_percent, decimals=2),
        delta=formatting.signed(
            comparison.max_utilization_delta_percent,
            decimals=2,
            unit=" pp",
        ),
        delta_color="inverse",
    )
    columns[2].metric(
        "Congested links",
        scenario.congested_link_count,
        delta=formatting.signed_int(comparison.congested_link_delta),
        delta_color="inverse",
    )
    columns[3].metric(
        "Overloaded links",
        scenario.overloaded_link_count,
        delta=formatting.signed_int(comparison.overloaded_link_delta),
        delta_color="inverse",
    )
    columns[4].metric(
        "Recovery",
        "available" if comparison.recovery_available else "lost",
    )


def _render_traceability(run: ScenarioRun) -> None:
    st.caption(
        f"Scenario: {run.scenario.id} ({SCENARIO_LABELS[run.scenario.type]}). "
        f"Baseline twin: {run.baseline_twin.name}, schema "
        f"{run.baseline_twin.schema_version}, fingerprint "
        f"{run.baseline_twin.fingerprint[:12]}. Scenario twin fingerprint "
        f"{run.scenario_twin.fingerprint[:12]}. Thresholds: warning "
        f"{run.thresholds.warning_percent:g}%, critical "
        f"{run.thresholds.critical_percent:g}%, overloaded above "
        f"{run.thresholds.overload_percent:g}%. Latency assumptions: "
        f"{len(run.assumptions.link_delay_ms)} link(s)."
    )


def _render_utilization_chart(run: ScenarioRun) -> None:
    before = {link.link_id: link for link in run.baseline_state.links}
    after = {link.link_id: link for link in run.scenario_state.links}
    ordered = [
        *(link.link_id for link in run.scenario_state.links),
        *(link.link_id for link in run.baseline_state.links if link.link_id not in after),
    ]
    if not ordered:
        st.info("No links remain to chart.")
        return
    scenario_colors = []
    for link_id in ordered:
        link = after.get(link_id)
        scenario_colors.append(
            LINK_COLORS.get(link.level.value, theme.color("link_undirected"))
            if link is not None
            else LINK_COLORS["failed"]
        )
    level_labels = _scenario_level_labels(ordered, after)
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=ordered,
            y=[
                before[link_id].utilization_percent if link_id in before else 0.0
                for link_id in ordered
            ],
            name="Baseline utilization",
            marker_color=theme.color("link_undirected"),
        )
    )
    figure.add_trace(
        go.Bar(
            x=ordered,
            y=[
                after[link_id].utilization_percent if link_id in after else 0.0
                for link_id in ordered
            ],
            name="Scenario utilization",
            marker_color=scenario_colors,
            text=level_labels,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "%{{x}}<br>Utilization: %{{y:.2f}}%<br>"
                f"{i18n.t('chart.congestion')}: %{{text}}<extra></extra>"
            ),
        )
    )
    for value, label, color in (
        (run.thresholds.warning_percent, "warning", theme.color("util_medium")),
        (run.thresholds.critical_percent, "critical", theme.color("util_high")),
        (run.thresholds.overload_percent, "overload", theme.color("critical")),
    ):
        figure.add_hline(
            y=value,
            line_dash="dot",
            line_color=color,
            line_width=1,
            annotation_text=f"{label} {value:g}%",
            annotation_position="top right",
        )
    figure.update_layout(
        barmode="group",
        height=380,
        margin={"l": 10, "r": 10, "t": 48, "b": 70},
        paper_bgcolor=theme.color("background"),
        plot_bgcolor=theme.color("background"),
        xaxis_title="Link",
        yaxis_title="Utilization (%)",
        xaxis_tickangle=-45,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode="x unified",
    )
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displayModeBar": False},
        alt="Grouped bar chart of baseline and scenario link utilization",
    )


def _render_link_table(run: ScenarioRun) -> None:
    frame = pd.DataFrame(
        link_comparison_rows(run.baseline_state, run.scenario_state)
    )
    if frame.empty:
        st.info("No links exist in either state.")
        return
    st.dataframe(
        frame.style.apply(_row_color, axis=1),
        hide_index=True,
        width="stretch",
    )
    st.download_button(
        "Download link comparison as CSV",
        data=csv_bytes(frame),
        file_name=f"{_safe_slug(run.scenario.name)}-links.csv",
        mime="text/csv",
        key="simulation_download_links",
    )


def _render_path_changes(run: ScenarioRun) -> None:
    show_all = st.checkbox(
        "Show unchanged demand paths",
        value=False,
        key=SHOW_UNCHANGED_PATHS_KEY,
    )
    frame = pd.DataFrame(
        path_change_rows(
            run.baseline_state,
            run.scenario_state,
            only_changed=not show_all,
        )
    )
    if frame.empty:
        st.info("No demand path changed between the baseline and the scenario.")
        return
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download path changes as CSV",
        data=csv_bytes(frame),
        file_name=f"{_safe_slug(run.scenario.name)}-paths.csv",
        mime="text/csv",
        key="simulation_download_paths",
    )


def _render_unserved(run: ScenarioRun) -> None:
    unserved = run.scenario_state.unserved_demands
    if not unserved:
        st.success("Every modeled demand has a path in the scenario.")
        return
    newly = run.comparison.newly_unserved_demands
    if newly:
        st.warning(
            "Newly unserved: " + ", ".join(newly),
            title="Service lost",
        )
    frame = pd.DataFrame(unserved_rows(run.scenario_state))
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download unserved demands as CSV",
        data=csv_bytes(frame),
        file_name=f"{_safe_slug(run.scenario.name)}-unserved.csv",
        mime="text/csv",
        key="simulation_download_unserved",
    )


def _topology_figure(twin: DigitalTwin, run: ScenarioRun) -> go.Figure | None:
    scenario_links = {link.link_id: link for link in run.scenario_state.links}
    lookup: dict[str, tuple[str, str, bool]] = {
        link.id: (link.endpoints[0], link.endpoints[1], link.directed)
        for link in twin.topology.links
    }
    for link in run.scenario_state.links:
        lookup.setdefault(
            link.link_id,
            (link.endpoints[0], link.endpoints[1], link.directed),
        )
    if not lookup:
        return None

    metadata: dict[str, tuple[str, str, str]] = {
        device.id: (device.role.value, device.type.value, device.site)
        for device in twin.topology.devices
    }
    for first, second, _ in lookup.values():
        metadata.setdefault(first, ("unknown", "unknown", "unknown"))
        metadata.setdefault(second, ("unknown", "unknown", "unknown"))
    for device_id in run.scenario_state.failed_devices:
        metadata.setdefault(device_id, ("unknown", "unknown", "unknown"))

    layout_graph = nx.Graph()
    for device_id in metadata:
        layout_graph.add_node(device_id)
    for first, second, _ in lookup.values():
        if not layout_graph.has_edge(first, second):
            layout_graph.add_edge(first, second)
    if layout_graph.number_of_nodes() == 0:
        return None
    positions = nx.spring_layout(layout_graph, seed=42, iterations=60)

    failed_links = set(run.scenario_state.failed_links)
    failed_devices = set(run.scenario_state.failed_devices)
    statuses: dict[str, list[str]] = {
        "normal": [],
        "warning": [],
        "critical": [],
        "overloaded": [],
        "failed": [],
    }
    for link_id in sorted(lookup):
        if link_id in failed_links or link_id not in scenario_links:
            statuses["failed"].append(link_id)
        else:
            statuses[scenario_links[link_id].level.value].append(link_id)

    figure = go.Figure()
    for status in ("normal", "warning", "critical", "overloaded", "failed"):
        link_ids = statuses[status]
        if not link_ids:
            continue
        x_values: list[float | None] = []
        y_values: list[float | None] = []
        for link_id in link_ids:
            first, second, _ = lookup[link_id]
            first_x, first_y = positions[first]
            second_x, second_y = positions[second]
            x_values.extend([first_x, second_x, None])
            y_values.extend([first_y, second_y, None])
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="lines",
                line={
                    "color": LINK_COLORS[status],
                    "width": 3.0 if status in {"overloaded", "failed"} else 1.8,
                    "dash": "dot" if status == "failed" else "solid",
                },
                hoverinfo="skip",
                name=(
                    "Failed / unavailable link"
                    if status == "failed"
                    else f"{status.capitalize()} link"
                ),
            )
        )

    surviving = [
        device_id for device_id in metadata if device_id not in failed_devices
    ]
    roles = sorted({metadata[device_id][0] for device_id in surviving})
    show_labels = len(metadata) <= 30
    for role in roles:
        nodes = [item for item in surviving if metadata[item][0] == role]
        figure.add_trace(
            go.Scatter(
                x=[positions[node][0] for node in nodes],
                y=[positions[node][1] for node in nodes],
                mode="markers+text" if show_labels else "markers",
                text=nodes if show_labels else None,
                textposition="top center",
                textfont={"size": 10, "color": theme.color("chart_text")},
                marker={
                    "size": 18,
                    "color": ROLE_COLORS.get(role, theme.color("role_access")),
                    "line": {"width": 1, "color": theme.color("background")},
                },
                customdata=[
                    [node, metadata[node][1], metadata[node][2], metadata[node][0]]
                    for node in nodes
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>Type: %{customdata[1]}"
                    "<br>Site: %{customdata[2]}<br>Role: %{customdata[3]}"
                    "<extra></extra>"
                ),
                name=role.replace("_", " ").capitalize(),
            )
        )
    failed_nodes = sorted(failed_devices & set(metadata))
    if failed_nodes:
        figure.add_trace(
            go.Scatter(
                x=[positions[node][0] for node in failed_nodes],
                y=[positions[node][1] for node in failed_nodes],
                mode="markers+text" if show_labels else "markers",
                text=failed_nodes if show_labels else None,
                textposition="top center",
                textfont={"size": 10, "color": theme.color("critical")},
                marker={
                    "size": 14,
                    "color": theme.color("critical"),
                    "symbol": "x",
                    "line": {"width": 1, "color": theme.color("critical")},
                },
                hovertemplate="<b>%{text}</b><br>Failed device<extra></extra>",
                name="Failed device",
            )
        )

    figure.update_layout(
        height=520,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        paper_bgcolor=theme.color("background"),
        plot_bgcolor=theme.color("background"),
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11},
        },
        hovermode="closest",
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def _render_topology(twin: DigitalTwin, run: ScenarioRun) -> None:
    st.subheader("Scenario topology")
    st.caption(
        "Deterministic spring layout (seed 42). Failed or unavailable links "
        "are dotted dark red; warning, critical, and overloaded links use the "
        "same colors as the link table. Node color shows hierarchical role."
    )
    figure = _topology_figure(twin, run)
    if figure is None:
        st.info("The baseline topology has no links to display.")
        return
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displayModeBar": False},
        alt="Scenario topology with failed and congested links highlighted",
    )


def _render_exports(run: ScenarioRun) -> None:
    st.subheader("Export")
    st.caption(
        "JSON contains both states and full traceability. CSV exports the "
        "before/after headline metrics. Both are deterministic for this run."
    )
    slug = _safe_slug(run.scenario.name)
    columns = st.columns(2)
    with columns[0]:
        st.download_button(
            "Download result JSON",
            data=run_to_json_bytes(run),
            file_name=f"{slug}-scenario.json",
            mime="application/json",
            key="simulation_download_json",
        )
    with columns[1]:
        st.download_button(
            "Download metrics CSV",
            data=run_to_csv(run),
            file_name=f"{slug}-metrics.csv",
            mime="text/csv",
            key="simulation_download_metrics",
        )


def _render_explanations(run: ScenarioRun) -> None:
    """Explain computed results; deterministic text never depends on an API key."""
    st.markdown("**Explanations**")
    st.caption(
        "The computed explanation is always shown. An AI note is advisory only, "
        "is audited against the computed values, and never sets a verdict."
    )
    why_button("copilot_why_simulation", lambda: simulation_request(run))

    demands = run.baseline_state.demands
    if not demands:
        return
    by_name = {demand.name: demand for demand in demands}
    selected = st.selectbox(
        "Demand to explain",
        list(by_name),
        key=ROUTE_EXPLANATION_SELECT_KEY,
    )
    why_button(
        "copilot_why_route",
        lambda: route_request(by_name[selected], assumptions=run.assumptions),
    )


def _render_results(twin: DigitalTwin) -> None:
    run = _active_run()
    if run is None:
        st.info(
            "No scenario result yet. Add demands, build a scenario, and select "
            "Run scenario."
        )
        return

    st.subheader("Result")
    st.caption(MODEL_NOTE)
    _render_headline_metrics(run)
    st.info(run.comparison.summary, title="Outcome")
    if not run.comparison.recovery_available:
        st.warning(run.comparison.recovery_note, title="Recovery")
    if run.warnings:
        with st.expander("Model warnings", expanded=False):
            for warning in run.warnings:
                st.write(f"- {warning}")
    _render_traceability(run)

    st.markdown("**Before / after metrics**")
    metrics = pd.DataFrame(metric_rows(run.baseline_state, run.scenario_state))
    st.dataframe(metrics, hide_index=True, width="stretch")

    st.markdown("**Link utilization**")
    _render_utilization_chart(run)

    st.markdown("**Link comparison**")
    _render_link_table(run)

    st.markdown("**Path changes**")
    _render_path_changes(run)

    _render_explanations(run)

    st.markdown("**Unserved demands**")
    _render_unserved(run)

    _render_topology(twin, run)
    _render_exports(run)


# ---------------------------------------------------------------------------
# History and comparison
# ---------------------------------------------------------------------------


def _history_frame(runs: tuple[ScenarioRun, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "index": index + 1,
                "scenario": run.scenario.name,
                "type": SCENARIO_LABELS[run.scenario.type],
                "served": run.scenario_state.served_demand_count,
                "unserved": len(run.scenario_state.unserved_demands),
                "max_utilization_%": round(
                    run.scenario_state.max_utilization_percent, 2
                ),
                "congested": run.scenario_state.congested_link_count,
                "recovery": (
                    "available" if run.comparison.recovery_available else "lost"
                ),
            }
            for index, run in enumerate(runs)
        ],
        columns=[
            "index",
            "scenario",
            "type",
            "served",
            "unserved",
            "max_utilization_%",
            "congested",
            "recovery",
        ],
    )


def _run_labels(runs: tuple[ScenarioRun, ...]) -> list[str]:
    return [
        f"{index + 1}. {_scenario_label(run)}"
        for index, run in enumerate(runs)
    ]


def _selected_history_index(runs: tuple[ScenarioRun, ...]) -> int:
    count = len(runs)
    current = state.session_get(HISTORY_SELECT_KEY)
    if current not in range(count):
        current = count - 1
        state.session_set(HISTORY_SELECT_KEY, current)
    labels = _run_labels(runs)
    return st.selectbox(
        "Result to inspect",
        options=range(count),
        index=current,
        format_func=lambda index: labels[index],
        key=HISTORY_SELECT_KEY,
    )


def _render_history() -> None:
    runs = state.get_simulation_runs()
    st.subheader("Session history")
    st.caption(
        "History is bounded to "
        f"{MAX_SCENARIOS} runs and lives only in this session. Results carry no "
        "wall-clock timestamp, so the same inputs remain reproducible."
    )
    if not runs:
        st.info("No scenario runs retained yet.")
        return

    st.dataframe(_history_frame(runs), hide_index=True, width="stretch")
    selected = _selected_history_index(runs)
    columns = st.columns(3)
    with columns[0]:
        if st.button("Load selected result", key="simulation_load_result"):
            state.session_set(VIEW_RUN_KEY, runs[selected])
            _flash("success", f"Loaded {runs[selected].scenario.name!r}.")
            st.rerun()
    with columns[1]:
        if st.button("Delete selected result", key="simulation_delete_result"):
            removed = state.remove_simulation_run(selected)
            current = state.session_get(VIEW_RUN_KEY)
            remaining = state.get_simulation_runs()
            if current == removed or current is removed:
                if remaining:
                    state.session_set(VIEW_RUN_KEY, remaining[-1])
                else:
                    state.session_delete(VIEW_RUN_KEY)
            _flash("success", f"Deleted {removed.scenario.name!r}.")
            st.rerun()
    with columns[2]:
        if st.button("Clear history", key="simulation_clear_history"):
            state.clear_simulation_history()
            state.session_delete(VIEW_RUN_KEY)
            _flash("success", "Cleared the scenario history.")
            st.rerun()


def _choose_history_run(
    label: str,
    key: str,
    labels: list[str],
    default: int,
) -> int:
    count = len(labels)
    current = state.session_get(key)
    if current not in range(count):
        current = default
        state.session_set(key, current)
    return st.selectbox(
        label,
        options=range(count),
        index=current,
        format_func=lambda index: labels[index],
        key=key,
    )


def _render_comparison() -> None:
    runs = state.get_simulation_runs()
    st.subheader("Compare two results")
    if len(runs) < 2:
        st.info("Run at least two scenarios to compare retained results.")
        return
    columns = st.columns(2)
    labels = _run_labels(runs)
    with columns[0]:
        left_index = _choose_history_run(
            "Left result",
            COMPARE_LEFT_KEY,
            labels,
            0,
        )
    with columns[1]:
        right_index = _choose_history_run(
            "Right result",
            COMPARE_RIGHT_KEY,
            labels,
            len(runs) - 1,
        )
    if left_index == right_index:
        st.info("Choose two different results to compare.")
        return

    left = runs[left_index]
    right = runs[right_index]
    comparison = compare_runs(left, right)
    st.caption(
        f"Left: {left.scenario.name!r}. Right: {right.scenario.name!r}. "
        "Positive deltas mean the right result is higher."
    )
    st.dataframe(
        pd.DataFrame(metric_rows(left.scenario_state, right.scenario_state)),
        hide_index=True,
        width="stretch",
    )
    link_frame = pd.DataFrame(
        link_comparison_rows(left.scenario_state, right.scenario_state)
    )
    link_frame = link_frame[link_frame["Change"] != "unchanged"]
    st.markdown("**Changed links**")
    if link_frame.empty:
        st.info("No link was added, removed, or moved to another band.")
    else:
        st.dataframe(
            link_frame.style.apply(_row_color, axis=1),
            hide_index=True,
            width="stretch",
        )
    paths = pd.DataFrame(
        path_change_rows(
            left.scenario_state,
            right.scenario_state,
            only_changed=True,
        )
    )
    st.markdown("**Changed paths**")
    if paths.empty:
        st.info("No demand path differs between the two results.")
    else:
        st.dataframe(paths, hide_index=True, width="stretch")
    st.download_button(
        "Download comparison metrics as CSV",
        data=csv_bytes(
            pd.DataFrame(
                metric_rows(left.scenario_state, right.scenario_state)
            )
        ),
        file_name="scenario-comparison.csv",
        mime="text/csv",
        key="simulation_download_comparison",
    )
    st.caption(comparison.summary)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def _render_empty_state() -> None:
    st.info(
        "No digital twin is loaded. Open the Topology Editor from the sidebar "
        "to create, generate, or import a topology, then return to this page."
    )
    st.caption(
        "Simulation reads the baseline digital twin and never modifies it. "
        "Scenario results are modeled estimates, not packet-level measurements."
    )


def render() -> None:
    """Render the Simulation Lab page."""
    page_header(
        "Simulation Lab",
        "Run deterministic what-if scenarios over the digital twin. Every "
        "latency, throughput, and utilization value is a modeled estimate from "
        "the assumptions on this page; nothing is packet-level or "
        "hardware-accurate.",
    )
    model_estimate_note(MODEL_NOTE)
    _render_flash()

    twin = state.get_twin()
    if twin is None or not twin.topology.devices:
        _render_empty_state()
        return

    _render_demand_editor(twin)
    st.divider()
    _render_shared_risk_editor(twin)
    st.divider()
    _render_copilot_interpretation(twin)
    st.divider()
    _render_scenario_builder(twin)
    st.divider()
    _render_mode_comparison(twin)
    st.divider()
    _render_failure_sweep(twin)
    st.divider()
    _render_results(twin)
    st.divider()
    _render_history()
    st.divider()
    _render_comparison()
