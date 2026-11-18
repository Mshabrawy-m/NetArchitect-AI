"""AppTest coverage for the twin-backed Dashboard."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.schemas.scenario import ScenarioType
from digital_twin import SnapshotStore, create_snapshot
from optimization import Algorithm, OptimizationHistory, run_optimization
from simulation import ScenarioHistory, run_scenario
from tests.unit.digital_twin.helpers import make_twin as design_twin
from tests.unit.optimization.helpers import settings, tiny_twin
from tests.unit.simulation.helpers import make_scenario
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _run_dashboard() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at.selectbox(key="page_nav").select("Dashboard").run()
    return at


def test_dashboard_empty_state_uses_no_placeholder_data() -> None:
    at = _run_dashboard()

    assert not at.exception
    assert at.title[0].value == "Dashboard"
    assert any("No digital twin is loaded" in info.value for info in at.info)
    assert not at.metric
    assert not any("Phase 11" in caption.value for caption in at.caption)


def test_dashboard_shows_twin_sessions_and_design_health() -> None:
    twin = tiny_twin()
    scenario_run = run_scenario(
        twin,
        make_scenario(ScenarioType.single_link_failure, affected_links=["ab"]),
    )
    settings_value = settings(max_iterations=2, max_runtime_seconds=5.0)
    optimization_run = run_optimization(twin, settings_value, Algorithm.greedy)

    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.SIMULATION_HISTORY_KEY] = ScenarioHistory()
    at.session_state[state.SIMULATION_HISTORY_KEY].add(scenario_run)
    at.session_state[state.OPTIMIZATION_HISTORY_KEY] = OptimizationHistory()
    at.session_state[state.OPTIMIZATION_HISTORY_KEY].add(optimization_run)
    store = SnapshotStore()
    store.add(create_snapshot(twin, "baseline"))
    at.session_state[state.SNAPSHOTS_KEY] = store
    at.run()
    at.selectbox(key="page_nav").select("Dashboard").run()

    assert not at.exception
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Devices"] == "4"
    assert metrics["Links"] == "2"
    assert metrics["Demands"] == "1"
    assert metrics["Snapshots"] == "1"
    assert metrics["Scenario runs"] == "1"
    assert metrics["Optimization runs"] == "1"
    assert metrics["Latest optimization evaluations"] == str(
        optimization_run.evaluations
    )
    assert "Design health" in [item.value for item in at.subheader]
    assert any("Twin:" in caption.value for caption in at.caption)
    assert not any("No scenario or optimization runs" in info.value for info in at.info)


def test_dashboard_counts_zero_when_no_runs_are_retained() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = design_twin()
    at.run()
    at.selectbox(key="page_nav").select("Dashboard").run()

    assert not at.exception
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Snapshots"] == "0"
    assert metrics["Scenario runs"] == "0"
    assert metrics["Optimization runs"] == "0"
    assert state.SNAPSHOTS_KEY not in at.session_state
    assert state.SIMULATION_HISTORY_KEY not in at.session_state
    assert state.OPTIMIZATION_HISTORY_KEY not in at.session_state
