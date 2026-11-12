"""Tests for deterministic topology generators."""

from __future__ import annotations

import pytest

from config.limits import MAX_EDGES, MAX_NODES
from core.exceptions import LimitsExceededError
from network.topology.connectivity import analyze_connectivity
from network.topology.generators import (
    generate_mesh,
    generate_ring,
    generate_star,
    generate_tree,
)
from network.topology.graph import topology_directedness


def _assert_well_formed(topology) -> None:
    assert topology_directedness(topology) == "undirected"
    assert analyze_connectivity(topology).is_connected is True
    assert len({device.id for device in topology.devices}) == len(topology.devices)
    assert len({link.id for link in topology.links}) == len(topology.links)


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
