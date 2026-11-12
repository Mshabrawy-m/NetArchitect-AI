"""Hand-computed structural metrics, critical entities, and bounds."""

from __future__ import annotations

import pytest

from core.exceptions import DeviceNotFoundError, LimitsExceededError
from network.analysis import (
    METRIC_DEFINITIONS,
    analyze_topology,
    centrality_metrics,
    component_analysis,
    critical_links,
    critical_nodes,
    diameter_analysis,
)

from .helpers import build_topology, make_link


def test_line_degree_and_betweenness_centrality(line_graph) -> None:
    report = centrality_metrics(line_graph)
    metrics = {metric.device_id: metric for metric in report.metrics}

    # Degrees are 1, 2, 2, 1 out of three other devices.
    assert [metrics[key].degree for key in ["a", "b", "c", "d"]] == [1, 2, 2, 1]
    assert metrics["a"].degree_centrality == pytest.approx(1 / 3)
    assert metrics["b"].degree_centrality == pytest.approx(2 / 3)

    # b lies on a-c, a-d, c-a, and d-a: raw 4, normalized 4 * 1/6 = 2/3.
    assert metrics["a"].betweenness_centrality == pytest.approx(0.0)
    assert metrics["b"].betweenness_centrality == pytest.approx(2 / 3)
    assert metrics["c"].betweenness_centrality == pytest.approx(2 / 3)
    assert metrics["d"].betweenness_centrality == pytest.approx(0.0)


def test_betweenness_uses_link_cost_as_distance() -> None:
    # Hop-wise, a-c is one direct link, so b would have zero betweenness.
    # Weighted by cost, the cheapest a-c route is a-b-c (1 + 2 = 3) rather
    # than the direct link (4), so b sits on every shortest a-c route.
    topology = build_topology(
        "Weighted triangle",
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bc", "b", "c", cost=2.0),
            make_link("ac", "a", "c", cost=4.0),
        ],
    )

    metrics = {
        metric.device_id: metric for metric in centrality_metrics(topology).metrics
    }

    assert metrics["b"].betweenness_centrality == pytest.approx(1.0)
    assert metrics["a"].betweenness_centrality == pytest.approx(0.0)
    assert metrics["c"].betweenness_centrality == pytest.approx(0.0)


def test_parallel_links_count_once_for_degree() -> None:
    topology = build_topology(
        "Parallel",
        ["a", "b", "c"],
        [
            make_link("ab-1", "a", "b"),
            make_link("ab-2", "a", "b"),
        ],
    )

    metrics = {
        metric.device_id: metric for metric in centrality_metrics(topology).metrics
    }

    assert metrics["a"].degree == 1
    assert metrics["b"].degree == 1
    assert metrics["a"].degree_centrality == pytest.approx(0.5)
    assert metrics["c"].degree_centrality == pytest.approx(0.0)


def test_directed_links_are_undirected_in_the_structural_projection(
    directed_chain,
) -> None:
    components = component_analysis(directed_chain)

    assert components.components == [["r1", "r2", "r3"]]
    assert components.is_connected is True


def test_disconnected_components_and_isolated_device(disconnected_graph) -> None:
    report = component_analysis(disconnected_graph)

    assert report.components == [["a", "b"], ["c", "d"], ["e"]]
    assert report.component_count == 3
    assert report.largest_component_size == 2
    assert report.is_connected is False
    assert report.isolated_device_ids == ["e"]


def test_connected_line_diameter_is_three_hops(line_graph) -> None:
    report = diameter_analysis(line_graph)

    assert report.overall_diameter == 3
    assert [(item.device_ids, item.diameter) for item in report.per_component] == [
        (["a", "b", "c", "d"], 3)
    ]


def test_disconnected_diameter_is_per_component_with_no_overall_value(
    disconnected_graph,
) -> None:
    report = diameter_analysis(disconnected_graph)

    assert report.overall_diameter is None
    assert [(len(item.device_ids), item.diameter) for item in report.per_component] == [
        (2, 1),
        (2, 1),
        (1, 0),
    ]


