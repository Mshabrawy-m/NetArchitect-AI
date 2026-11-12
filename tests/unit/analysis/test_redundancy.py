"""Hand-computed node- and edge-disjoint path counts."""

from __future__ import annotations

import pytest

from core.exceptions import DeviceNotFoundError, LinkNotFoundError
from network.analysis import redundancy
from network.topology import generate_ring, generate_spine_leaf, generate_star

from .helpers import build_topology, make_link


def test_line_has_one_disjoint_path(line_graph) -> None:
    report = redundancy(line_graph, "a", "d")

    assert report.reachable is True
    assert report.node_disjoint_paths == 1
    assert report.edge_disjoint_paths == 1


def test_ring_has_two_disjoint_paths(ring_graph) -> None:
    # r1-r2-r3 and r1-r4-r3 share no intermediate device or link.
    opposite = redundancy(ring_graph, "r1", "r3")
    adjacent = redundancy(ring_graph, "r1", "r2")

    assert (opposite.node_disjoint_paths, opposite.edge_disjoint_paths) == (2, 2)
    assert (adjacent.node_disjoint_paths, adjacent.edge_disjoint_paths) == (2, 2)


def test_star_paths_share_the_hub(star_graph) -> None:
    report = redundancy(star_graph, "s1", "s2")

    assert report.node_disjoint_paths == 1
    assert report.edge_disjoint_paths == 1


def test_diamond_has_two_node_and_edge_disjoint_paths(
    equal_cost_diamond,
) -> None:
    report = redundancy(equal_cost_diamond, "a", "d")

    assert report.node_disjoint_paths == 2
    assert report.edge_disjoint_paths == 2


def test_parallel_links_add_edge_redundancy_but_not_node_redundancy() -> None:
    topology = build_topology(
        "Parallel pair",
        ["a", "b"],
        [
            make_link("ab-1", "a", "b"),
            make_link("ab-2", "a", "b"),
        ],
    )

    report = redundancy(topology, "a", "b")

    assert report.node_disjoint_paths == 1
    assert report.edge_disjoint_paths == 2


def test_redundancy_honors_directed_links(directed_chain) -> None:
    forward = redundancy(directed_chain, "r1", "r3")
    reverse = redundancy(directed_chain, "r3", "r1")

    assert (forward.node_disjoint_paths, forward.edge_disjoint_paths) == (1, 1)
    assert reverse.reachable is False
    assert reverse.node_disjoint_paths == 0
    assert reverse.edge_disjoint_paths == 0
    assert "No directed path" in reverse.reason


def test_direction_can_reduce_redundancy_in_one_direction_only() -> None:
    # a -> b is directed; a-c and c-b are undirected.
    topology = build_topology(
        "Mixed",
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", directed=True),
            make_link("ac", "a", "c"),
            make_link("cb", "c", "b"),
        ],
    )

    forward = redundancy(topology, "a", "b")
    reverse = redundancy(topology, "b", "a")

    assert (forward.node_disjoint_paths, forward.edge_disjoint_paths) == (2, 2)
    assert (reverse.node_disjoint_paths, reverse.edge_disjoint_paths) == (1, 1)


def test_failed_link_reduces_ring_redundancy_to_one(ring_graph) -> None:
    report = redundancy(ring_graph, "r1", "r3", failed_links=["l12"])

    assert report.reachable is True
    assert report.node_disjoint_paths == 1
    assert report.edge_disjoint_paths == 1


def test_failed_node_makes_pair_unreachable(line_graph) -> None:
    report = redundancy(line_graph, "a", "d", failed_devices=["c"])

    assert report.reachable is False
    assert report.node_disjoint_paths == 0
    assert report.edge_disjoint_paths == 0


def test_failed_endpoint_is_unreachable(line_graph) -> None:
    report = redundancy(line_graph, "a", "d", failed_devices=["a"])

    assert report.reachable is False
    assert "failed" in report.reason


def test_source_equals_destination_is_reported_as_undefined(line_graph) -> None:
    report = redundancy(line_graph, "b", "b")

    assert report.reachable is True
    assert report.node_disjoint_paths == 0
    assert report.edge_disjoint_paths == 0
    assert "undefined" in report.reason


def test_unknown_device_raises_typed_error(line_graph) -> None:
    with pytest.raises(DeviceNotFoundError):
        redundancy(line_graph, "a", "ghost")


def test_unknown_failure_id_raises_typed_error(line_graph) -> None:
    with pytest.raises(LinkNotFoundError):
        redundancy(line_graph, "a", "d", failed_links=["ghost"])


def test_redundancy_does_not_mutate_the_topology(line_graph) -> None:
    before = line_graph.model_copy(deep=True)

    redundancy(line_graph, "a", "d", failed_links=["bc"])

    assert line_graph == before


def test_generated_topologies_have_expected_redundancy() -> None:
    star = redundancy(generate_star(spoke_count=3), "star-spoke-00", "star-spoke-01")
    ring = redundancy(generate_ring(node_count=4), "ring-node-00", "ring-node-02")
    fabric = redundancy(
        generate_spine_leaf(spines=2, leaves=4),
        "fabric-leaf-01",
        "fabric-leaf-02",
    )

    assert (star.node_disjoint_paths, star.edge_disjoint_paths) == (1, 1)
    assert (ring.node_disjoint_paths, ring.edge_disjoint_paths) == (2, 2)
    assert (fabric.node_disjoint_paths, fabric.edge_disjoint_paths) == (2, 2)
