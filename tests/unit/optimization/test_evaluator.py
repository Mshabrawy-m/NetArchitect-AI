"""Evaluator cache, counting, and reproducibility tests."""

from __future__ import annotations

import pytest

from optimization import (
    EvaluationCache,
    ObjectiveKind,
    ObjectiveSpec,
    evaluate_candidate,
)
from simulation import twin_fingerprint
from tests.unit.optimization.helpers import connect_cd, settings, tiny_twin


def test_cache_reuses_identical_candidates() -> None:
    cache = EvaluationCache()
    config = settings()
    first = evaluate_candidate(tiny_twin(), connect_cd(), config, cache=cache)
    second = evaluate_candidate(tiny_twin(), connect_cd(), config, cache=cache)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.model_copy(update={"cache_hit": False}) == first
    assert cache.misses == 1
    assert cache.hits == 1
    assert cache.unique_candidates == 1


def test_evaluate_candidate_does_not_mutate_the_baseline() -> None:
    baseline = tiny_twin()
    before = twin_fingerprint(baseline)
    evaluate_candidate(baseline, connect_cd(), settings())
    assert twin_fingerprint(baseline) == before
    assert len(baseline.topology.links) == 2


def test_evaluation_is_deterministic_for_identical_inputs() -> None:
    config = settings()
    first = evaluate_candidate(tiny_twin(), connect_cd(), config)
    second = evaluate_candidate(tiny_twin(), connect_cd(), config)
    assert first.model_dump() == second.model_dump()


def test_evaluation_records_all_selected_objectives() -> None:
    config = settings(
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
        )
    )
    evaluation = evaluate_candidate(tiny_twin(), connect_cd(), config)
    kinds = [value.kind for value in evaluation.objectives]
    assert kinds == [
        ObjectiveKind.infrastructure_cost,
        ObjectiveKind.max_utilization,
    ]
    assert evaluation.weighted_score == pytest.approx(
        sum(value.contribution for value in evaluation.objectives)
    )


def test_metrics_include_reliability_only_when_needed() -> None:
    plain = evaluate_candidate(tiny_twin(), connect_cd(), settings())
    assert plain.metrics.spof_count is None
    assert plain.metrics.min_edge_disjoint_paths is None

    config = settings(
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.spof_count,
                weight=0.5,
                lower_bound=0,
                upper_bound=10,
            ),
            ObjectiveSpec(
                kind=ObjectiveKind.min_edge_disjoint_paths,
                weight=0.5,
                lower_bound=0,
                upper_bound=4,
            ),
        )
    )
    evaluation = evaluate_candidate(tiny_twin(), connect_cd(), config)
    assert evaluation.metrics.spof_count is not None
    assert evaluation.metrics.min_edge_disjoint_paths is not None
