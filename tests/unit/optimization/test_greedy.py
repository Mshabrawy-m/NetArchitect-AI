"""Greedy baseline optimizer tests: feasibility, limits, and immutability."""

from __future__ import annotations

import pytest

from optimization import (
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    StopReason,
    run_greedy,
)
from simulation import twin_fingerprint
from tests.unit.optimization.helpers import connect_cd, settings, tiny_twin
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def test_greedy_returns_a_feasible_recommendation() -> None:
    run = run_greedy(tiny_twin(), settings(max_iterations=10))
    assert run.best is not None
    assert run.best.evaluation.feasible
    assert run.best.evaluation.metrics.served_demand_ratio == 1.0
    assert len(run.best.evaluation.candidate.selected_link_ids) == 1


def test_greedy_never_recommends_an_infeasible_candidate() -> None:
    run = run_greedy(
        tiny_twin(),
        settings(
            pool=(),
            constraints=HardConstraints(
                require_connectivity=True,
                min_served_demand_ratio=1.0,
            ),
            max_iterations=5,
        ),
    )
    assert run.best is None
    assert run.candidates
    assert all(not record.evaluation.feasible for record in run.candidates)


def test_greedy_stops_at_max_evaluations() -> None:
    run = run_greedy(tiny_twin(), settings(max_evaluations=1))
    assert run.stop_reason is StopReason.max_evaluations
    assert run.evaluations == 1


def test_greedy_stops_at_max_iterations_after_an_improvement() -> None:
    run = run_greedy(tiny_twin(), settings(max_iterations=1, max_evaluations=200))
    assert run.stop_reason is StopReason.max_iterations


def test_greedy_stops_at_runtime_limit() -> None:
    run = run_greedy(
        tiny_twin(),
        settings(max_runtime_seconds=1e-9, max_iterations=20),
    )
    assert run.stop_reason is StopReason.runtime_limit
    assert run.baseline is not None


def test_greedy_stops_when_no_neighbour_improves() -> None:
    topology = make_topology(
        ["a", "b", "c"],
        [make_link("ab", "a", "b"), make_link("bc", "b", "c")],
    )
    twin = make_twin(topology, (make_demand("a-to-c", "a", "c", 10.0),))
    run = run_greedy(twin, settings(pool=(), max_iterations=5))
    assert run.stop_reason is StopReason.no_improvement
    assert run.best is not None
    assert run.best.evaluation.candidate.selected_link_ids == ()


def test_greedy_upgrades_a_congested_baseline_link() -> None:
    topology = make_topology(
        ["a", "b"],
        [make_link("ab", "a", "b", capacity_mbps=100.0)],
    )
    twin = make_twin(topology, (make_demand("a-to-b", "a", "b", 150.0),))
    config = settings(
        pool=(),
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=1.0,
                lower_bound=0,
                upper_bound=200,
            ),
        ),
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            max_utilization_percent=100.0,
        ),
        max_iterations=5,
    )
    run = run_greedy(twin, config)
    assert run.best is not None
    assert run.best.evaluation.metrics.max_utilization_percent == 15.0


def test_greedy_is_reproducible_for_identical_settings() -> None:
    config = settings()
    first = run_greedy(tiny_twin(), config)
    second = run_greedy(tiny_twin(), config)
    assert first.model_dump() == second.model_dump()


def test_greedy_does_not_mutate_the_baseline() -> None:
    baseline = tiny_twin()
    before = twin_fingerprint(baseline)
    run_greedy(baseline, settings())
    assert twin_fingerprint(baseline) == before


def test_greedy_counts_match_unique_candidates() -> None:
    run = run_greedy(tiny_twin(), settings())
    assert run.evaluations == len(run.candidates)
    assert run.evaluations > 0
    assert run.cache_hits >= 0


def test_greedy_recommendation_is_the_best_feasible_record() -> None:
    run = run_greedy(tiny_twin(), settings())
    feasible = [
        record.evaluation
        for record in run.candidates
        if record.evaluation.feasible
    ]
    assert run.best is not None
    assert run.best.evaluation.weighted_score == pytest.approx(
        min(item.weighted_score for item in feasible)
    )
    assert connect_cd().selected_link_ids in {
        record.evaluation.candidate.selected_link_ids for record in run.candidates
    }
