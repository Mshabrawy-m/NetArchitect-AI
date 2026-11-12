"""Known properties of generated topologies and path-walk invariants."""

from __future__ import annotations

from itertools import pairwise

import pytest

from network.routing import (
    alternative_paths,
    build_routing_graph,
    reachability_matrix,
    routing_table,
    shortest_path,
)
from network.topology import (
    generate_hierarchical_campus,
    generate_ring,
    generate_spine_leaf,
    generate_star,
)


def _assert_all_pairs_reachable_and_walks_are_valid(topology) -> None:
    graph = build_routing_graph(topology)
    matrix = reachability_matrix(topology)

    assert matrix.unreachable_pairs == 0
    for source in matrix.device_ids:
        for destination in matrix.device_ids:
            if source == destination:
                continue
            path = shortest_path(topology, source, destination)
            assert path.reachable is True
            assert path.device_ids[0] == source
            assert path.device_ids[-1] == destination
            walked = sum(
                float(graph[first][second]["cost"])
                for first, second in pairwise(path.device_ids)
            )
            assert path.total_cost == pytest.approx(walked)
            assert path.hop_count == len(path.device_ids) - 1


def test_star_spoke_to_spoke_traverses_the_hub() -> None:
    topology = generate_star(spoke_count=4)

    # star-spoke-00 -> star-hub -> star-spoke-01, two links at cost 1 each.
    path = shortest_path(topology, "star-spoke-00", "star-spoke-01")

    assert path.device_ids == ["star-spoke-00", "star-hub", "star-spoke-01"]
    assert path.total_cost == pytest.approx(2.0)
    assert path.hop_count == 2
    _assert_all_pairs_reachable_and_walks_are_valid(topology)


def test_star_hub_failure_isolates_every_spoke() -> None:
    topology = generate_star(spoke_count=4)

    matrix = reachability_matrix(topology, failed_devices=["star-hub"])

    assert matrix.excluded_device_ids == ["star-hub"]
    # Four isolated spokes: 4 * 3 = 12 unreachable ordered pairs.
    assert matrix.unreachable_pairs == 12


def test_ring_has_two_equal_cost_routes_to_the_opposite_node() -> None:
    topology = generate_ring(node_count=4)

    # ring-node-00 -> ring-node-02 clockwise or counter-clockwise, cost 2.
    result = alternative_paths(topology, "ring-node-00", "ring-node-02", k=2)

    assert [path.device_ids for path in result.paths] == [
        ["ring-node-00", "ring-node-01", "ring-node-02"],
        ["ring-node-00", "ring-node-03", "ring-node-02"],
    ]
    _assert_all_pairs_reachable_and_walks_are_valid(topology)


def test_campus_access_to_access_crosses_core_and_distribution() -> None:
    topology = generate_hierarchical_campus(
        distribution_count=2,
        access_per_distribution=3,
    )

    # acc-01-01 -> dist-01 -> core-01 -> dist-02 -> acc-02-01 = 4 hops.
    path = shortest_path(topology, "campus-acc-01-01", "campus-acc-02-01")

    assert path.device_ids == [
        "campus-acc-01-01",
        "campus-dist-01",
        "campus-core-01",
        "campus-dist-02",
        "campus-acc-02-01",
    ]
    assert path.total_cost == pytest.approx(4.0)
    assert path.hop_count == 4
    _assert_all_pairs_reachable_and_walks_are_valid(topology)


def test_redundant_campus_survives_one_core_uplink_failure() -> None:
    topology = generate_hierarchical_campus(
        distribution_count=2,
        access_per_distribution=3,
        redundant_uplinks=True,
    )

    matrix = reachability_matrix(
        topology,
        failed_links=["campus-link-core-01-dist-01"],
    )

    assert matrix.unreachable_pairs == 0


def test_spine_leaf_leaves_have_two_spine_alternatives() -> None:
    topology = generate_spine_leaf(spines=2, leaves=4)

    # fabric-leaf-01 -> fabric-spine-01 -> fabric-leaf-02
    # fabric-leaf-01 -> fabric-spine-02 -> fabric-leaf-02
    result = alternative_paths(topology, "fabric-leaf-01", "fabric-leaf-02", k=2)

    assert [path.device_ids for path in result.paths] == [
        ["fabric-leaf-01", "fabric-spine-01", "fabric-leaf-02"],
        ["fabric-leaf-01", "fabric-spine-02", "fabric-leaf-02"],
    ]
    assert all(path.total_cost == pytest.approx(2.0) for path in result.paths)
    _assert_all_pairs_reachable_and_walks_are_valid(topology)


def test_spine_leaf_routing_table_lists_every_other_device() -> None:
    topology = generate_spine_leaf(spines=2, leaves=4)

    table = routing_table(topology, "fabric-leaf-01")

    assert len(table.entries) == len(topology.devices) - 1
    assert {entry.destination for entry in table.entries} == {
        device.id for device in topology.devices if device.id != "fabric-leaf-01"
    }
