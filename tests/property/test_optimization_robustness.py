"""Bounded invariants for derived optimization results."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from optimization import (
    Algorithm,
    ObjectiveKind,
    ObjectiveSpec,
    rerank_pareto_front,
    reranking_to_json,
    run_optimization,
)
from tests.property.config import BOUNDED
from tests.unit.optimization.helpers import settings, tiny_twin


def _run():
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
        max_iterations=6,
        max_evaluations=150,
    )
    return run_optimization(tiny_twin(capacity_mbps=40.0), config, Algorithm.nsga2)


_RUN = _run()


@BOUNDED
@given(
    cost_weight=st.floats(
        min_value=0.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_rerank_is_deterministic_and_feasibility_safe(cost_weight: float) -> None:
    weights = {
        ObjectiveKind.infrastructure_cost: cost_weight,
        ObjectiveKind.max_utilization: 1.0 - cost_weight,
    }

    first = rerank_pareto_front(_RUN, weights)
    second = rerank_pareto_front(_RUN, weights)

    assert reranking_to_json(first) == reranking_to_json(second)
    assert [item.rank for item in first.items] == list(
        range(1, len(first.items) + 1)
    )
    assert all(item.evaluation.feasible for item in first.items)
    if first.recommended_candidate_hash is not None:
        assert first.recommended_candidate_hash in {
            item.candidate_hash for item in first.items
        }
