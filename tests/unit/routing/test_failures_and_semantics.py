"""Link semantics, parallel-link collapse, and failure handling."""

from __future__ import annotations

import pytest

from core.exceptions import DeviceNotFoundError, LinkNotFoundError
from network.routing import (
    build_routing_graph,
    component_summary,
    reachability_matrix,
    shortest_path,
)

from .helpers import build_topology, make_link


def test_undirected_link_works_in_both_directions() -> None:
    topology = build_topology(
        "Undirected",
        ["a", "b"],
        [make_link("ab", "a", "b", cost=1.0)],
    )

    forward = shortest_path(topology, "a", "b")
    reverse = shortest_path(topology, "b", "a")

    assert forward.reachable is True
    assert reverse.reachable is True
    assert reverse.device_ids == ["b", "a"]
    assert reverse.total_cost == pytest.approx(1.0)


def test_directed_link_only_works_from_first_to_second_endpoint() -> None:
    topology = build_topology(
        "Directed",
        ["a", "b"],
        [make_link("ab", "a", "b", cost=1.0, directed=True)],
    )

    assert shortest_path(topology, "a", "b").reachable is True
    assert shortest_path(topology, "b", "a").reachable is False


def test_parallel_links_collapse_to_the_lowest_cost() -> None:
    topology = build_topology(
        "Parallel",
        ["a", "b"],
        [
            make_link("z-expensive", "a", "b", cost=5.0),
            make_link("a-cheap", "a", "b", cost=2.0),
        ],
    )

    graph = build_routing_graph(topology)

    assert graph.number_of_edges() == 2  # one per direction after collapse
    assert graph["a"]["b"]["link_id"] == "a-cheap"
    assert graph["a"]["b"]["cost"] == 2.0


def test_equal_cost_parallel_links_collapse_to_lowest_link_id() -> None:
    topology = build_topology(
        "Parallel tie",
        ["a", "b"],
        [
            make_link("b-link", "a", "b", cost=2.0),
            make_link("a-link", "a", "b", cost=2.0),
        ],
    )

    graph = build_routing_graph(topology)

    assert graph["a"]["b"]["link_id"] == "a-link"


def test_capacity_is_metadata_and_never_used_for_path_selection() -> None:
    # Capacity deliberately contradicts cost: the low-capacity link is
    # cheaper and must still be selected.
    topology = build_topology(
        "Capacity ignored",
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", cost=1.0, capacity_mbps=1.0),
            make_link("ac", "a", "c", cost=2.0, capacity_mbps=10_000.0),
            make_link("cb", "c", "b", cost=2.0, capacity_mbps=10_000.0),
        ],
    )

    path = shortest_path(topology, "a", "b")

    assert path.device_ids == ["a", "b"]
    assert path.total_cost == pytest.approx(1.0)


def test_failed_link_forces_the_longer_path(unequal_diamond) -> None:
    # Normally a-b-d costs 2. With b-d failed the only route is a-c-d = 4.
    path = shortest_path(unequal_diamond, "a", "d", failed_links=["bd"])

    assert path.reachable is True
    assert path.device_ids == ["a", "c", "d"]
    assert path.total_cost == pytest.approx(4.0)
    assert path.hop_count == 2


def test_failed_node_makes_its_endpoints_unreachable(line_graph) -> None:
    path = shortest_path(line_graph, "a", "d", failed_devices=["c"])

    assert path.reachable is False
    assert "No directed path" in path.reason

    matrix = reachability_matrix(line_graph, failed_devices=["c"])
    assert matrix.device_ids == ["a", "b", "d"]
    assert matrix.excluded_device_ids == ["c"]
    # a <-> b reachable; d is isolated, so four ordered pairs are unreachable:
    # (a, d), (b, d), (d, a), (d, b).
    assert matrix.unreachable_pairs == 4


def test_removing_the_only_bridge_disconnects_the_line(line_graph) -> None:
    summary = component_summary(line_graph, failed_links=["bc"])
    matrix = reachability_matrix(line_graph, failed_links=["bc"])

    assert summary.weak_components == [["a", "b"], ["c", "d"]]
    assert summary.is_weakly_connected is False
    # Two components of size two: 2 * 2 * 2 = 8 unreachable ordered pairs.
    assert matrix.unreachable_pairs == 8


def test_failed_source_or_destination_is_unreachable(weighted_triangle) -> None:
    from_failed = shortest_path(weighted_triangle, "a", "c", failed_devices=["a"])
    to_failed = shortest_path(weighted_triangle, "a", "c", failed_devices=["c"])

    assert from_failed.reachable is False
    assert "failed" in from_failed.reason
    assert to_failed.reachable is False
    assert "failed" in to_failed.reason


def test_unknown_failed_device_raises_typed_error(weighted_triangle) -> None:
    with pytest.raises(DeviceNotFoundError):
        shortest_path(weighted_triangle, "a", "c", failed_devices=["ghost"])


def test_unknown_failed_link_raises_typed_error(weighted_triangle) -> None:
    with pytest.raises(LinkNotFoundError):
        shortest_path(weighted_triangle, "a", "c", failed_links=["ghost"])


def test_unknown_analysis_endpoint_raises_typed_error(weighted_triangle) -> None:
    with pytest.raises(DeviceNotFoundError):
        shortest_path(weighted_triangle, "a", "ghost")


def test_failure_handling_never_mutates_the_input_topology(unequal_diamond) -> None:
    before = unequal_diamond.model_copy(deep=True)

    shortest_path(unequal_diamond, "a", "d", failed_links=["bd"])
    reachability_matrix(unequal_diamond, failed_devices=["c"])
    component_summary(unequal_diamond, failed_links=["ab", "cd"])
    build_routing_graph(unequal_diamond, failed_devices=["b"])

    assert unequal_diamond == before
