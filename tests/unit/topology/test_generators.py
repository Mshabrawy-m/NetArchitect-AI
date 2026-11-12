"""Tests for deterministic topology generators."""

from __future__ import annotations

import pytest

from config.limits import MAX_EDGES, MAX_NODES
from core.exceptions import LimitsExceededError
from network.topology.connectivity import analyze_connectivity
from network.topology.generators import (
    generate_hierarchical_campus,
    generate_hybrid,
    generate_mesh,
    generate_ring,
    generate_spine_leaf,
    generate_star,
    generate_tree,
)
from network.topology.graph import topology_directedness
from network.topology.serialization import from_json, to_json


def _assert_well_formed(topology) -> None:
    assert topology_directedness(topology) == "undirected"
    assert analyze_connectivity(topology).is_connected is True
    assert len({device.id for device in topology.devices}) == len(topology.devices)
    assert len({link.id for link in topology.links}) == len(topology.links)


def _assert_json_round_trip(topology) -> None:
    assert from_json(to_json(topology)) == topology


# Star -----------------------------------------------------------------------


def test_star_counts_and_roles() -> None:
    topology = generate_star(spoke_count=5)

    assert topology.name == "Star topology"
    assert len(topology.devices) == 6
    assert len(topology.links) == 5
    assert topology.devices[0].id == "star-hub"
    assert topology.devices[0].type.value == "switch"
    assert topology.devices[0].role.value == "core"
    assert all(device.type.value == "host" for device in topology.devices[1:])
    _assert_well_formed(topology)


def test_star_is_deterministic() -> None:
    assert generate_star(spoke_count=3) == generate_star(spoke_count=3)


def test_star_hub_is_center_of_every_link() -> None:
    topology = generate_star(spoke_count=4)

    assert all("star-hub" in link.endpoints for link in topology.links)


def test_star_rejects_zero_spokes() -> None:
    with pytest.raises(ValueError, match="spoke_count"):
        generate_star(spoke_count=0)


def test_star_rejects_oversized_request() -> None:
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_NODES}"):
        generate_star(spoke_count=MAX_NODES)


# Ring -----------------------------------------------------------------------


def test_ring_counts_and_closure() -> None:
    topology = generate_ring(node_count=5)

    assert len(topology.devices) == 5
    assert len(topology.links) == 5
    assert topology.links[0].endpoints == ("ring-node-00", "ring-node-01")
    assert topology.links[-1].endpoints == ("ring-node-04", "ring-node-00")
    assert all(device.role.value == "core" for device in topology.devices)
    _assert_well_formed(topology)


def test_ring_is_deterministic() -> None:
    assert generate_ring(node_count=6) == generate_ring(node_count=6)


def test_ring_rejects_fewer_than_three_nodes() -> None:
    with pytest.raises(ValueError, match="node_count"):
        generate_ring(node_count=2)


def test_ring_rejects_oversized_request() -> None:
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_NODES}"):
        generate_ring(node_count=MAX_NODES + 1)


# Mesh -----------------------------------------------------------------------


def test_full_mesh_counts_and_degrees() -> None:
    topology = generate_mesh(node_count=5)

    assert len(topology.devices) == 5
    assert len(topology.links) == 10
    degrees = {device.id: 0 for device in topology.devices}
    for link in topology.links:
        for endpoint in link.endpoints:
            degrees[endpoint] += 1
    assert set(degrees.values()) == {4}
    _assert_well_formed(topology)


def test_mesh_is_deterministic() -> None:
    assert generate_mesh(node_count=4) == generate_mesh(node_count=4)


def test_mesh_rejects_single_node() -> None:
    with pytest.raises(ValueError, match="node_count"):
        generate_mesh(node_count=1)


def test_mesh_rejects_requests_over_edge_limit() -> None:
    # 64 nodes need 2016 links, which exceeds MAX_EDGES (2000).
    with pytest.raises(LimitsExceededError) as error:
        generate_mesh(node_count=64)

    assert f"limit is {MAX_EDGES}" in str(error.value)


def test_mesh_rejects_requests_over_node_limit() -> None:
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_NODES}"):
        generate_mesh(node_count=MAX_NODES + 1)


# Tree -----------------------------------------------------------------------


def test_tree_depth_two_binary_counts() -> None:
    topology = generate_tree(depth=2, branching_factor=2)

    assert len(topology.devices) == 7
    assert len(topology.links) == 6
    assert topology.devices[0].id == "tree-l0-n00"
    assert topology.devices[0].role.value == "core"
    assert topology.devices[-1].role.value == "access"
    _assert_well_formed(topology)


def test_tree_depth_zero_is_single_root() -> None:
    topology = generate_tree(depth=0)

    assert len(topology.devices) == 1
    assert topology.links == []
    assert analyze_connectivity(topology).is_connected is True


def test_tree_depth_one_ternary_counts() -> None:
    topology = generate_tree(depth=1, branching_factor=3)

    assert len(topology.devices) == 4
    assert len(topology.links) == 3
    _assert_well_formed(topology)


def test_tree_is_deterministic() -> None:
    assert generate_tree(depth=3, branching_factor=2) == generate_tree(
        depth=3, branching_factor=2
    )


def test_tree_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="depth"):
        generate_tree(depth=-1)
    with pytest.raises(ValueError, match="branching_factor"):
        generate_tree(branching_factor=0)


