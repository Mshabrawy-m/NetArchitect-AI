"""AppTest smoke tests for the Phase 8c Optimization Center page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from optimization import (
    SEARCH_NOTE,
    Algorithm,
    OptimizationHistory,
    run_optimization,
)
from tests.unit.optimization.helpers import settings, tiny_twin
from tests.unit.simulation.helpers import diamond_twin, make_demand
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.pages.optimization_center import ALGORITHM_LABELS, SNAPSHOT_LABEL_KEY

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _twin_with_demand():
    return diamond_twin(demands=(make_demand("a-to-d", "a", "d"),))


def _retained_nsga2_run():
    """Build one small deterministic run with a populated Pareto front."""
    twin = tiny_twin()
    config = settings(
        max_iterations=3,
        max_evaluations=80,
        max_runtime_seconds=5.0,
    )
    return twin, run_optimization(twin, config, Algorithm.nsga2)


def test_optimization_center_requires_a_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    open_page(at, "Optimization Center")

    assert not at.exception
    assert any("No digital twin" in info.value for info in at.info)
    assert any(SEARCH_NOTE in info.value for info in at.info)


def test_optimization_center_requires_demands() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = diamond_twin()
    open_page(at, "Optimization Center")

    assert not at.exception
    assert any("no traffic demands" in info.value for info in at.info)


def test_optimization_center_runs_and_shows_results() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Optimization Center")

    assert not at.exception
    assert any(SEARCH_NOTE in info.value for info in at.info)
    assert at.button(key="optimization_run")

    at.button(key="optimization_run").click().run()

    assert not at.exception
    history = at.session_state[state.OPTIMIZATION_HISTORY_KEY]
    assert len(history.runs) == 1
    run = history.runs[0]
    assert run.seed == 42
    assert run.evaluations >= 1
    assert at.button(key="optimization_load_run")
    assert at.button(key="optimization_save_snapshot")
    assert at.download_button(key="optimization_download_json")
    assert at.download_button(key="optimization_download_csv")


def test_optimization_center_parses_a_candidate_pool() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Optimization Center")

    at.session_state["optimization_pool_editor"] = {
        "edited_rows": {},
        "added_rows": [
            {
                "id": "ad",
                "source": "a",
                "destination": "d",
                "capacity_mbps": 1_000.0,
                "cost": 1.0,
                "directed": False,
            }
        ],
        "deleted_rows": [],
    }
    at.session_state["optimization_iterations"] = 3
    at.button(key="optimization_run").click().run()

    assert not at.exception
    run = at.session_state[state.OPTIMIZATION_HISTORY_KEY].runs[0]
    assert [link.id for link in run.settings.candidate_pool] == ["ad"]
    assert run.settings.candidate_pool[0].capacity_mbps == 1_000.0
    assert run.settings.max_iterations == 3


def test_optimization_center_saves_an_explicit_snapshot() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Optimization Center")
    at.button(key="optimization_run").click().run()

    assert not at.exception
    at.session_state[SNAPSHOT_LABEL_KEY] = "optimized design"
    at.button(key="optimization_save_snapshot").click().run()

    assert not at.exception
    store = at.session_state[state.SNAPSHOTS_KEY]
    assert len(store.snapshots) == 1
    assert store.snapshots[0].label == "optimized design"


def test_optimization_center_excludes_infeasible_recommendations() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Optimization Center")

    # Requiring zero devices makes every candidate infeasible.
    at.session_state["optimization_max_nodes"] = 0
    at.button(key="optimization_run").click().run()

    assert not at.exception
    run = at.session_state[state.OPTIMIZATION_HISTORY_KEY].runs[0]
    assert run.best is None
    assert any(
        "No evaluated candidate satisfies" in warning.value
        for warning in at.warning
    )


def test_optimization_center_renders_e5_controls() -> None:
    twin, run = _retained_nsga2_run()
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.session_state[state.TWIN_KEY] = twin
    history = OptimizationHistory()
    history.add(run)
    at.session_state[state.OPTIMIZATION_HISTORY_KEY] = history
    open_page(at, "Optimization Center")

    assert not at.exception
    algorithm = at.selectbox(key="optimization_algorithm")
    assert any(
        ALGORITHM_LABELS[Algorithm.simulated_annealing] in option
        for option in algorithm.options
    )
    assert at.checkbox(key="optimization_sa_greedy_start")
    assert at.button(key="optimization_rerank_apply")
    assert at.button(key="optimization_sensitivity_run")
    assert at.slider(key="optimization_sensitivity_candidates")
    assert at.number_input(key="optimization_sensitivity_runtime")


def test_optimization_center_e5_downloads_after_applying_controls() -> None:
    twin, run = _retained_nsga2_run()
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.session_state[state.TWIN_KEY] = twin
    history = OptimizationHistory()
    history.add(run)
    at.session_state[state.OPTIMIZATION_HISTORY_KEY] = history
    open_page(at, "Optimization Center")

    at.button(key="optimization_rerank_apply").click().run()

    assert not at.exception
    assert at.download_button(key="optimization_download_rerank_json")
    assert at.download_button(key="optimization_download_rerank_csv")

    at.session_state["optimization_sensitivity_candidates"] = 1
    at.session_state["optimization_sensitivity_runtime"] = 5.0
    at.button(key="optimization_sensitivity_run").click().run()

    assert not at.exception
    assert at.download_button(key="optimization_download_sensitivity_json")
    assert at.download_button(key="optimization_download_sensitivity_csv")
