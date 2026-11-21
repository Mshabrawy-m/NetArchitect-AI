"""Instant Pareto re-ranking without re-evaluating candidates."""

from __future__ import annotations

import pytest

from optimization import (
    Algorithm,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    ParetoReranking,
    RerankedCandidate,
    rerank_pareto_front,
    reranking_to_csv,
    reranking_to_json,
    run_greedy,
    run_optimization,
)
from tests.unit.optimization.helpers import settings, tiny_twin


def _trade_off_run():
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
    config = settings(
        objectives=objectives,
        max_iterations=8,
        max_evaluations=250,
    )
    return run_optimization(tiny_twin(capacity_mbps=40.0), config, Algorithm.nsga2)


def test_rerank_changes_order_without_re_evaluating_or_mutating_the_run() -> None:
    run = _trade_off_run()
    before = run.model_dump_json()

    cheap = rerank_pareto_front(
        run,
        {ObjectiveKind.infrastructure_cost: 1.0, ObjectiveKind.max_utilization: 0.0},
    )
    low_utilization = rerank_pareto_front(
        run,
        {ObjectiveKind.infrastructure_cost: 0.0, ObjectiveKind.max_utilization: 1.0},
    )

    assert run.model_dump_json() == before
    assert isinstance(cheap, ParetoReranking)
    assert all(isinstance(item, RerankedCandidate) for item in cheap.items)
    assert cheap.source_evaluations == run.evaluations
    assert cheap.source_baseline_hash == run.baseline.candidate_hash
    assert cheap.source_algorithm is run.algorithm
    assert cheap.source_seed == run.seed
    assert cheap.recommended_candidate_hash != low_utilization.recommended_candidate_hash
    assert cheap.items[0].candidate_hash == cheap.recommended_candidate_hash
    assert low_utilization.items[0].candidate_hash == (
        low_utilization.recommended_candidate_hash
    )


def test_recomputed_scores_match_weights_and_ranks() -> None:
    run = _trade_off_run()
    weights = {
        ObjectiveKind.infrastructure_cost: 0.25,
        ObjectiveKind.max_utilization: 0.75,
    }

    reranked = rerank_pareto_front(run, weights)

    assert [item.rank for item in reranked.items] == list(
        range(1, len(reranked.items) + 1)
    )
    for item in reranked.items:
        values = {value.kind: value for value in item.evaluation.objectives}
        assert values[ObjectiveKind.infrastructure_cost].weight == 0.25
        assert values[ObjectiveKind.max_utilization].weight == 0.75
        assert item.evaluation.weighted_score == pytest.approx(
            sum(value.contribution for value in item.evaluation.objectives)
        )
        assert item.evaluation.feasible


def test_default_weights_match_the_source_run_order() -> None:
    run = _trade_off_run()

    reranked = rerank_pareto_front(run)

    assert {item.candidate_hash for item in reranked.items} == {
        record.evaluation.candidate_hash
        for record in run.pareto_front
        if record.evaluation.feasible
    }
    assert reranked.recommended_candidate_hash == (
        run.best.evaluation.candidate_hash if run.best else None
    )


def test_rerank_never_recommends_an_infeasible_candidate() -> None:
    config = settings(
        pool=(),
        constraints=HardConstraints(min_served_demand_ratio=1.0),
        max_iterations=3,
        max_evaluations=60,
    )
    run = run_greedy(tiny_twin(), config)
    assert run.best is None

    reranked = rerank_pareto_front(run)

    assert reranked.items == ()
    assert reranked.recommended_candidate_hash is None


def test_invalid_weights_are_rejected() -> None:
    run = _trade_off_run()

    with pytest.raises(ValueError, match="sum to 1"):
        rerank_pareto_front(
            run,
            {
                ObjectiveKind.infrastructure_cost: 1.0,
                ObjectiveKind.max_utilization: 1.0,
            },
        )
    with pytest.raises(ValueError, match="exactly the source objectives"):
        rerank_pareto_front(run, {ObjectiveKind.infrastructure_cost: 1.0})
    with pytest.raises(ValueError, match="finite"):
        rerank_pareto_front(
            run,
            {
                ObjectiveKind.infrastructure_cost: float("nan"),
                ObjectiveKind.max_utilization: 1.0,
            },
        )


def test_rerank_exports_are_deterministic() -> None:
    run = _trade_off_run()
    reranked = rerank_pareto_front(run)

    assert reranking_to_json(reranked) == reranking_to_json(reranked)
    assert reranking_to_csv(reranked) == reranking_to_csv(reranked)
    assert reranking_to_csv(reranked).startswith(
        "rank,candidate_hash,weighted_score,"
    )


def test_source_run_with_empty_candidate_is_handled() -> None:
    run = _trade_off_run().model_copy(
        update={
            "candidates": (),
            "pareto_front": (),
            "best": None,
        }
    )

    reranked = rerank_pareto_front(run)

    assert reranked.items == ()
    assert reranked.recommended_candidate_hash is None