def test_tree_rejects_oversized_request() -> None:
    # depth 8 with branching factor 2 needs 511 devices.
    with pytest.raises(LimitsExceededError, match=f"limit of {MAX_NODES}"):
        generate_tree(depth=8, branching_factor=2)


# Hierarchical campus --------------------------------------------------------


def test_hierarchical_campus_single_homed_counts() -> None:
    topology = generate_hierarchical_campus(
        distribution_count=3,
        access_per_distribution=2,
        redundant_uplinks=False,
    )

    assert len(topology.devices) == 1 + 3 + 3 * 2
    assert len(topology.links) == 3 + 3 * 2
    roles = [device.role.value for device in topology.devices]
    assert roles.count("core") == 1
    assert roles.count("distribution") == 3
    assert roles.count("access") == 6
    _assert_well_formed(topology)
    _assert_json_round_trip(topology)


def test_hierarchical_campus_dual_homed_counts_and_degrees() -> None:
    topology = generate_hierarchical_campus(
        distribution_count=3,
        access_per_distribution=2,
        redundant_uplinks=True,
    )

    assert len(topology.devices) == 2 + 3 + 3 * 2
    assert len(topology.links) == 2 * 3 + 2 * 3 * 2
    degrees = {device.id: 0 for device in topology.devices}
    for link in topology.links:
        for endpoint in link.endpoints:
            degrees[endpoint] += 1
    # Each distribution switch: two core uplinks + 2 access switches x 2 links.
    assert degrees["campus-dist-01"] == 2 + 2 * 2
    # Each access switch: dual-homed to two distribution switches.
    assert degrees["campus-acc-01-01"] == 2
    _assert_well_formed(topology)
    _assert_json_round_trip(topology)


def test_hierarchical_campus_is_deterministic() -> None:
    first = generate_hierarchical_campus(distribution_count=2, access_per_distribution=3)
    second = generate_hierarchical_campus(
        distribution_count=2, access_per_distribution=3
    )
    assert first == second


def test_hierarchical_campus_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="distribution_count"):
        generate_hierarchical_campus(distribution_count=0)
    with pytest.raises(ValueError, match="access_per_distribution"):
        generate_hierarchical_campus(access_per_distribution=0)
    with pytest.raises(ValueError, match="redundant_uplinks"):
        generate_hierarchical_campus(
            distribution_count=1, redundant_uplinks=True
        )


def test_hierarchical_campus_rejects_oversized_request() -> None:
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_NODES}"):
        generate_hierarchical_campus(
            distribution_count=100, access_per_distribution=10
        )


# Spine-leaf ----------------------------------------------------------------


def test_spine_leaf_full_mesh_counts_and_degrees() -> None:
    topology = generate_spine_leaf(spines=2, leaves=4, full_mesh=True)

    assert len(topology.devices) == 6
    assert len(topology.links) == 2 * 4
    degrees = {device.id: 0 for device in topology.devices}
    for link in topology.links:
        for endpoint in link.endpoints:
            degrees[endpoint] += 1
    assert degrees["fabric-spine-01"] == 4
    assert degrees["fabric-leaf-01"] == 2
    _assert_well_formed(topology)
    _assert_json_round_trip(topology)


def test_spine_leaf_partial_mesh_counts() -> None:
    topology = generate_spine_leaf(spines=2, leaves=5, full_mesh=False)

    assert len(topology.devices) == 7
    assert len(topology.links) == 5 * 2
    _assert_well_formed(topology)
    _assert_json_round_trip(topology)


def test_spine_leaf_is_deterministic() -> None:
    assert generate_spine_leaf(spines=3, leaves=4) == generate_spine_leaf(
        spines=3, leaves=4
    )


def test_spine_leaf_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="spines"):
        generate_spine_leaf(spines=0)
    with pytest.raises(ValueError, match="leaves"):
        generate_spine_leaf(leaves=0)


def test_spine_leaf_rejects_oversized_node_request() -> None:
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_NODES}"):
        generate_spine_leaf(spines=250, leaves=251)


def test_spine_leaf_rejects_oversized_edge_request() -> None:
    # 50 spines x 41 leaves = 2050 links with only 91 devices.
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_EDGES}"):
        generate_spine_leaf(spines=50, leaves=41)


# Hybrid --------------------------------------------------------------------


def test_hybrid_composes_ring_and_stars() -> None:
    topology = generate_hybrid(core_nodes=4, access_per_core=3)

    assert len(topology.devices) == 4 * (2 + 3)
    assert len(topology.links) == 4 * (3 + 2)
    roles = [device.role.value for device in topology.devices]
    assert roles.count("core") == 4
    assert roles.count("distribution") == 4
    assert roles.count("access") == 12
    assert any(link.id == "hybrid-link-uplink-01" for link in topology.links)
    _assert_well_formed(topology)
    _assert_json_round_trip(topology)


def test_hybrid_is_deterministic() -> None:
    assert generate_hybrid(core_nodes=5, access_per_core=2) == generate_hybrid(
        core_nodes=5, access_per_core=2
    )


def test_hybrid_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="core_nodes"):
        generate_hybrid(core_nodes=2)
    with pytest.raises(ValueError, match="access_per_core"):
        generate_hybrid(access_per_core=0)


def test_hybrid_rejects_oversized_request() -> None:
    with pytest.raises(LimitsExceededError, match=f"limit is {MAX_NODES}"):
        generate_hybrid(core_nodes=100, access_per_core=10)
