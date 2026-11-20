"""Tests for the deterministic layered topology diagram and inspector."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from tests.unit.ui.nav_helpers import open_page
from ui import state, theme, topology_view

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _device(
    device_id: str,
    device_type: DeviceType,
    role: DeviceRole,
    *,
    site: str = "site-a",
) -> Device:
    return Device(id=device_id, type=device_type, site=site, role=role)


def _topology() -> Topology:
    return Topology(
        name="Layered sample",
        devices=[
            _device("wan", DeviceType.modem, DeviceRole.wan),
            _device("core", DeviceType.router, DeviceRole.core),
            _device("dist", DeviceType.layer3_switch, DeviceRole.distribution),
            _device("access", DeviceType.switch, DeviceRole.access),
            _device("host", DeviceType.host, DeviceRole.access),
        ],
        links=[
            Link(
                id="wan-core",
                endpoints=("wan", "core"),
                capacity_mbps=1000,
                cost=1,
            ),
            Link(
                id="core-dist",
                endpoints=("core", "dist"),
                capacity_mbps=1000,
                cost=1,
                directed=True,
            ),
        ],
    )


def test_layered_layout_is_deterministic_and_follows_role_order() -> None:
    topology = _topology()

    first = topology_view.layered_layout(topology)
    second = topology_view.layered_layout(topology)

    assert first == second
    assert first.tiers["wan"] < first.tiers["core"] < first.tiers["dist"]
    assert first.tiers["dist"] < first.tiers["access"] < first.tiers["host"]
    assert first.positions["core"][0] < first.positions["dist"][0]
    assert first.positions["dist"][0] < first.positions["access"][0]


def test_large_tier_layout_is_bounded_and_labels_are_thinned() -> None:
    devices = [
        _device(f"d{index:03d}", DeviceType.switch, DeviceRole.access)
        for index in range(120)
    ]
    topology = Topology(name="Large", devices=devices, links=[])

    layout = topology_view.layered_layout(topology)
    y_values = [position[1] for position in layout.positions.values()]

    assert max(y_values) <= topology_view.MAX_TIER_SPAN / 2
    assert min(y_values) >= -topology_view.MAX_TIER_SPAN / 2
    assert topology_view.should_show_labels(1) is True
    assert topology_view.should_show_labels(topology_view.MAX_LABELS + 1) is False

    figure = topology_view.build_topology_figure(topology)
    device_traces = [
        trace for trace in figure.data if trace.name and trace.name.startswith("Device:")
    ]
    assert device_traces
    assert all(trace.text is None for trace in device_traces)


def test_symbols_and_legend_cover_device_types_and_color_modes() -> None:
    assert set(topology_view.DEVICE_SYMBOLS) == {item.value for item in DeviceType}
    topology = _topology()

    for mode in topology_view.COLOR_MODES:
        figure = topology_view.build_topology_figure(topology, color_mode=mode)
        names = [trace.name for trace in figure.data if trace.showlegend]
        assert "Type: Router" in names
        assert "Type: Layer3 Switch" in names
        assert "Undirected link" in names
        assert "Directed link" in names
        assert any(name.startswith(f"{mode}: ") for name in names)


def test_device_colors_cover_zone_role_and_utilization() -> None:
    device = _device("core", DeviceType.router, DeviceRole.core)

    assert topology_view.zone_token("site-a") == topology_view.zone_token("site-a")
    assert topology_view.zone_token("site-a") in topology_view.ZONE_TOKENS
    assert topology_view.device_color(device, "Role", None)[1] == "role_core"
    assert topology_view.device_color(device, "Zone", None)[1].startswith("zone_")
    assert topology_view.device_color(device, "Utilization", None)[1] == "util_none"
    assert topology_view.utilization_token(50) == "util_low"
    assert topology_view.utilization_token(75) == "util_medium"
    assert topology_view.utilization_token(95) == "util_high"
    assert topology_view.utilization_token(110) == "util_overload"


@pytest.mark.parametrize(
    ("mode", "token"),
    [
        ("Role", "role_core"),
        ("Zone", topology_view.zone_token("site-a")),
        ("Utilization", "util_medium"),
    ],
)
def test_figure_uses_theme_tokens_for_selected_color_mode(mode: str, token: str) -> None:
    topology = _topology()
    figure = topology_view.build_topology_figure(
        topology,
        color_mode=mode,
        utilization={"wan-core": 75.0},
    )
    colors = {
        trace.marker.color
        for trace in figure.data
        if trace.customdata is not None and trace.marker.color is not None
    }
    assert theme.color(token) in colors


def test_figure_has_hover_details_and_selection_metadata() -> None:
    topology = _topology()
    figure = topology_view.build_topology_figure(
        topology,
        utilization={"wan-core": 75.0},
    )

    device_traces = [
        trace
        for trace in figure.data
        if trace.customdata is not None and trace.customdata[0][0] == "device"
    ]
    link_traces = [
        trace
        for trace in figure.data
        if trace.customdata is not None and trace.customdata[0][0] == "link"
    ]
    assert device_traces
    assert link_traces
    assert "Type:" in device_traces[0].hovertemplate
    assert "Site:" in device_traces[0].hovertemplate
    assert "Tier:" in device_traces[0].hovertemplate
    assert "Max link utilization:" in device_traces[0].hovertemplate
    assert "Capacity:" in link_traces[0].hovertemplate
    assert "Routing cost:" in link_traces[0].hovertemplate
    assert "Utilization:" in link_traces[0].hovertemplate

    assert topology_view.selection_from_event(
        {"selection": {"points": [{"customdata": ["device", "core"]}]}}
    ) == {"kind": "device", "id": "core"}


def _open_generated_topology() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    assert not at.exception
    open_page(at, "Topology Editor")
    assert not at.exception
    at.button(key="generate_topology").click().run()
    assert not at.exception
    return at


def test_device_selection_shows_inspector_and_can_be_cleared() -> None:
    at = _open_generated_topology()
    topology = at.session_state[state.TWIN_KEY].topology
    device_id = min(device.id for device in topology.devices)
    at.session_state[topology_view.CHART_KEY] = {
        "selection": {
            "points": [
                {
                    "curve_number": 0,
                    "point_number": 0,
                    "point_index": 0,
                    "customdata": ["device", device_id],
                }
            ],
            "point_indices": [],
            "box": [],
            "lasso": [],
        }
    }

    at.run()

    assert not at.exception
    assert any(f"Device: {device_id}" in item.value for item in at.markdown)
    assert at.button(key="topology_view_queue_device_failure")
    at.button(key="topology_view_clear_selection").click().run()
    assert not at.exception
    assert at.session_state.get(topology_view.SELECTION_KEY) is None


def test_link_quick_action_queues_a_failure_scenario() -> None:
    at = _open_generated_topology()
    topology = at.session_state[state.TWIN_KEY].topology
    link_id = min(link.id for link in topology.links)
    at.session_state[topology_view.CHART_KEY] = {
        "selection": {
            "points": [
                {
                    "curve_number": 0,
                    "point_number": 0,
                    "point_index": 0,
                    "customdata": ["link", link_id],
                }
            ],
            "point_indices": [],
            "box": [],
            "lasso": [],
        }
    }

    at.run()
    assert not at.exception
    assert any(f"Link: {link_id}" in item.value for item in at.markdown)

    at.button(key="topology_view_queue_link_failure").click().run()

    assert not at.exception
    assert at.session_state["simulation_scenario_type"] == "Single link failure"
    assert at.session_state["simulation_affected_links"] == [link_id]
