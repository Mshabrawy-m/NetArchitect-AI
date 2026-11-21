"""Bounded demand/capacity sensitivity with the documented robust definition."""

from __future__ import annotations

import pytest

from config.limits import (
    MAX_SENSITIVITY_CANDIDATES,
    MAX_SENSITIVITY_SCENARIOS,
)
from core.exceptions import LimitsExceededError
from optimization import (
    ROBUST_DEFINITION,
    ROBUST_SCORE_TOLERANCE,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    SensitivityScenario,
    analyze_sensitivity,
    run_greedy,
    sensitivity_to_csv,
    sensitivity_to_json,
)
from tests.unit.optimization.helpers import settings
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def _linear_twin():
    topology = make_topology(
        ["a", "c"],
        [
            make_link("ac", "a", "c", capacity_mbps=20.0),
        ],
    )
    return make_twin(topology, (make_demand("a-to-c", "a", "c", 8.0),))


def _utilization_config():
    return settings(
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


def test_robust_candidate_keeps_score_within_tolerance_of_perturbed_baseline() -> None:
    twin = _linear_twin()
    run = run_greedy(twin, _utilization_config())
    assert run.best is not None

    report = analyze_sensitivity(twin, run)

    assert report.stop_reason.value == "completed"
    assert report.score_tolerance == ROBUST_SCORE_TOLERANCE
    assert report.robust_definition == ROBUST_DEFINITION
    assert run.best.evaluation.candidate_hash in report.robust_candidate_hashes
    assert report.recommended_candidate_hash == run.best.evaluation.candidate_hash
    assert len(report.scenarios) == 4
    for result in report.scenarios:
        case = next(
            item
            for item in result.cases
            if item.candidate_hash == run.best.evaluation.candidate_hash
        )
        assert case.feasible
        assert case.weighted_score <= result.baseline.weighted_score + 0.05 + 1e-12


def test_source_run_is_not_mutated_and_exports_are_deterministic() -> None:
    twin = _linear_twin()
    run = run_greedy(twin, _utilization_config())
    before = run.model_dump_json()

    first = analyze_sensitivity(twin, run)
    second = analyze_sensitivity(twin, run)

    assert run.model_dump_json() == before
    assert first == second
    assert sensitivity_to_json(first) == sensitivity_to_json(second)
    assert sensitivity_to_csv(first) == sensitivity_to_csv(second)
    assert sensitivity_to_csv(first).startswith("row_kind,scenario_id,")
    assert first.source_algorithm == run.algorithm
    assert first.source_baseline_hash == run.baseline.candidate_hash
    assert first.source_twin_fingerprint
    assert first.evaluations == sum(
        1 + len(result.cases) for result in first.scenarios
    )


def test_perturbations_change_twin_fingerprints() -> None:
    twin = _linear_twin()
    run = run_greedy(twin, _utilization_config())

    report = analyze_sensitivity(twin, run)

    fingerprints = {result.twin_fingerprint for result in report.scenarios}
    assert len(fingerprints) == 4
    assert report.source_twin_fingerprint not in fingerprints


def test_worse_weighted_score_is_not_robust_and_no_infeasible_recommendation() -> None:
    twin = _linear_twin()
    config = settings(
        pool=(make_link("ac-backup", "a", "c", cost=2.0),),
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.infrastructure_cost,
                weight=1.0,
                lower_bound=0.0,
                upper_bound=50.0,
            ),
        ),
        max_iterations=4,
        max_evaluations=80,
    )
    run = run_greedy(twin, config)

    report = analyze_sensitivity(twin, run, max_candidates=3)

    assert report.robust_candidate_hashes == ()
    assert report.recommended_candidate_hash is None
    assert report.evaluated_candidates <= 3


def test_runtime_limit_marks_no_candidate_robust() -> None:
    twin = _linear_twin()
    run = run_greedy(twin, _utilization_config())

    report = analyze_sensitivity(twin, run, deadline=0.0)

    assert report.stop_reason.value == "runtime_limit"
    assert report.scenarios == ()
    assert report.robust_candidate_hashes == ()
    assert report.recommended_candidate_hash is None


def test_sensitivity_bounds_are_enforced() -> None:
    twin = _linear_twin()
    run = run_greedy(twin, _utilization_config())
    too_many = tuple(
        SensitivityScenario(id=f"case-{index}", label=f"Case {index}")
        for index in range(MAX_SENSITIVITY_SCENARIOS + 1)
    )

    with pytest.raises(LimitsExceededError, match="scenarios"):
        analyze_sensitivity(twin, run, scenarios=too_many)
    with pytest.raises(LimitsExceededError, match="candidates"):
        analyze_sensitivity(twin, run, max_candidates=MAX_SENSITIVITY_CANDIDATES + 1)


def test_duplicate_scenario_ids_are_rejected() -> None:
    twin = _linear_twin()
    run = run_greedy(twin, _utilization_config())
    scenario = SensitivityScenario(id="same", label="Same")

    with pytest.raises(ValueError, match="unique"):
        analyze_sensitivity(twin, run, scenarios=(scenario, scenario))
