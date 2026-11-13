"""Comparison helper: deltas, trade-offs, weights, and comparability rules."""

from __future__ import annotations

import pytest

from optimization import (
    Algorithm,
    Candidate,
    HardConstraints,
    ObjectiveDelta,
    ObjectiveDirection,
    ObjectiveKind,
    ObjectiveSpec,
    compare_runs,
    evaluate_candidate,
    objective_deltas,
    run_genetic,
    run_greedy,
    run_nsga2,
    trade_off_messages,
)
from tests.unit.optimization.helpers import (
    connect_cd,
    settings,
    tiny_twin,
)
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def test_compare_reports_baseline_and_each_algorithm() -> None:
    config = settings(max_iterations=4, max_evaluations=300)
    runs = [
        run_greedy(tiny_twin(), config),
        run_genetic(tiny_twin(), config),
        run_nsga2(tiny_twin(), config),
    ]
    report = compare_runs(runs)
    assert report.baseline.candidate_hash == runs[0].baseline.candidate_hash
    assert [item.algorithm for item in report.comparisons] == [
        Algorithm.greedy,
        Algorithm.genetic,
        Algorithm.nsga2,
    ]
    assert all(item.best is not None for item in report.comparisons)
    for comparison, run in zip(report.comparisons, runs):
        assert comparison.stop_reason is run.stop_reason
        assert comparison.evaluations == run.evaluations
        assert len(comparison.deltas) == len(run.settings.objectives)
    assert report.weighted_best_algorithm in set(Algorithm)
    assert "link_count=1" in report.weight_note
    assert "not a global optimum" in report.weight_note
    assert any("evaluated candidates only" in note for note in report.notes)


def test_compare_rejects_different_settings() -> None:
    first = run_greedy(tiny_twin(), settings(max_iterations=2))
    second = run_greedy(tiny_twin(), settings(max_iterations=3))
    with pytest.raises(ValueError, match="settings"):
        compare_runs([first, second])


def test_compare_handles_runs_without_feasible_candidates() -> None:
    config = settings(
        pool=(),
        constraints=HardConstraints(
            require_connectivity=True,
            min_served_demand_ratio=1.0,
        ),
        max_iterations=2,
    )
    runs = [run_greedy(tiny_twin(), config), run_genetic(tiny_twin(), config)]
    report = compare_runs(runs)
    assert all(item.best is None for item in report.comparisons)
    assert all(item.deltas == () for item in report.comparisons)
    assert all(item.trade_offs == () for item in report.comparisons)
    assert report.weighted_best_algorithm is None


def test_objective_deltas_report_relative_and_direction() -> None:
    config = settings(
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.link_count,
                weight=1.0,
                lower_bound=0,
                upper_bound=10,
            ),
        )
    )
    baseline = run_greedy(tiny_twin(), config).baseline
    candidate = run_greedy(tiny_twin(), config).best
    assert candidate is not None
    deltas = objective_deltas(
        baseline,
        candidate.evaluation,
        weights={ObjectiveKind.link_count: 1.0},
    )
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.kind is ObjectiveKind.link_count
    assert delta.baseline_value == 2.0
    assert delta.candidate_value == pytest.approx(3.0)
    assert delta.absolute_change == pytest.approx(1.0)
    assert delta.relative_change == pytest.approx(0.5)
    assert delta.improved is False
    assert delta.weight == 1.0


def test_relative_change_is_none_when_baseline_is_zero() -> None:
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b"),
            make_link("bc", "b", "c"),
        ],
    )
    twin = make_twin(topology, (make_demand("a-to-d", "a", "d", 50.0),))
    config = settings(
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=1.0,
                lower_bound=0,
                upper_bound=200,
            ),
        ),
        constraints=HardConstraints(min_served_demand_ratio=0.0),
    )
    baseline = evaluate_candidate(
        twin,
        Candidate(),
        config,
    )
    candidate = evaluate_candidate(twin, connect_cd(), config)
    deltas = objective_deltas(baseline, candidate)
    assert deltas[0].baseline_value == 0.0
    assert deltas[0].relative_change is None
    assert deltas[0].improved is False


def test_trade_off_messages_name_worsened_objectives_only() -> None:
    worse = ObjectiveDelta(
        kind=ObjectiveKind.infrastructure_cost,
        label="Infrastructure cost proxy",
        unit="modeled cost units",
        direction=ObjectiveDirection.minimize,
        baseline_value=10.0,
        candidate_value=20.0,
        absolute_change=10.0,
        relative_change=1.0,
        improved=False,
        weight=0.75,
    )
    better = ObjectiveDelta(
        kind=ObjectiveKind.max_utilization,
        label="Maximum link utilization",
        unit="percent",
        direction=ObjectiveDirection.minimize,
        baseline_value=80.0,
        candidate_value=40.0,
        absolute_change=-40.0,
        relative_change=-0.5,
        improved=True,
        weight=0.25,
    )
    same = ObjectiveDelta(
        kind=ObjectiveKind.link_count,
        label="Link count",
        unit="links",
        direction=ObjectiveDirection.minimize,
        baseline_value=5.0,
        candidate_value=5.0,
        absolute_change=0.0,
        relative_change=0.0,
        improved=False,
        weight=0.0,
    )
    messages = trade_off_messages([worse, better, same])
    assert len(messages) == 1
    assert "Infrastructure cost proxy" in messages[0]
    assert "0.75" in messages[0]
