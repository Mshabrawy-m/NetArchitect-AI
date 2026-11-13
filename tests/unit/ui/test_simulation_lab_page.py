"""AppTest smoke tests for the Phase 7c Simulation Lab page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from simulation import MODEL_NOTE
from tests.unit.simulation.helpers import diamond_twin, make_demand
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _twin_with_demand():
    return diamond_twin(demands=(make_demand("a-to-d", "a", "d"),))


def test_simulation_lab_requires_a_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("Simulation Lab").run()

    assert not at.exception
    assert any("No digital twin is loaded" in info.value for info in at.info)
    assert any("Topology Editor" in info.value for info in at.info)


def test_simulation_lab_rejects_invalid_scenario() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    at.selectbox(key="page_nav").select("Simulation Lab").run()

    at.button(key="simulation_validate_scenario").click().run()

    assert not at.exception
    assert any(
        "requires exactly one affected link" in error.value for error in at.error
    )
    assert not at.session_state[state.SIMULATION_HISTORY_KEY].runs


def test_simulation_lab_demand_editor_writes_to_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = diamond_twin()
    at.selectbox(key="page_nav").select("Simulation Lab").run()

    at.session_state["simulation_demand_editor"] = {
        "edited_rows": {},
        "added_rows": [
            {
                "name": "new-flow",
                "source": "a",
                "destination": "d",
                "bandwidth_mbps": 25.0,
                "priority": 1,
            }
        ],
        "deleted_rows": [],
    }
    at.button(key="simulation_apply_demands").click().run()

    assert not at.exception
    assert not at.error
    twin = at.session_state[state.TWIN_KEY]
    assert len(twin.demands) == 1
    assert twin.demands[0].name == "new-flow"
    assert twin.demands[0].bandwidth_mbps == 25.0


def test_simulation_lab_runs_and_compares_scenarios() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    at.selectbox(key="page_nav").select("Simulation Lab").run()

    assert any(MODEL_NOTE in info.value for info in at.info)
    assert at.button(key="simulation_apply_demands")
    assert at.button(key="simulation_run_scenario")

    # Form widgets are committed on submit; setting their session keys is the
    # AppTest equivalent of a user filling the form before clicking Run.
    at.session_state["simulation_scenario_type"] = "Multiple link failures"
    at.session_state["simulation_scenario_name"] = "Lose both branches"
    at.session_state["simulation_affected_links"] = ["ab", "bd", "ac", "cd"]
    at.button(key="simulation_run_scenario").click().run()

    assert not at.exception
    history = at.session_state[state.SIMULATION_HISTORY_KEY]
    assert len(history.runs) == 1
    run = history.runs[0]
    assert run.scenario.name == "Lose both branches"
    assert run.comparison.newly_unserved_demands == ("a-to-d",)
    assert any("Newly unserved" in warning.value for warning in at.warning)

    at.session_state["simulation_scenario_name"] = "Lose the other branch"
    at.session_state["simulation_affected_links"] = ["ac", "cd"]
    at.button(key="simulation_run_scenario").click().run()

    assert not at.exception
    history = at.session_state[state.SIMULATION_HISTORY_KEY]
    assert len(history.runs) == 2
    assert at.selectbox(key="simulation_compare_left")
    assert at.selectbox(key="simulation_compare_right")
    assert at.download_button(key="simulation_download_json")
    assert at.download_button(key="simulation_download_comparison")
