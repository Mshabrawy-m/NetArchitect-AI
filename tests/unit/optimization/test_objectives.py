"""Objective arithmetic and min-max normalization tests with hand values."""

from __future__ import annotations

import pytest

from optimization import (
    Candidate,
    ObjectiveKind,
    ObjectiveSpec,
    infrastructure_cost_proxy,
    normalize_value,
    objective_value,
    weighted_score,
)
from tests.unit.optimization.helpers import (
    TIER_LARGE,
    TIER_SMALL,
    settings,
    tiny_twin,
)


def test_infrastructure_cost_proxy_arithmetic() -> None:
    # Device cost 5 * 4 devices = 20.
    # Selected cd at large = 100; selected ad at small = 10.
    # Baseline ab 100 Mbps -> large is a 100 - 10 = 90 tier delta.
    # Total = 20 + 100 + 10 + 90 = 220 modeled cost units.
    candidate = Candidate(
        selected_link_ids=("cd", "ad"),
        tier_assignments=(("cd", "large"), ("ad", "small"), ("ab", "large")),
    )
    cost = infrastructure_cost_proxy(
        tiny_twin(),
        candidate,
        settings(cost_model=_with_device_cost(5.0)),
    )
    assert cost == pytest.approx(220.0)


def _with_device_cost(device_cost: float):
    from optimization import CostModel

    return CostModel(
        tiers=(TIER_SMALL, TIER_LARGE),
        device_cost_proxy=device_cost,
    )


def test_upgrade_to_the_same_tier_has_zero_delta() -> None:
    # Both baseline links are already 100 Mbps, matching the small tier (10).
    candidate = Candidate(tier_assignments=(("ab", "small"),))
    cost = infrastructure_cost_proxy(tiny_twin(), candidate, settings())
    assert cost == pytest.approx(0.0)


def test_unknown_capacity_has_no_sunk_cost() -> None:
    # A 250 Mbps baseline link matches no tier, so the full large cost is charged.
    candidate = Candidate(tier_assignments=(("ab", "large"),))
    cost = infrastructure_cost_proxy(
        tiny_twin(capacity_mbps=250.0),
        candidate,
        settings(),
    )
    assert cost == pytest.approx(100.0)


def test_minimize_normalization_and_clamping() -> None:
    spec = ObjectiveSpec(
        kind=ObjectiveKind.link_count,
        weight=1.0,
        lower_bound=10,
        upper_bound=20,
    )
    assert normalize_value(10, spec) == pytest.approx(0.0)
    assert normalize_value(15, spec) == pytest.approx(0.5)
    assert normalize_value(20, spec) == pytest.approx(1.0)
    assert normalize_value(5, spec) == pytest.approx(0.0)
    assert normalize_value(25, spec) == pytest.approx(1.0)


def test_maximize_normalization_inverts_direction() -> None:
    spec = ObjectiveSpec(
        kind=ObjectiveKind.min_edge_disjoint_paths,
        weight=1.0,
        lower_bound=0,
        upper_bound=4,
    )
    assert normalize_value(0, spec) == pytest.approx(1.0)
    assert normalize_value(2, spec) == pytest.approx(0.5)
    assert normalize_value(4, spec) == pytest.approx(0.0)


def test_weighted_score_sums_contributions() -> None:
    specs = (
        ObjectiveSpec(
            kind=ObjectiveKind.link_count,
            weight=0.25,
            lower_bound=0,
            upper_bound=10,
        ),
        ObjectiveSpec(
            kind=ObjectiveKind.max_utilization,
            weight=0.75,
            lower_bound=0,
            upper_bound=100,
        ),
    )
    values = (
        objective_value(specs[0], 5.0),  # normalized 0.5 -> 0.125
        objective_value(specs[1], 50.0),  # normalized 0.5 -> 0.375
    )
    assert weighted_score(values) == pytest.approx(0.5)


def test_objective_value_carries_metadata() -> None:
    spec = ObjectiveSpec(
        kind=ObjectiveKind.infrastructure_cost,
        weight=0.5,
        lower_bound=0,
        upper_bound=100,
    )
    value = objective_value(spec, 25.0)
    assert value.label == "Infrastructure cost proxy"
    assert value.unit == "modeled cost units"
    assert value.raw_value == 25.0
    assert value.normalized_value == pytest.approx(0.25)
    assert value.contribution == pytest.approx(0.125)
