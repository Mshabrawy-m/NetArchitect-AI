"""Tests for NetworkX conversion in ``network.topology.graph``."""

from __future__ import annotations

import networkx as nx
import pytest

from core.exceptions import SchemaError
from core.schemas.network import DeviceRole, DeviceType, Topology
from network.topology.graph import (
    DIRECTED,
    MIXED,
    UNDIRECTED,
    from_networkx,
    to_networkx,
    topology_directedness,
)

from .helpers import make_device, make_link


def test_topology_directedness_reports_mixed(mixed_topology: Topology) -> None:
    assert topology_directedness(mixed_topology) == MIXED


def test_topology_directedness_reports_undirected() -> None:
    topology = Topology(
        name="t",
        devices=[make_device("a"), make_device("b")],
        links=[make_link("l", "a", "b")],
    )
    assert topology_directedness(topology) == UNDIRECTED


def test_topology_directedness_reports_directed() -> None:
    topology = Topology(
        name="t",
        devices=[make_device("a"), make_device("b")],
        links=[make_link("l", "a", "b", directed=True)],
    )
    assert topology_directedness(topology) == DIRECTED


def test_topology_directedness_empty_is_undirected() -> None:
    assert topology_directedness(Topology(name="empty")) == UNDIRECTED


def test_to_networkx_represents_undirected_links_as_reciprocal_arcs(
    mixed_topology: Topology,
) -> None:
    graph = to_networkx(mixed_topology)

    assert isinstance(graph, nx.MultiDiGraph)
    assert set(graph.nodes) == {"r1", "r2", "h1"}
    # Undirected link -> two arcs; directed link -> one arc.
    assert graph.number_of_edges() == 3
    assert graph.has_edge("r1", "r2", key="l-undirected")
    assert graph.has_edge("r2", "r1", key="l-undirected")
    assert graph.has_edge("r1", "h1", key="l-directed")
    assert not graph.has_edge("h1", "r1", key="l-directed")


def test_to_networkx_sets_graph_metadata(mixed_topology: Topology) -> None:
    graph = to_networkx(mixed_topology)

    assert graph.graph["name"] == "Mixed test topology"
    assert graph.graph["directedness"] == MIXED


def test_to_networkx_sets_node_and_edge_attributes(
    mixed_topology: Topology,
) -> None:
    graph = to_networkx(mixed_topology)

    assert graph.nodes["r1"] == {
        "type": "router",
        "site": "site-1",
        "role": "core",
    }
    attributes = graph.edges["r1", "r2", "l-undirected"]
    assert attributes["endpoints"] == ("r2", "r1")
    assert attributes["capacity_mbps"] == 1000.0
    assert attributes["cost"] == 2.5
    assert attributes["directed"] is False


def test_round_trip_through_networkx_is_exact(mixed_topology: Topology) -> None:
    restored = from_networkx(to_networkx(mixed_topology))
    assert restored == mixed_topology


def test_round_trip_preserves_enum_types(mixed_topology: Topology) -> None:
    restored = from_networkx(to_networkx(mixed_topology))
    assert restored.devices[0].type is DeviceType.router
    assert restored.devices[1].role is DeviceRole.distribution


def test_from_networkx_uses_name_override(mixed_topology: Topology) -> None:
    restored = from_networkx(to_networkx(mixed_topology), name="Renamed")
    assert restored.name == "Renamed"


def test_from_networkx_accepts_plain_undirected_graph() -> None:
    graph = nx.Graph()
    graph.add_node("a", type="router", site="s", role="core")
    graph.add_node("b", type="switch", site="s", role="access")
    graph.add_edge("a", "b", capacity_mbps=100.0, cost=1.0)

    topology = from_networkx(graph, name="plain")

    assert topology.name == "plain"
    assert len(topology.links) == 1
    assert topology.links[0].id == "link-0"
    assert topology.links[0].directed is False


def test_from_networkx_accepts_plain_directed_graph() -> None:
    graph = nx.DiGraph()
    graph.add_node("a", type="router", site="s", role="core")
    graph.add_node("b", type="switch", site="s", role="access")
    graph.add_edge("a", "b", link_id="l1", capacity_mbps=100.0, cost=1.0)

    topology = from_networkx(graph)

    assert topology.links[0].directed is True
    assert topology.links[0].endpoints == ("a", "b")


def test_from_networkx_rejects_missing_node_attributes() -> None:
    graph = nx.Graph()
    graph.add_node("a", type="router")

    with pytest.raises(SchemaError, match="missing required attributes"):
        from_networkx(graph)


def test_from_networkx_rejects_invalid_enum_values() -> None:
    graph = nx.Graph()
    graph.add_node("a", type="router", site="s", role="core")
    graph.add_node("b", type="spaceship", site="s", role="access")

    with pytest.raises(SchemaError, match="invalid attributes"):
        from_networkx(graph)


def test_from_networkx_rejects_malformed_endpoint_attribute() -> None:
    graph = nx.Graph()
    graph.add_node("a", type="router", site="s", role="core")
    graph.add_node("b", type="switch", site="s", role="access")
    graph.add_edge(
        "a",
        "b",
        link_id="l1",
        endpoints="ab",
        capacity_mbps=100.0,
        cost=1.0,
    )

    with pytest.raises(SchemaError, match="exactly two endpoints"):
        from_networkx(graph)
