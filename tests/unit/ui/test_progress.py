"""Progress-strip states derived only from real session data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.schemas.scenario import ScenarioType
from core.schemas.validation import ValidationReport
from optimization import Algorithm, OptimizationHistory, run_optimization
from simulation import ScenarioHistory, run_scenario, twin_fingerprint
from tests.unit.digital_twin.helpers import make_twin as design_twin
from tests.unit.optimization.helpers import settings, tiny_twin
from tests.unit.simulation.helpers import make_scenario
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.progress import DONE, INCOMPLETE, STALE

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"

PROGRESS_SOURCE = """
import streamlit as st

from ui import state
from ui.progress import build_progress

source_fp = st.session_state.get("__source_fp", "")
check = state.peek_addressing_check()
optimizations = state.peek_optimization_runs()
if check is not None and source_fp and not state.peek_addressing_check_fingerprint(check):
    state.set_addressing_check_source_fingerprint(check, source_fp)
if optimizations and source_fp and not state.get_optimization_source_fingerprint(optimizations[-1]):
    state.set_optimization_source_fingerprint(optimizations[-1], source_fp)
if source_fp:
    state.session_set(
        state.REPORT_TIME_KEY,
        {source_fp: __import__("datetime").datetime.now(__import__("datetime").timezone.utc)},
    )
steps = build_progress()
state.session_set("__progress_steps", [(step.key, step.status, step.detail) for step in steps])
"""


def _progress_statuses(at: AppTest) -> dict[str, str]:
    return {
        key: status
        for key, status, _ in at.session_state["__progress_steps"]
    }


def _add_results(at: AppTest, source_twin: object, source_fp: str) -> None:
    at.session_state["__source_fp"] = source_fp
    at.session_state[state.SIMULATION_HISTORY_KEY] = ScenarioHistory()
    at.session_state[state.SIMULATION_HISTORY_KEY].add(
        run_scenario(
            source_twin,  # type: ignore[arg-type]
            make_scenario(ScenarioType.single_link_failure, affected_links=["l2"]),
        )
    )
    # The optimizer test pool uses a-b-c-d endpoints, so build the run on the
    # matching fixture twin. The source fingerprint above still models which
    # twin revision the result is claimed to have come from.
    run = run_optimization(
        tiny_twin(),
        settings(max_iterations=2, max_runtime_seconds=5.0),
        Algorithm.greedy,
    )
    at.session_state[state.OPTIMIZATION_HISTORY_KEY] = OptimizationHistory()
    at.session_state[state.OPTIMIZATION_HISTORY_KEY].add(run)
    at.session_state[state.CHECK_KEY] = ValidationReport(
        is_valid=True,
        summary="No overlaps detected.",
        findings=[],
    )


def test_progress_is_incomplete_without_creating_session_state() -> None:
    at = AppTest.from_string(PROGRESS_SOURCE).run()

    assert not at.exception
    assert set(_progress_statuses(at).values()) == {INCOMPLETE}
    for key in (
        state.TWIN_KEY,
        state.SNAPSHOTS_KEY,
        state.SIMULATION_HISTORY_KEY,
        state.OPTIMIZATION_HISTORY_KEY,
        state.REPORT_TIME_KEY,
        state.CHECK_KEY,
        state.CHECK_FINGERPRINT_KEY,
    ):
        assert key not in at.session_state


def test_progress_is_done_when_results_match_current_twin() -> None:
    twin = design_twin()
    at = AppTest.from_string(PROGRESS_SOURCE)
    at.session_state[state.TWIN_KEY] = twin
    _add_results(at, twin, twin_fingerprint(twin))
    at.run()

    assert not at.exception
    assert set(_progress_statuses(at).values()) == {DONE}


def test_progress_is_stale_when_source_fingerprints_differ() -> None:
    twin = design_twin()
    old_twin = design_twin(metadata=twin.metadata.model_copy(update={"name": "Old design"}))
    assert twin_fingerprint(twin) != twin_fingerprint(old_twin)

    at = AppTest.from_string(PROGRESS_SOURCE)
    at.session_state[state.TWIN_KEY] = twin
    _add_results(at, old_twin, twin_fingerprint(old_twin))
    at.run()

    assert not at.exception
    statuses = _progress_statuses(at)
    assert statuses["design"] == DONE
    assert statuses["addressing"] == DONE
    assert statuses["validate"] == STALE
    assert statuses["simulate"] == STALE
    assert statuses["optimize"] == STALE
    assert statuses["report"] == STALE


def test_progress_report_is_stale_for_a_different_twin() -> None:
    twin = design_twin()
    at = AppTest.from_string("""
from ui import state
from ui.progress import build_progress
steps = build_progress()
state.session_set("__progress_steps", [(s.key, s.status, s.detail) for s in steps])
""")
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.REPORT_TIME_KEY] = {
        "another-twin-revision": datetime.now(UTC),
    }
    at.run()

    assert not at.exception
    assert _progress_statuses(at)["report"] == STALE


@pytest.mark.parametrize("page", ["Dashboard", "Topology Editor", "Settings"])
def test_progress_strip_links_each_step_on_main_pages(page: str) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    open_page(at, page)

    assert not at.exception
    labels = [link.value for link in at.page_link]
    assert labels == [
        "1. Design",
        "2. Addressing",
        "3. Validate",
        "4. Simulate",
        "5. Optimize",
        "6. Report",
    ]


def test_build_progress_returns_six_ordered_steps() -> None:
    source = """
from ui.progress import build_progress
from ui import state
state.session_set("__progress_keys", [s.key for s in build_progress()])
"""
    at = AppTest.from_string(source).run()
    assert not at.exception
    assert at.session_state["__progress_keys"] == [
        "design",
        "addressing",
        "validate",
        "simulate",
        "optimize",
        "report",
    ]
