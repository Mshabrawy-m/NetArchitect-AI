"""Bounded hard-constraint invariants for candidate evaluation."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from optimization import Candidate, HardConstraints, evaluate_candidate
from tests.property.config import BOUNDED
from tests.unit.optimization.helpers import settings as optimization_settings
from tests.unit.optimization.helpers import tiny_twin

_POOL_IDS = ("cd", "ad", "bd")


@st.composite
def _candidates(draw):
    selected = draw(
        st.lists(st.sampled_from(_POOL_IDS), unique=True, max_size=len(_POOL_IDS))
    )
    return Candidate(
        selected_link_ids=tuple(sorted(selected)),
        tier_assignments=tuple((link_id, "small") for link_id in sorted(selected)),
    )


@BOUNDED
@given(candidate=_candidates())
def test_node_cap_always_marks_valid_candidate_infeasible(candidate) -> None:
    config = optimization_settings(
        constraints=HardConstraints(max_nodes=3),
        max_runtime_seconds=5.0,
    )
    evaluation = evaluate_candidate(tiny_twin(), candidate, config)

    assert evaluation.metrics.device_count == 4
    assert not evaluation.feasible
    assert "max_nodes" in evaluation.violated_constraints
    assert evaluation.feasible == (not evaluation.violated_constraints)


@BOUNDED
@given(
    candidate=_candidates(),
    budget=st.floats(
        min_value=0.0,
        max_value=100.0,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
)
def test_budget_cap_violation_matches_cost_proxy(candidate, budget) -> None:
    config = optimization_settings(
        constraints=HardConstraints(max_budget_proxy=budget),
        max_runtime_seconds=5.0,
    )
    evaluation = evaluate_candidate(tiny_twin(), candidate, config)
    exceeds = evaluation.metrics.infrastructure_cost_proxy > budget + 1e-9

    assert ("budget" in evaluation.violated_constraints) is exceeds
    if exceeds:
        assert not evaluation.feasible


@BOUNDED
@given(candidate=_candidates())
def test_disconnected_baseline_is_infeasible_only_without_a_pool_link(
    candidate,
) -> None:
    config = optimization_settings(
        constraints=HardConstraints(
            require_connectivity=True,
            min_served_demand_ratio=1.0,
        ),
        max_runtime_seconds=5.0,
    )
    evaluation = evaluate_candidate(tiny_twin(), candidate, config)

    if candidate.selected_link_ids:
        assert evaluation.metrics.weak_component_count == 1
        assert "connectivity" not in evaluation.violated_constraints
        assert evaluation.feasible
    else:
        assert evaluation.metrics.weak_component_count > 1
        assert "connectivity" in evaluation.violated_constraints
        assert not evaluation.feasible
