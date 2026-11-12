"""Limit enforcement for nodes and alternative-path requests."""

from __future__ import annotations

import pytest

from config.limits import MAX_ALTERNATIVE_PATHS
from core.exceptions import LimitsExceededError
from network.routing import alternative_paths, reachability_matrix

from .helpers import build_topology, make_link


def _line_of_four():
    return build_topology(
        "Line of four",
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b"),
            make_link("bc", "b", "c"),
            make_link("cd", "c", "d"),
        ],
    )


def test_reachability_is_bounded_by_max_nodes(monkeypatch) -> None:
    monkeypatch.setattr("network.routing.graph.MAX_NODES", 3)

    with pytest.raises(LimitsExceededError):
        reachability_matrix(_line_of_four())


def test_exactly_max_nodes_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr("network.routing.graph.MAX_NODES", 4)

    matrix = reachability_matrix(_line_of_four())

    assert len(matrix.device_ids) == 4


def test_alternative_path_k_is_bounded_by_the_configured_limit() -> None:
    with pytest.raises(LimitsExceededError):
        alternative_paths(
            _line_of_four(),
            "a",
            "d",
            k=MAX_ALTERNATIVE_PATHS + 1,
        )


def test_alternative_path_k_must_be_positive() -> None:
    with pytest.raises(ValueError):
        alternative_paths(_line_of_four(), "a", "d", k=0)


def test_alternative_path_k_equal_to_limit_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr("network.routing.paths.MAX_ALTERNATIVE_PATHS", 1)

    result = alternative_paths(_line_of_four(), "a", "d", k=1)

    assert len(result.paths) == 1
