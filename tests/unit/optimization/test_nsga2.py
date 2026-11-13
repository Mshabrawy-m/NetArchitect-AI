"""Brute-force Pareto front versus NSGA-II on a tiny topology."""

from __future__ import annotations

from optimization import (
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationSettings,
    dominates_values,
    enumerate_candidates,
    evaluate_candidate,
    non_dominated_sort,
    run_nsga2,
)
from tests.unit.optimization.helpers import pool_links, settings, tiny_twin


def _brute_force_config() -> OptimizationSettings:
    """One pool link, two tiers, and two upgradeable baseline links.

    The discrete space has 3 * 2 * 2 = 12 candidates, so every candidate can be
    evaluated exactly once.
    """
    return settings(
        pool=(pool_links()[0],),
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.infrastructure_cost,
                weight=0.5,
                lower_bound=0,
                upper_bound=500,
            ),
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=0.5,
                lower_bound=0,
                upper_bound=200,
            ),
        ),
        constraints=HardConstraints(
            require_connectivity=False,
            min_served_demand_ratio=1.0,
        ),
        max_iterations=10,
        max_evaluations=500,
    )


def test_nsga2_front_matches_brute_force_on_a_tiny_space() -> None:
    baseline = tiny_twin()
    config = _brute_force_config()
    candidates = enumerate_candidates(baseline, config, limit=100)
    assert len(candidates) == 12

    evaluations = [
        evaluate_candidate(baseline, candidate, config)
        for candidate in candidates
    ]
    brute_layers = non_dominated_sort(evaluations)
    brute_front = {
        evaluation.candidate_hash
        for evaluation in brute_layers[0]
        if evaluation.feasible
    }
    assert brute_front

    run = run_nsga2(baseline, config)
    observed = {
        record.evaluation.candidate_hash for record in run.pareto_front
    }
    assert observed == brute_front
    assert all(record.evaluation.feasible for record in run.pareto_front)
    assert run.stop_reason.value in {
        "completed",
        "max_iterations",
        "max_evaluations",
        "runtime_limit",
    }


def test_nsga2_front_is_mutually_non_dominated() -> None:
    baseline = tiny_twin()
    config = _brute_force_config()
    run = run_nsga2(baseline, config)
    front = [record.evaluation for record in run.pareto_front]
    for left in front:
        for right in front:
            if left.candidate_hash == right.candidate_hash:
                continue
            left_values = [value.raw_value for value in left.objectives]
            right_values = [value.raw_value for value in right.objectives]
            directions = [value.direction for value in left.objectives]
            assert not dominates_values(left_values, right_values, directions)
