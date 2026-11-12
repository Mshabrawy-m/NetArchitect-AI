"""AppTest smoke test for the Topology Editor page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.schemas.network import Topology
from network.topology.connectivity import analyze_connectivity

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def test_topology_editor_loads_and_generates_star() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("Topology Editor").run()
    assert not at.exception

    at.button(key="generate_topology").click().run()
    assert not at.exception

    topology = at.session_state["topology"]
    assert isinstance(topology, Topology)
    assert topology.name == "Star topology"
    assert len(topology.devices) == 7
    assert len(topology.links) == 6
    assert analyze_connectivity(topology).is_connected is True
    assert at.get("plotly_chart")
