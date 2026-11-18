"""AppTest coverage for the read-only Capacity Planning page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.schemas.scenario import ScenarioType
from simulation import ScenarioHistory, run_scenario
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.simulation.helpers import make_scenario
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _capacity_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at.selectbox(key="page_nav").select("Capacity Planning").run()
    return at


def test_capacity_planning_requires_a_twin() -> None:
    at = _capacity_page()

    assert not at.exception
    assert at.title[0].value == "Capacity Planning"
    assert any("No digital twin" in info.value for info in at.info)
    assert not at.metric


def test_capacity_planning_inventory_uses_existing_data_only() -> None:
    twin = make_twin()
    scenario_run = run_scenario(
        twin,
        make_scenario(ScenarioType.single_link_failure, affected_links=["l2"]),
    )
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.SIMULATION_HISTORY_KEY] = ScenarioHistory()
    at.session_state[state.SIMULATION_HISTORY_KEY].add(scenario_run)
    at.run()
    at.selectbox(key="page_nav").select("Capacity Planning").run()

    assert not at.exception
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Links"] == "2"
    assert metrics["Configured capacity"] == "1,100.0 Mbps"
    assert metrics["Demands"] == "1"
    assert metrics["Stated demand"] == "50.0 Mbps"
    assert at.download_button(key="capacity_links_download")
    assert at.download_button(key="capacity_demands_download")
    assert at.download_button(key="capacity_load_download")
    assert any("Source: scenario" in caption.value for caption in at.caption)
