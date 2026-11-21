"""Focused tests for the E5 bounded derived-result session accessors."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import streamlit as st

from config.limits import MAX_OPTIMIZATION_RUNS, MAX_SCENARIOS
from optimization import (
    Algorithm,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    ParetoReranking,
    SensitivityReport,
    analyze_sensitivity,
    rerank_pareto_front,
    run_greedy,
    run_optimization,
)
from simulation import (
    FailureSweepResult,
    RoutingModeComparison,
    compare_routing_modes,
    run_failure_sweep,
)
from tests.unit.optimization.helpers import settings, tiny_twin
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)
from ui import state

_E5_KEYS = (
    state.SIMULATION_SWEEPS_KEY,
    state.SIMULATION_MODE_COMPARISONS_KEY,
    state.SIMULATION_SWEEP_CURSOR_KEY,
    state.OPTIMIZATION_SENSITIVITY_KEY,
    state.OPTIMIZATION_RERANKINGS_KEY,
    state.OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY,
)


@pytest.fixture(autouse=True)
def _clean_e5_state() -> Iterator[None]:
    for key in _E5_KEYS:
        state.session_delete(key)
    yield
    for key in _E5_KEYS:
        state.session_delete(key)


def _small_twin():
    topology = make_topology(
        ["a", "b", "c"],
        [make_link("ab", "a", "b"), make_link("bc", "b", "c")],
    )
    return make_twin(topology, (make_demand("a-to-c", "a", "c", 10.0),))


@pytest.fixture(scope="module")
def sweep_base() -> FailureSweepResult:
    return run_failure_sweep(_small_twin(), limit=2)


@pytest.fixture(scope="module")
def comparison_base() -> RoutingModeComparison:
    return compare_routing_modes(_small_twin())


@pytest.fixture(scope="module")
def sensitivity_base() -> SensitivityReport:
    topology = make_topology(
        ["a", "c"], [make_link("ac", "a", "c", capacity_mbps=20.0)]
    )
    twin = make_twin(topology, (make_demand("a-to-c", "a", "c", 8.0),))
    config = settings(
        pool=(),
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=1.0,
                lower_bound=0.0,
                upper_bound=100.0,
            ),
        ),
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            max_utilization_percent=100.0,
        ),
        max_iterations=5,
        max_evaluations=80,
    )
    return analyze_sensitivity(twin, run_greedy(twin, config))


@pytest.fixture(scope="module")
def reranking_base() -> ParetoReranking:
    objectives = (
        ObjectiveSpec(
            kind=ObjectiveKind.infrastructure_cost,
            weight=0.5,
            lower_bound=0.0,
            upper_bound=500.0,
        ),
        ObjectiveSpec(
            kind=ObjectiveKind.max_utilization,
            weight=0.5,
            lower_bound=0.0,
            upper_bound=200.0,
        ),
    )
    config = settings(objectives=objectives, max_iterations=8, max_evaluations=250)
    run = run_optimization(tiny_twin(capacity_mbps=40.0), config, Algorithm.nsga2)
    return rerank_pareto_front(run)


def _assert_bounded_accessors(
    *,
    key: str,
    cap: int,
    items: tuple[Any, ...],
    add: Callable[[Any], Any],
    peek: Callable[[], tuple[Any, ...]],
    get: Callable[[], tuple[Any, ...]],
    clear: Callable[[], None],
) -> None:
    clear()
    assert key not in st.session_state
    assert peek() == ()
    assert key not in st.session_state
    assert get() == ()
    assert st.session_state[key] == ()

    for item in items[:3]:
        assert add(item) is item
    assert peek() == items[:3]

    st.session_state[key] = ("bad", items[1], items[0])
    assert peek() == (items[1], items[0])
    assert get() == (items[1], items[0])
    assert isinstance(st.session_state[key], tuple)

    with pytest.raises(TypeError):
        add("bad")
    assert peek() == (items[1], items[0])

    for item in items:
        assert add(item) is item
    stored = peek()
    assert stored == items[-cap:]
    assert len(stored) == cap

    clear()
    assert key not in st.session_state
    assert peek() == ()


def test_e5_caps_match_shared_limits() -> None:
    assert state.SIMULATION_SWEEP_ENTRIES == MAX_SCENARIOS
    assert state.SIMULATION_MODE_COMPARISON_ENTRIES == 4
    assert state.OPTIMIZATION_SENSITIVITY_ENTRIES == MAX_OPTIMIZATION_RUNS
    assert state.OPTIMIZATION_RERANKING_ENTRIES == MAX_OPTIMIZATION_RUNS


def test_failure_sweep_accessors_are_typed_bounded_and_ordered(
    sweep_base: FailureSweepResult,
) -> None:
    cap = state.SIMULATION_SWEEP_ENTRIES
    items = tuple(
        sweep_base.model_copy(update={"start": index}) for index in range(cap + 3)
    )
    _assert_bounded_accessors(
        key=state.SIMULATION_SWEEPS_KEY,
        cap=cap,
        items=items,
        add=state.add_simulation_sweep,
        peek=state.peek_simulation_sweeps,
        get=state.get_simulation_sweeps,
        clear=state.clear_simulation_sweeps,
    )


def test_mode_comparison_accessors_are_typed_bounded_and_ordered(
    comparison_base: RoutingModeComparison,
) -> None:
    cap = state.SIMULATION_MODE_COMPARISON_ENTRIES
    items = tuple(
        comparison_base.model_copy(update={"scenario_id": f"scenario-{index}"})
        for index in range(cap + 3)
    )
    _assert_bounded_accessors(
        key=state.SIMULATION_MODE_COMPARISONS_KEY,
        cap=cap,
        items=items,
        add=state.add_mode_comparison,
        peek=state.peek_mode_comparisons,
        get=state.get_mode_comparisons,
        clear=state.clear_mode_comparisons,
    )


def test_sensitivity_accessors_are_typed_bounded_and_ordered(
    sensitivity_base: SensitivityReport,
) -> None:
    cap = state.OPTIMIZATION_SENSITIVITY_ENTRIES
    items = tuple(
        sensitivity_base.model_copy(update={"subset_note": f"subset-{index}"})
        for index in range(cap + 3)
    )
    _assert_bounded_accessors(
        key=state.OPTIMIZATION_SENSITIVITY_KEY,
        cap=cap,
        items=items,
        add=state.add_sensitivity_report,
        peek=state.peek_sensitivity_reports,
        get=state.get_sensitivity_reports,
        clear=state.clear_sensitivity_reports,
    )


def test_reranking_accessors_are_typed_bounded_and_ordered(
    reranking_base: ParetoReranking,
) -> None:
    cap = state.OPTIMIZATION_RERANKING_ENTRIES
    items = tuple(
        reranking_base.model_copy(update={"weight_note": f"weights-{index}"})
        for index in range(cap + 3)
    )
    _assert_bounded_accessors(
        key=state.OPTIMIZATION_RERANKINGS_KEY,
        cap=cap,
        items=items,
        add=state.add_reranking,
        peek=state.peek_rerankings,
        get=state.get_rerankings,
        clear=state.clear_rerankings,
    )


def test_sweep_cursor_is_typed_bounded_and_non_negative() -> None:
    key = state.SIMULATION_SWEEP_CURSOR_KEY
    assert key not in st.session_state
    assert state.get_sweep_cursor("missing") == 0
    assert key not in st.session_state

    assert state.set_sweep_cursor("sweep-1", 3) == 3
    assert state.get_sweep_cursor("sweep-1") == 3
    assert state.set_sweep_cursor("sweep-1", 5) == 5
    assert st.session_state[key] == {"sweep-1": 5}

    with pytest.raises(ValueError):
        state.set_sweep_cursor("negative", -1)
    with pytest.raises(TypeError):
        state.set_sweep_cursor("wrong-type", "1")  # type: ignore[arg-type]
    assert state.get_sweep_cursor("missing", 7) == 7

    state.session_set(key, {"bad": -1, 5: 2, "good": 4})
    assert state.get_sweep_cursor("bad") == 0
    assert state.get_sweep_cursor("good") == 4
    state.set_sweep_cursor("another", 1)
    mapping = st.session_state[key]
    assert all(
        isinstance(name, str)
        and isinstance(position, int)
        and not isinstance(position, bool)
        and position >= 0
        for name, position in mapping.items()
    )

    for index in range(state.SIMULATION_SWEEP_ENTRIES + 2):
        state.set_sweep_cursor(f"k-{index}", index)
    mapping = st.session_state[key]
    assert len(mapping) == state.SIMULATION_SWEEP_ENTRIES
    assert "k-0" not in mapping
    assert mapping[f"k-{state.SIMULATION_SWEEP_ENTRIES + 1}"] == (
        state.SIMULATION_SWEEP_ENTRIES + 1
    )

    state.clear_sweep_cursor()
    assert key not in st.session_state


def test_rerank_source_fingerprints_are_content_keyed_typed_and_bounded(
    reranking_base: ParetoReranking,
) -> None:
    key = state.OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY
    first = reranking_base.model_copy(update={"weight_note": "first"})
    duplicate = reranking_base.model_copy(update={"weight_note": "first"})

    assert key not in st.session_state
    assert state.peek_rerank_source_fingerprint(first) == ""
    assert key not in st.session_state
    assert state.set_rerank_source_fingerprint(first, "fp-first") == "fp-first"
    expected = hashlib.sha256(first.model_dump_json().encode("utf-8")).hexdigest()
    assert expected in st.session_state[key]
    assert state.get_rerank_source_fingerprint(duplicate) == "fp-first"
    assert state.peek_rerank_source_fingerprint(duplicate) == "fp-first"

    with pytest.raises(TypeError):
        state.set_rerank_source_fingerprint("bad", "fp")  # type: ignore[arg-type]
    assert len(st.session_state[key]) == 1

    state.session_set(key, {"not-a-hash": 7})
    assert state.get_rerank_source_fingerprint(first) == ""
    state.set_rerank_source_fingerprint(first, "fp-first")

    for index in range(state.OPTIMIZATION_RERANKING_ENTRIES + 2):
        item = reranking_base.model_copy(update={"weight_note": f"variant-{index}"})
        state.set_rerank_source_fingerprint(item, f"fp-{index}")
    mapping = st.session_state[key]
    assert len(mapping) == state.OPTIMIZATION_RERANKING_ENTRIES
    assert all(
        isinstance(name, str)
        and len(name) == 64
        and isinstance(value, str)
        for name, value in mapping.items()
    )
    assert "fp-0" not in mapping.values()
    assert "fp-first" not in mapping.values()

    state.add_reranking(first)
    state.clear_rerankings()
    assert key not in st.session_state
    assert state.OPTIMIZATION_RERANKINGS_KEY not in st.session_state
