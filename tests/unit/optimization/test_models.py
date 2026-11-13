"""Unit tests for optimization candidate, settings, and cost models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.exceptions import OptimizationValidationError
from optimization import (
    Candidate,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationSettings,
    build_candidate_twin,
)
from simulation import twin_fingerprint
from tests.unit.optimization.helpers import (
    connect_cd,
    pool_links,
    settings,
    tiny_twin,
    two_tier_model,
)


def test_candidate_is_canonicalized_and_hashes_stably() -> None:
    candidate = Candidate(
        selected_link_ids=("cd", "ad"),
        tier_assignments=(("cd", "large"), ("ad", "small")),
    )
    reordered = Candidate(
        selected_link_ids=("ad", "cd"),
        tier_assignments=(("ad", "small"), ("cd", "large")),
    )
    assert candidate.selected_link_ids == ("ad", "cd")
    assert candidate == reordered
    assert candidate.model_dump() == reordered.model_dump()


def test_candidate_rejects_duplicate_decisions() -> None:
    with pytest.raises(ValidationError):
        Candidate(selected_link_ids=("cd", "cd"))
    with pytest.raises(ValidationError):
        Candidate(tier_assignments=(("cd", "small"), ("cd", "large")))
    with pytest.raises(ValidationError):
        Candidate(cost_multipliers=(("cd", 1.0), ("cd", 2.0)))


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="weights must sum to 1"):
        OptimizationSettings(
            objectives=(
                ObjectiveSpec(
                    kind=ObjectiveKind.link_count,
                    weight=0.4,
                    lower_bound=0,
                    upper_bound=10,
                ),
                ObjectiveSpec(
                    kind=ObjectiveKind.max_utilization,
                    weight=0.4,
                    lower_bound=0,
                    upper_bound=100,
                ),
            ),
            max_iterations=10,
        )


def test_duplicate_objective_kind_rejected() -> None:
    with pytest.raises(ValidationError, match="only once"):
        OptimizationSettings(
            objectives=(
                ObjectiveSpec(
                    kind=ObjectiveKind.link_count,
                    weight=0.5,
                    lower_bound=0,
                    upper_bound=10,
                ),
                ObjectiveSpec(
                    kind=ObjectiveKind.link_count,
                    weight=0.5,
                    lower_bound=0,
                    upper_bound=20,
                ),
            ),
            max_iterations=10,
        )


def test_objective_bounds_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="upper_bound"):
        ObjectiveSpec(
            kind=ObjectiveKind.link_count,
            weight=1.0,
            lower_bound=10,
            upper_bound=10,
        )


def test_candidate_pool_ids_must_be_unique() -> None:
    link = pool_links()[0]
    with pytest.raises(ValidationError, match="unique"):
        OptimizationSettings(
            candidate_pool=(link, link),
            objectives=(
                ObjectiveSpec(
                    kind=ObjectiveKind.link_count,
                    weight=1.0,
                    lower_bound=0,
                    upper_bound=10,
                ),
            ),
            max_iterations=10,
        )


def test_build_candidate_never_mutates_the_baseline() -> None:
    baseline = tiny_twin()
    before = twin_fingerprint(baseline)
    build_candidate_twin(baseline, connect_cd(), settings())
    assert twin_fingerprint(baseline) == before
    assert len(baseline.topology.links) == 2


def test_build_candidate_adds_pool_link_at_selected_tier() -> None:
    twin = build_candidate_twin(tiny_twin(), connect_cd(), settings())
    link = next(link for link in twin.topology.links if link.id == "cd")
    assert link.capacity_mbps == 100.0
    assert link.endpoints == ("c", "d")


def test_build_candidate_applies_routing_cost_multiplier() -> None:
    candidate = Candidate(cost_multipliers=(("ab", 2.5),))
    twin = build_candidate_twin(tiny_twin(), candidate, settings())
    ab = next(link for link in twin.topology.links if link.id == "ab")
    assert ab.cost == 2.5


def test_unknown_tier_is_rejected_at_application() -> None:
    candidate = Candidate(
        selected_link_ids=("cd",),
        tier_assignments=(("cd", "missing"),),
    )
    with pytest.raises(OptimizationValidationError, match="unknown tier"):
        build_candidate_twin(tiny_twin(), candidate, settings())


def test_selecting_a_baseline_link_id_is_rejected() -> None:
    from tests.unit.simulation.helpers import make_link

    candidate = Candidate(selected_link_ids=("ab",))
    config = settings(pool=(make_link("ab", "a", "b"),))
    with pytest.raises(OptimizationValidationError, match="already exist"):
        build_candidate_twin(tiny_twin(), candidate, config)


def test_cost_model_tier_lookup() -> None:
    model = two_tier_model()
    assert model.tier("small").capacity_mbps == 100.0
    assert model.tier_for_capacity(1_000.0) == model.tiers[1]
    assert model.tier_for_capacity(123.0) is None