def test_line_middle_devices_are_articulation_points(line_graph) -> None:
    report = critical_nodes(line_graph)

    assert [node.device_id for node in report.nodes] == ["b", "c"]
    # Removing b leaves {a} and {c, d}; a loses its only neighbour.
    assert report.nodes[0].components_after_removal == 2
    assert report.nodes[0].isolated_device_ids == ["a"]
    # Removing c leaves {a, b} and {d}.
    assert report.nodes[1].components_after_removal == 2
    assert report.nodes[1].isolated_device_ids == ["d"]


def test_star_hub_is_the_only_articulation_point(star_graph) -> None:
    report = critical_nodes(star_graph)

    assert [node.device_id for node in report.nodes] == ["h"]
    assert report.nodes[0].components_after_removal == 3
    assert report.nodes[0].isolated_device_ids == ["s1", "s2", "s3"]


def test_ring_has_no_articulation_points_or_bridges(ring_graph) -> None:
    assert critical_nodes(ring_graph).nodes == []
    assert critical_links(ring_graph).links == []


def test_line_every_link_is_a_bridge(line_graph) -> None:
    report = critical_links(line_graph)

    assert [link.link_id for link in report.links] == ["ab", "bc", "cd"]
    assert all(link.components_after_removal == 2 for link in report.links)
    # Removing ab isolates a; removing cd isolates d.
    assert report.links[0].isolated_device_ids == ["a"]
    assert report.links[2].isolated_device_ids == ["d"]


def test_parallel_links_are_not_reported_as_a_single_link_spof() -> None:
    topology = build_topology(
        "Parallel pair",
        ["a", "b", "c"],
        [
            make_link("ab-1", "a", "b"),
            make_link("ab-2", "a", "b"),
            make_link("bc", "b", "c"),
        ],
    )

    report = critical_links(topology)

    # a-b survives losing one of its two links; b-c is still a bridge.
    assert [link.link_id for link in report.links] == ["bc"]


def test_failures_are_applied_before_analysis(line_graph) -> None:
    report = critical_links(line_graph, failed_links=["bc"])
    components = component_analysis(line_graph, failed_links=["bc"])

    assert components.components == [["a", "b"], ["c", "d"]]
    assert [link.link_id for link in report.links] == ["ab", "cd"]


def test_unknown_failure_id_raises_typed_error(line_graph) -> None:
    with pytest.raises(DeviceNotFoundError):
        component_analysis(line_graph, failed_devices=["ghost"])


def test_empty_topology_has_no_metrics() -> None:
    topology = build_topology("Empty", [], [])

    report = analyze_topology(topology)

    assert report.centrality.metrics == []
    assert report.components.component_count == 0
    assert report.components.is_connected is False
    assert report.diameter.overall_diameter is None
    assert report.spof.entries == []
    assert report.findings == []


def test_single_device_topology_is_connected_with_zero_diameter() -> None:
    topology = build_topology("Single", ["only"], [])

    report = analyze_topology(topology)

    assert report.components.is_connected is True
    assert report.diameter.overall_diameter == 0
    assert report.critical_nodes.nodes == []
    assert report.spof.entries == []


def test_analysis_is_bounded_by_max_nodes(monkeypatch, line_graph) -> None:
    monkeypatch.setattr("network.analysis.graph.MAX_NODES", 3)

    with pytest.raises(LimitsExceededError):
        component_analysis(line_graph)


def test_metric_definitions_cover_every_exported_metric() -> None:
    assert set(METRIC_DEFINITIONS) == {
        "degree_centrality",
        "betweenness_centrality",
        "connected_components",
        "diameter",
        "articulation_point",
        "bridge",
        "node_disjoint_paths",
        "edge_disjoint_paths",
        "spof",
    }
    assert all(definition.strip() for definition in METRIC_DEFINITIONS.values())
