"""Unit tests for Pareto dominance and crowding-distance arithmetic."""

from __future__ import annotations

import pytest

from optimization import (
    ObjectiveDirection,
    crowding_distance_values,
    dominates_values,
)


def test_minimize_dominance_requires_all_and_one_strict() -> None:
    directions = (ObjectiveDirection.minimize, ObjectiveDirection.minimize)
    assert dominates_values((1.0, 1.0), (2.0, 2.0), directions)
    assert dominates_values((1.0, 2.0), (2.0, 2.0), directions)
    assert not dominates_values((1.0, 1.0), (1.0, 1.0), directions)
    assert not dominates_values((1.0, 2.0), (2.0, 1.0), directions)
    assert not dominates_values((2.0, 1.0), (1.0, 2.0), directions)


def test_maximize_dominance_is_inverted() -> None:
    directions = (ObjectiveDirection.maximize, ObjectiveDirection.maximize)
    assert dominates_values((2.0, 3.0), (1.0, 2.0), directions)
    assert not dominates_values((2.0, 1.0), (1.0, 2.0), directions)


def test_mixed_direction_dominance() -> None:
    directions = (ObjectiveDirection.minimize, ObjectiveDirection.maximize)
    assert dominates_values((1.0, 5.0), (2.0, 4.0), directions)
    assert not dominates_values((1.0, 3.0), (2.0, 4.0), directions)
    assert not dominates_values((2.0, 5.0), (1.0, 4.0), directions)


def test_dominance_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        dominates_values((1.0,), (1.0, 2.0), (ObjectiveDirection.minimize,))


def test_crowding_distance_boundaries_are_infinite() -> None:
    distances = crowding_distance_values([[0.0], [1.0], [2.0]])
    assert distances[0] == float("inf")
    assert distances[2] == float("inf")
    assert distances[1] == pytest.approx(1.0)


def test_crowding_distance_sums_normalized_neighbour_gaps() -> None:
    # One objective with values 0, 1, 2, 4: range 4.
    # Interior point 1 -> (2 - 0) / 4 = 0.5.
    # Interior point 2 -> (4 - 1) / 4 = 0.75.
    values = [[0.0], [1.0], [2.0], [4.0]]
    distances = crowding_distance_values(values)
    assert distances[1] == pytest.approx(0.5)
    assert distances[2] == pytest.approx(0.75)


def test_crowding_distance_with_two_points_is_infinite() -> None:
    assert crowding_distance_values([[0.0], [1.0]]) == [
        float("inf"),
        float("inf"),
    ]
    assert crowding_distance_values([]) == []


def test_crowding_distance_ignores_zero_width_objective() -> None:
    # Second objective has no spread, so it adds nothing.
    values = [[0.0, 1.0], [1.0, 1.0], [3.0, 1.0]]
    distances = crowding_distance_values(values)
    assert distances[1] == pytest.approx(1.0)
