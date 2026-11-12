"""AppTest smoke tests for the Phase 5 routing and analytics pages."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from network.topology import generate_ring, generate_spine_leaf
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def test_routing_page_requires_a_topology() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("Routing Analysis").run()

    assert not at.exception
    assert any("No topology is loaded" in info.value for info in at.info)


def test_routing_page_renders_paths_tables_and_failures() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state["topology"] = generate_ring(node_count=4)
    at.selectbox(key="page_nav").select("Routing Analysis").run()
    assert not at.exception
    assert state.TWIN_KEY in at.session_state

    at.selectbox(key="routing_destination").select("ring-node-02").run()
    assert not at.exception
    assert at.get("plotly_chart")
    assert at.get("dataframe")
    assert at.get("download_button")

    at.multiselect(key="routing_failed_links").set_value(["ring-link-00"]).run()

    assert not at.exception
    # The two-hop path through ring-node-03 remains reachable.
    assert at.get("plotly_chart")


def test_analytics_page_requires_a_topology() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("Network Analytics").run()

    assert not at.exception
    assert any("No topology is loaded" in info.value for info in at.info)


def test_analytics_page_renders_metrics_and_findings() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state["topology"] = generate_spine_leaf(spines=2, leaves=3)
    at.selectbox(key="page_nav").select("Network Analytics").run()

    assert not at.exception
    assert at.get("dataframe")
    assert at.get("download_button")
