"""Equivalence of the sparse hot paths and the frozen NetworkX reference.

The reference implementation lives in ``tests/routing_reference.py`` and is
never modified to accommodate the production code.
"""

from __future__ import annotations

from itertools import product

import pytest

from core.schemas.network import Topology
from network.routing import component_summary, reachability_matrix, shortest_path
from network.topology import (
    generate_hierarchical_campus,
    generate_ring,
    generate_spine_leaf,
    generate_star,
)
from tests.routing_reference import (
    component_summary as reference_component_summary,
)
from tests.routing_reference import (
    reachability_matrix as reference_reachability_matrix,
)
from tests.routing_reference import (
    shortest_path as reference_shortest_path,
)

from .helpers import build_topology, make_link

TieTopology = Topology


@pytest.fixture
def tie_topology() -> TieTopology:
    """Equal-cost device paths plus equal-cost and cheaper parallel links."""
    return build_topology(
        "Tie topology",
        ["a", "b", "c", "d", "e"],
        [
            make_link("ab-first", "a", "b", cost=1.0),
            make_link("ab-second", "a", "b", cost=1.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("ac", "a", "c", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
            make_link("de", "d", "e", cost=2.0),
            # A directed shortcut that does not create a return path.
            make_link("ae-directed", "a", "e", cost=2.0, directed=True),
        ],
    )


@pytest.fixture
def directed_chain() -> Topology:
    return build_topology(
        "Directed chain",
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0, directed=True),
            make_link("bc", "b", "c", cost=1.0, directed=True),
            make_link("cd", "c", "d", cost=1.0, directed=True),
        ],
    )


@pytest.fixture
def disconnected_topology() -> Topology:
    return build_topology(
        "Disconnected",
        ["a", "b", "c", "d", "e"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("ba", "b", "a", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
            make_link("dc", "d", "c", cost=1.0),
        ],
    )


def _assert_equivalent(
    topology: Topology,
    *,
    pairs: list[tuple[str, str]],
    failed_devices: tuple[str, ...] = (),
    failed_links: tuple[str, ...] = (),
) -> None:
    for source, destination in pairs:
        actual = shortest_path(
            topology,
            source,
            destination,
            failed_devices=failed_devices,
            failed_links=failed_links,
        ).model_dump()
        expected = reference_shortest_path(
            topology,
            source,
            destination,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
        assert actual == expected, (source, destination, failed_devices, failed_links)

    assert reachability_matrix(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    ).model_dump() == reference_reachability_matrix(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    assert component_summary(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    ).model_dump() == reference_component_summary(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )


def _all_pairs(topology: Topology) -> list[tuple[str, str]]:
    ids = [device.id for device in topology.devices]
    return list(product(ids, repeat=2))


def test_ties_parallel_links_and_directed_shortcut_match(tie_topology) -> None:
    _assert_equivalent(tie_topology, pairs=_all_pairs(tie_topology))


def test_equal_cost_parallel_link_uses_lowest_link_id(tie_topology) -> None:
    actual = shortest_path(tie_topology, "a", "b")
    expected = reference_shortest_path(tie_topology, "a", "b")

    assert actual.model_dump() == expected
    assert actual.hops[0].link_id == "ab-first"


def test_failed_link_changes_the_same_path_as_the_reference(tie_topology) -> None:
    _assert_equivalent(
        tie_topology,
        pairs=_all_pairs(tie_topology),
        failed_links=("ab-first", "ab-second"),
    )


def test_failed_device_changes_the_same_path_as_the_reference(tie_topology) -> None:
    _assert_equivalent(
        tie_topology,
        pairs=_all_pairs(tie_topology),
        failed_devices=("b",),
    )


def test_directed_links_keep_the_reference_asymmetry(directed_chain) -> None:
    assert shortest_path(directed_chain, "a", "d").reachable is True
    assert shortest_path(directed_chain, "d", "a").reachable is False
    _assert_equivalent(directed_chain, pairs=_all_pairs(directed_chain))


def test_disconnected_graph_matches_reference(disconnected_topology) -> None:
    _assert_equivalent(
        disconnected_topology,
        pairs=_all_pairs(disconnected_topology),
    )


def test_float_association_matches_reference() -> None:
    """Regression: 0.1 + 0.2 is not the same float as 0.3.

    This topology once made the sparse router prefer ``a-b-d`` (0.30000000000000004)
    over the reference's exact ``a-d`` (0.3) because path extraction used a
    tolerance. Suffix distances must be computed from the candidate neighbor as
    source and compared exactly.
    """
    topology = build_topology(
        "Float association",
        ["a", "b", "d"],
        [
            make_link("ab", "a", "b", cost=0.1),
            make_link("bd", "b", "d", cost=0.2),
            make_link("ad", "a", "d", cost=0.3),
        ],
    )
    _assert_equivalent(topology, pairs=_all_pairs(topology))
    assert shortest_path(topology, "a", "d").device_ids == ["a", "d"]


@pytest.mark.parametrize(
    "topology",
    [
        generate_star(spoke_count=6, id_prefix="equiv-star"),
        generate_ring(node_count=6, id_prefix="equiv-ring"),
        generate_spine_leaf(spines=2, leaves=4, id_prefix="equiv-fabric"),
        generate_hierarchical_campus(
            name="Equivalence campus",
            distribution_count=2,
            access_per_distribution=3,
            id_prefix="equiv-campus",
        ),
    ],
    ids=["star", "ring", "spine-leaf", "campus"],
)
def test_generated_topologies_match_reference(topology) -> None:
    _assert_equivalent(topology, pairs=_all_pairs(topology))


def test_max_size_topology_matches_reference() -> None:
    topology = generate_hierarchical_campus(
        name="Max-size equivalence campus",
        distribution_count=3,
        access_per_distribution=165,
        id_prefix="equiv-max",
    )
    ids = [device.id for device in topology.devices]
    pairs = [
        (ids[0], ids[-1]),
        (ids[-1], ids[0]),
        (ids[1], ids[100]),
        (ids[100], ids[1]),
        (ids[250], ids[400]),
        (ids[400], ids[250]),
        (ids[10], ids[10]),
    ]
    _assert_equivalent(topology, pairs=pairs)
