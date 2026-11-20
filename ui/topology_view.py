"""Deterministic layered topology diagram and entity inspector.

The diagram is derived only from the current session topology and retained
simulation results. Layout, symbols, colors, labels, and selection metadata are
pure functions so they can be tested without a browser. Plotly selection is
optional: the inspector also exposes a keyboard-reachable entity picker.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from core.schemas.network import Device, DeviceType, Topology
from simulation import ScenarioRun, twin_fingerprint
from ui import state, theme
from ui.components import key_value_list, section_header
from ui.navigation import PAGE_FILES

CHART_KEY = "topology_view_chart_a"
CHART_KEY_ALT = "topology_view_chart_b"
ACTIVE_CHART_KEY_KEY = "topology_view_active_chart"
SELECTION_KEY = "topology_view_selection"
ENTITY_SELECT_KEY = "topology_view_entity_select"
COLOR_MODE_KEY = "topology_view_color_mode"

NONE_OPTION = "(none)"
COLOR_MODES = ("Role", "Zone", "Utilization")

DEVICE_SYMBOLS = MappingProxyType(
    {
        DeviceType.router.value: "diamond",
        DeviceType.switch.value: "square",
        DeviceType.layer3_switch.value: "cross",
        DeviceType.firewall.value: "hexagon",
        DeviceType.load_balancer.value: "bowtie",
        DeviceType.access_point.value: "triangle-up",
        DeviceType.server.value: "circle",
        DeviceType.host.value: "triangle-down",
        DeviceType.controller.value: "star",
        DeviceType.modem.value: "pentagon",
    }
)

ROLE_TIERS = MappingProxyType(
    {
        "wan": 0,
        "border": 0,
        "dmz": 1,
        "core": 1,
        "distribution": 2,
        "aggregation": 2,
        "access": 3,
        "edge": 3,
    }
)
ENDPOINT_TYPES = frozenset({DeviceType.server.value, DeviceType.host.value})
ZONE_TOKENS = tuple(f"zone_{index}" for index in range(1, 7))
UTILIZATION_TOKENS = (
    "util_none",
    "util_low",
    "util_medium",
    "util_high",
    "util_overload",
)
UTILIZATION_LABELS = MappingProxyType(
    {
        "util_none": "No data",
        "util_low": "Low (<70%)",
        "util_medium": "Medium (70-89%)",
        "util_high": "High (90-100%)",
        "util_overload": "Overload (>100%)",
    }
)

MAX_LABELS = 30
MAX_TIER_SPAN = 12.0
TIER_DISTANCE = 2.4
MAX_INSPECT_OPTIONS = 200

SIMULATION_TYPE_KEY = "simulation_scenario_type"
SIMULATION_LINK_KEY = "simulation_affected_links"
SIMULATION_NODE_KEY = "simulation_affected_nodes"


@dataclass(frozen=True)
class LayeredLayout:
    """Stable diagram coordinates and role tiers for one topology."""

    positions: Mapping[str, tuple[float, float]]
    tiers: Mapping[str, int]


def device_tier(device: Device) -> int:
    """Return the deterministic hierarchy tier for one device."""
    tier = ROLE_TIERS.get(device.role.value, 2)
    if tier >= 3 and device.type.value in ENDPOINT_TYPES:
        return 4
    return tier


def layered_layout(topology: Topology) -> LayeredLayout:
    """Place devices in bounded, left-to-right tiers.

    Devices are ordered by tier, site, and id, so the same topology always
    produces the same coordinates. Large tiers are compressed to a fixed span
    instead of growing without bound.
    """
    tiers = {device.id: device_tier(device) for device in topology.devices}
    grouped: dict[int, list[str]] = defaultdict(list)
    for device in sorted(
        topology.devices,
        key=lambda item: (tiers[item.id], item.site, item.id),
    ):
        grouped[tiers[device.id]].append(device.id)

    positions: dict[str, tuple[float, float]] = {}
    for tier, device_ids in grouped.items():
        count = len(device_ids)
        spacing = 1.0 if count == 1 else min(1.0, MAX_TIER_SPAN / (count - 1))
        for index, device_id in enumerate(device_ids):
            y_position = (index - (count - 1) / 2) * spacing
            positions[device_id] = (tier * TIER_DISTANCE, y_position)
    return LayeredLayout(positions=positions, tiers=tiers)


def should_show_labels(device_count: int) -> bool:
    """Thin device labels once a diagram becomes too dense to read."""
    return 0 < device_count <= MAX_LABELS


def zone_token(site: str) -> str:
    """Map a site id to a stable, bounded zone color token."""
    digest = sha256(site.encode("utf-8")).hexdigest()
    return ZONE_TOKENS[int(digest[:8], 16) % len(ZONE_TOKENS)]


def utilization_token(value: float | None) -> str:
    """Classify a utilization percentage against the shared thresholds."""
    if value is None or value <= 0:
        return "util_none"
    if value > 100:
        return "util_overload"
    if value >= 90:
        return "util_high"
    if value >= 70:
        return "util_medium"
    return "util_low"


def utilization_label(token: str) -> str:
    """Return the text label for one utilization color token."""
    return UTILIZATION_LABELS.get(token, "No data")


def device_color(
    device: Device,
    mode: str,
    utilization_percent: float | None,
) -> tuple[str, str]:
    """Return the legend label and color token for one device."""
    if mode == "Role":
        token = theme.ROLE_TOKEN_NAMES.get(device.role.value, "role_access")
        return device.role.value.replace("_", " ").title(), token
    if mode == "Zone":
        token = zone_token(device.site)
        return token.replace("_", " ").title(), token
    if mode == "Utilization":
        token = utilization_token(utilization_percent)
        return utilization_label(token), token
    raise ValueError(f"Unsupported color mode: {mode!r}")


def current_utilization(
    runs: Sequence[ScenarioRun],
    twin: object | None,
) -> dict[str, float]:
    """Return link utilization from the latest run on the current twin."""
    if twin is None:
        return {}
    fingerprint = twin_fingerprint(twin)  # type: ignore[arg-type]
    for run in reversed(runs):
        if run.baseline_twin.fingerprint == fingerprint:
            return {
                load.link_id: float(load.utilization_percent)
                for load in run.baseline_state.links
            }
    return {}


def _legend_labels(color_mode: str) -> tuple[tuple[str, str], ...]:
    if color_mode == "Role":
        return tuple(
            (name.replace("_", " ").title(), token)
            for name, token in sorted(theme.ROLE_TOKEN_NAMES.items())
        )
    if color_mode == "Zone":
        return tuple(
            (token.replace("_", " ").title(), token) for token in ZONE_TOKENS
        )
    if color_mode == "Utilization":
        return tuple(
            (label, token) for token, label in UTILIZATION_LABELS.items()
        )
    raise ValueError(f"Unsupported color mode: {color_mode!r}")


def _device_utilization(
    topology: Topology,
    utilization: Mapping[str, float],
) -> dict[str, float | None]:
    attached: dict[str, list[float]] = defaultdict(list)
    for link in topology.links:
        value = utilization.get(link.id)
        if value is None:
            continue
        for endpoint in link.endpoints:
            attached[endpoint].append(value)
    return {
        device.id: max(attached[device.id]) if attached.get(device.id) else None
        for device in topology.devices
    }


def _legend_trace(
    *,
    name: str,
    symbol: str | None = None,
    color: str | None = None,
    dash: str | None = None,
) -> go.Scatter:
    """Add one metadata-only trace that keeps the legend order stable."""
    if dash is not None:
        return go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            line={"color": color, "width": 2, "dash": dash},
            name=name,
            showlegend=True,
            hoverinfo="skip",
        )
    return go.Scatter(
        x=[None],
        y=[None],
        mode="markers",
        marker={
            "symbol": symbol or "circle",
            "color": color or theme.color("muted"),
            "size": 12,
        },
        name=name,
        showlegend=True,
        hoverinfo="skip",
    )


def build_topology_figure(
    topology: Topology,
    *,
    color_mode: str = "Role",
    utilization: Mapping[str, float] | None = None,
    selected: Mapping[str, str] | None = None,
) -> go.Figure:
    """Build the layered, selectable Plotly figure for one topology."""
    if color_mode not in COLOR_MODES:
        raise ValueError(f"Unsupported color mode: {color_mode!r}")
    utilization = utilization or {}
    layout = layered_layout(topology)
    device_utilization = _device_utilization(topology, utilization)
    show_labels = should_show_labels(len(topology.devices))
    palette = theme.active_palette()
    background = theme.color("background", palette=palette)
    figure = go.Figure()

    for directed, dash in ((False, "solid"), (True, "dash")):
        x_values: list[float | None] = []
        y_values: list[float | None] = []
        for link in topology.links:
            if link.directed is not directed:
                continue
            first = layout.positions[link.endpoints[0]]
            second = layout.positions[link.endpoints[1]]
            x_values.extend([first[0], second[0], None])
            y_values.extend([first[1], second[1], None])
        if x_values:
            figure.add_trace(
                go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode="lines",
                    line={
                        "color": theme.color("link_undirected", palette=palette),
                        "width": 1.4,
                        "dash": dash,
                    },
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    link_groups: dict[tuple[str, str], list] = defaultdict(list)
    for link in topology.links:
        if color_mode == "Utilization":
            token = utilization_token(utilization.get(link.id))
            label = utilization_label(token)
        else:
            token = "link_undirected"
            label = "Link"
        link_groups[(label, token)].append(link)
    for (label, token), links in link_groups.items():
        x_values = []
        y_values = []
        customdata = []
        for link in sorted(links, key=lambda item: item.id):
            first = layout.positions[link.endpoints[0]]
            second = layout.positions[link.endpoints[1]]
            x_values.append((first[0] + second[0]) / 2)
            y_values.append((first[1] + second[1]) / 2)
            value = utilization.get(link.id)
            customdata.append(
                [
                    "link",
                    link.id,
                    f"{link.endpoints[0]} - {link.endpoints[1]}",
                    f"{link.capacity_mbps:.1f} Mbps",
                    f"{link.cost:.2f}",
                    "Directed" if link.directed else "Undirected",
                    "n/a" if value is None else f"{value:.1f}%",
                ]
            )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="markers",
                marker={
                    "symbol": "circle",
                    "size": 10,
                    "color": theme.color(token, palette=palette),
                    "line": {"color": background, "width": 1},
                },
                customdata=customdata,
                hovertemplate=(
                    "<b>Link %{customdata[1]}</b><br>Endpoints: %{customdata[2]}"
                    "<br>Capacity: %{customdata[3]}"
                    "<br>Routing cost: %{customdata[4]}"
                    "<br>Style: %{customdata[5]}"
                    "<br>Utilization: %{customdata[6]}<extra></extra>"
                ),
                name=f"Link: {label}",
                showlegend=False,
            )
        )

    device_groups: dict[tuple[str, str, str], list[Device]] = defaultdict(list)
    for device in topology.devices:
        label, token = device_color(
            device, color_mode, device_utilization[device.id]
        )
        device_groups[(device.type.value, label, token)].append(device)
    for (device_type, label, token), devices in device_groups.items():
        customdata = []
        for device in sorted(devices, key=lambda item: item.id):
            value = device_utilization[device.id]
            customdata.append(
                [
                    "device",
                    device.id,
                    device.type.value,
                    device.site,
                    device.role.value,
                    str(layout.tiers[device.id]),
                    label,
                    "n/a" if value is None else f"{value:.1f}%",
                ]
            )
        figure.add_trace(
            go.Scatter(
                x=[layout.positions[device.id][0] for device in devices],
                y=[layout.positions[device.id][1] for device in devices],
                mode="markers+text" if show_labels else "markers",
                text=[device.id for device in devices] if show_labels else None,
                textposition="top center",
                textfont={"size": 10, "color": theme.color("chart_text", palette=palette)},
                marker={
                    "symbol": DEVICE_SYMBOLS[device_type],
                    "size": 18,
                    "color": theme.color(token, palette=palette),
                    "line": {"color": background, "width": 1},
                },
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>Type: %{customdata[2]}"
                    "<br>Site: %{customdata[3]}<br>Role: %{customdata[4]}"
                    "<br>Tier: %{customdata[5]}<br>Color: %{customdata[6]}"
                    "<br>Max link utilization: %{customdata[7]}"
                    "<extra></extra>"
                ),
                name=f"Device: {label}",
                showlegend=False,
            )
        )

    if selected and selected.get("kind") == "device":
        device_id = selected.get("id")
        if device_id in layout.positions:
            x_position, y_position = layout.positions[device_id]
            figure.add_trace(
                go.Scatter(
                    x=[x_position],
                    y=[y_position],
                    mode="markers",
                    marker={
                        "symbol": "circle-open",
                        "size": 32,
                        "color": theme.color("highlight", palette=palette),
                    },
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    for device_type in sorted(DEVICE_SYMBOLS):
        figure.add_trace(
            _legend_trace(
                name=f"Type: {device_type.replace('_', ' ').title()}",
                symbol=DEVICE_SYMBOLS[device_type],
                color=theme.color("muted", palette=palette),
            )
        )
    for label, token in _legend_labels(color_mode):
        figure.add_trace(
            _legend_trace(
                name=f"{color_mode}: {label}",
                color=theme.color(token, palette=palette),
            )
        )
    for label, dash in (("Undirected link", "solid"), ("Directed link", "dash")):
        figure.add_trace(
            _legend_trace(
                name=label,
                dash=dash,
                color=theme.color("link_undirected", palette=palette),
            )
        )

    max_tier = max(layout.tiers.values(), default=0)
    figure.update_layout(
        height=560,
        margin={"l": 12, "r": 12, "t": 20, "b": 95},
        paper_bgcolor=background,
        plot_bgcolor=background,
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.04,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 10},
        },
        hovermode="closest",
    )
    figure.update_xaxes(
        visible=False,
        range=[-1.2, max_tier * TIER_DISTANCE + 1.2],
    )
    figure.update_yaxes(
        visible=False,
        range=[-MAX_TIER_SPAN / 2 - 1, MAX_TIER_SPAN / 2 + 1],
    )
    return figure


def _points_from_event(event: object) -> list[Any]:
    if isinstance(event, Mapping):
        selection = event.get("selection", {})
        return list(selection.get("points", [])) if isinstance(selection, Mapping) else []
    selection = getattr(event, "selection", None)
    points = (
        selection.get("points", [])
        if isinstance(selection, Mapping)
        else getattr(selection, "points", [])
    )
    return list(points or [])


def selection_from_event(event: object) -> dict[str, str] | None:
    """Normalize a Plotly selection from either PlotlyState or AppTest dict."""
    for point in _points_from_event(event):
        customdata = (
            point.get("customdata")
            if isinstance(point, Mapping)
            else getattr(point, "customdata", None)
        )
        if isinstance(customdata, Mapping):
            kind = customdata.get("kind", customdata.get(0))
            entity_id = customdata.get("id", customdata.get(1))
        elif isinstance(customdata, Sequence) and not isinstance(customdata, str):
            kind = customdata[0] if len(customdata) > 0 else None
            entity_id = customdata[1] if len(customdata) > 1 else None
        else:
            continue
        if kind in {"device", "link"} and isinstance(entity_id, str):
            return {"kind": kind, "id": entity_id}
    return None


def _active_chart_key() -> str:
    """Return the currently mounted chart widget key."""
    value = state.session_get(ACTIVE_CHART_KEY_KEY, CHART_KEY)
    return value if value in {CHART_KEY, CHART_KEY_ALT} else CHART_KEY


def _toggle_chart_key() -> None:
    """Swap between two bounded chart keys to clear a Plotly selection.

    Plotly widget keys are read-only after mounting, so resetting the selection
    requires remounting the chart with the alternate key. Only two keys are ever
    used, keeping selection state bounded.
    """
    current = _active_chart_key()
    state.session_set(
        ACTIVE_CHART_KEY_KEY,
        CHART_KEY_ALT if current == CHART_KEY else CHART_KEY,
    )


def _valid_selection(
    value: object,
    topology: Topology,
) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    kind, entity_id = value.get("kind"), value.get("id")
    if not isinstance(entity_id, str):
        return None
    if kind == "device" and any(device.id == entity_id for device in topology.devices):
        return {"kind": "device", "id": entity_id}
    if kind == "link" and any(link.id == entity_id for link in topology.links):
        return {"kind": "link", "id": entity_id}
    return None


def _entity_options(topology: Topology) -> list[str]:
    devices = [f"device:{device.id}" for device in topology.devices]
    links = [f"link:{link.id}" for link in topology.links]
    return [NONE_OPTION, *sorted(devices), *sorted(links)][
        : MAX_INSPECT_OPTIONS + 1
    ]


def _option_for_selection(selection: Mapping[str, str] | None) -> str:
    if selection is None:
        return NONE_OPTION
    return f"{selection['kind']}:{selection['id']}"


def _clear_selection() -> None:
    state.session_set(SELECTION_KEY, None)
    state.session_set(ENTITY_SELECT_KEY, NONE_OPTION)
    _toggle_chart_key()


def _selection_widget_changed() -> None:
    value = state.session_get(ENTITY_SELECT_KEY, NONE_OPTION)
    if isinstance(value, str) and value.startswith(("device:", "link:")):
        kind, entity_id = value.split(":", 1)
        state.session_set(SELECTION_KEY, {"kind": kind, "id": entity_id})
    else:
        state.session_set(SELECTION_KEY, None)
    _toggle_chart_key()


def _queue_link_failure(link_id: str) -> None:
    state.session_set(SIMULATION_TYPE_KEY, "Single link failure")
    state.session_set(SIMULATION_LINK_KEY, [link_id])


def _queue_device_failure(device_id: str) -> None:
    state.session_set(SIMULATION_TYPE_KEY, "Node failure")
    state.session_set(SIMULATION_NODE_KEY, [device_id])


def _render_inspector(
    topology: Topology,
    selection: Mapping[str, str] | None,
    utilization: Mapping[str, float],
) -> None:
    with st.container(border=True):
        st.subheader("Inspector")
        st.button(
            "Clear selection",
            key="topology_view_clear_selection",
            on_click=_clear_selection,
            disabled=selection is None,
        )
        options = _entity_options(topology)
        option = _option_for_selection(selection)
        if option not in options:
            options.insert(1, option)
        if ENTITY_SELECT_KEY not in st.session_state:
            state.session_set(ENTITY_SELECT_KEY, option)
        st.selectbox(
            "Inspect entity",
            options,
            key=ENTITY_SELECT_KEY,
            on_change=_selection_widget_changed,
            help="Keyboard-accessible alternative to clicking the diagram.",
        )

        if selection is None:
            st.info(
                "Click a device or a link midpoint to inspect it. The picker "
                "above provides the same selection without a pointer."
            )
            return

        entity_id = selection["id"]
        if selection["kind"] == "device":
            device = next(
                (item for item in topology.devices if item.id == entity_id), None
            )
            if device is None:
                return
            value = utilization.get(
                next(
                    (
                        link.id
                        for link in topology.links
                        if entity_id in link.endpoints
                    ),
                    "",
                )
            )
            st.markdown(f"**Device: {device.id}**")
            key_value_list(
                [
                    ("Type", device.type.value),
                    ("Site / zone", device.site),
                    ("Role", device.role.value),
                    ("Tier", layered_layout(topology).tiers[device.id]),
                    ("Attached links", sum(
                        entity_id in link.endpoints for link in topology.links
                    )),
                    ("Link utilization", "n/a" if value is None else f"{value:.1f}%"),
                ]
            )
            st.button(
                "Queue node failure",
                key="topology_view_queue_device_failure",
                on_click=_queue_device_failure,
                args=(device.id,),
            )
            st.page_link(
                PAGE_FILES["Simulation Lab"],
                label="Open Simulation Lab",
                icon=":material/bolt:",
            )
            return

        link = next((item for item in topology.links if item.id == entity_id), None)
        if link is None:
            return
        value = utilization.get(link.id)
        st.markdown(f"**Link: {link.id}**")
        key_value_list(
            [
                ("Endpoints", " - ".join(link.endpoints)),
                ("Capacity", f"{link.capacity_mbps:.1f} Mbps"),
                ("Routing cost", f"{link.cost:.2f}"),
                ("Style", "Directed" if link.directed else "Undirected"),
                ("Utilization", "n/a" if value is None else f"{value:.1f}%"),
            ]
        )
        st.button(
            "Queue link failure",
            key="topology_view_queue_link_failure",
            on_click=_queue_link_failure,
            args=(link.id,),
        )
        st.page_link(
            PAGE_FILES["Simulation Lab"],
            label="Open Simulation Lab",
            icon=":material/bolt:",
        )


def render_topology_view(topology: Topology) -> None:
    """Render the diagram and inspector for the current topology."""
    section_header(
        "Diagram",
        description=(
            "Deterministic left-to-right tiers. Marker shape shows device type; "
            "color shows the selected dimension. Click a device or link midpoint "
            "to inspect it."
        ),
    )
    if not topology.devices:
        st.info("The topology has no devices to display.")
        return

    color_mode = st.selectbox(
        "Color by",
        COLOR_MODES,
        key=COLOR_MODE_KEY,
    )
    twin = state.peek_twin()
    utilization = current_utilization(state.peek_simulation_runs(), twin)
    figure = build_topology_figure(
        topology,
        color_mode=color_mode,
        utilization=utilization,
        selected=_valid_selection(state.session_get(SELECTION_KEY), topology),
    )

    chart_column, inspector_column = st.columns([4, 1.5])
    with chart_column:
        event = st.plotly_chart(
            figure,
            width="stretch",
            config={"displayModeBar": False},
            on_select="rerun",
            selection_mode="points",
            key=_active_chart_key(),
            alt=(
                f"Layered topology diagram with {len(topology.devices)} devices and "
                f"{len(topology.links)} links"
            ),
        )

    chart_selection = selection_from_event(event)
    if chart_selection is not None:
        state.session_set(SELECTION_KEY, chart_selection)
    selection = _valid_selection(state.session_get(SELECTION_KEY), topology)
    if selection is None:
        state.session_delete(SELECTION_KEY)
    else:
        state.session_set(ENTITY_SELECT_KEY, _option_for_selection(selection))

    with inspector_column:
        _render_inspector(topology, selection, utilization)


__all__ = [
    "CHART_KEY",
    "COLOR_MODES",
    "DEVICE_SYMBOLS",
    "ENTITY_SELECT_KEY",
    "SELECTION_KEY",
    "LayeredLayout",
    "build_topology_figure",
    "current_utilization",
    "device_color",
    "device_tier",
    "layered_layout",
    "render_topology_view",
    "selection_from_event",
    "should_show_labels",
    "utilization_token",
    "zone_token",
]
