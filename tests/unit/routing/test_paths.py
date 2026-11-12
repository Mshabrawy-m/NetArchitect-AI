"""Hand-computed shortest paths, tables, reachability, and components."""

from __future__ import annotations

from itertools import pairwise

import pytest

from network.routing import (
    alternative_paths,
    build_routing_graph,
    component_summary,
    reachability_matrix,
    routing_table,
    shortest_path,
)


def test_weighted_triangle_prefers_cheaper_indirect_path(weighted_triangle) -> None:
    # a-b-c = 1 + 2 = 3; direct a-c = 4, so the two-hop path wins.
    path = shortest_path(weighted_triangle, "a", "c")

    assert path.reachable is True
    assert path.device_ids == ["a", "b", "c"]
    assert path.total_cost == pytest.approx(3.0)
    assert path.hop_count == 2
    assert [(hop.source, hop.target) for hop in path.hops] == [
        ("a", "b"),
        ("b", "c"),
    ]


def test_source_equals_destination_is_empty_reachable_path(line_graph) -> None:
    path = shortest_path(line_graph, "b", "b")

    assert path.reachable is True
    assert path.device_ids == ["b"]
    assert path.hops == []
    assert path.total_cost == 0.0
    assert path.hop_count == 0


def test_disconnected_pair_is_unreachable_not_an_exception(disconnected_graph) -> None:
    path = shortest_path(disconnected_graph, "a", "d")

    assert path.reachable is False
    assert path.device_ids == []
    assert "No directed path" in path.reason


def test_equal_cost_tie_break_uses_lowest_device_sequence(
    equal_cost_diamond,
) -> None:
    # Both a-b-d and a-c-d cost 2; a-b-d is lexicographically smaller.
    path = shortest_path(equal_cost_diamond, "a", "d")

    assert path.device_ids == ["a", "b", "d"]

    table = routing_table(equal_cost_diamond, "a")
    entry = next(item for item in table.entries if item.destination == "d")
    assert entry.next_hop == "b"
    assert entry.total_cost == pytest.approx(2.0)
    assert entry.hop_count == 2


def test_alternatives_are_ordered_by_cost_then_sequence(equal_cost_diamond) -> None:
    result = alternative_paths(equal_cost_diamond, "a", "d", k=2)

    assert result.requested_k == 2
    assert [path.device_ids for path in result.paths] == [
        ["a", "b", "d"],
        ["a", "c", "d"],
    ]
    assert [path.total_cost for path in result.paths] == [2.0, 2.0]


def test_ring_opposite_nodes_have_two_equal_cost_alternatives(ring_graph) -> None:
    # r1-r2-r3 and r1-r4-r3 both cost 2; the former sorts first.
    result = alternative_paths(ring_graph, "r1", "r3", k=2)

    assert [path.device_ids for path in result.paths] == [
        ["r1", "r2", "r3"],
        ["r1", "r4", "r3"],
    ]
    assert all(path.total_cost == pytest.approx(2.0) for path in result.paths)


def test_alternatives_are_capped_at_the_available_simple_paths(line_graph) -> None:
    # Only one simple path exists between the two ends of a line.
    result = alternative_paths(line_graph, "a", "d", k=5)

    assert [path.device_ids for path in result.paths] == [["a", "b", "c", "d"]]


def test_routing_table_line_next_hop_is_the_only_neighbor(line_graph) -> None:
    table = routing_table(line_graph, "a")

    assert [entry.destination for entry in table.entries] == ["b", "c", "d"]
    assert {entry.next_hop for entry in table.entries} == {"b"}
    assert [(entry.total_cost, entry.hop_count) for entry in table.entries] == [
        (1.0, 1),
        (2.0, 2),
        (3.0, 3),
    ]
    assert {entry.link_id for entry in table.entries} == {"ab"}


def test_routing_table_excludes_the_source(line_graph) -> None:
    table = routing_table(line_graph, "c")

    assert "c" not in {entry.destination for entry in table.entries}


def test_reachability_matrix_honors_directed_links(directed_chain) -> None:
    # r1 -> r2 -> r3 only. Unreachable ordered pairs: (r2, r1), (r3, r1),
    # (r3, r2) = 3.
    matrix = reachability_matrix(directed_chain)

    assert matrix.device_ids == ["r1", "r2", "r3"]
    assert matrix.matrix == [
        [True, True, True],
        [False, True, True],
        [False, False, True],
    ]
    assert matrix.unreachable_pairs == 3
    assert matrix.excluded_device_ids == []


def test_reachability_matrix_counts_cross_component_pairs(
    disconnected_graph,
) -> None:
    # Four ordered pairs in each direction across the two components: 8.
    matrix = reachability_matrix(disconnected_graph)

    assert matrix.device_ids == ["a", "b", "c", "d"]
    assert matrix.unreachable_pairs == 8
    assert all(matrix.matrix[i][i] for i in range(4))


def test_component_summary_distinguishes_weak_and_strong(directed_chain) -> None:
    summary = component_summary(directed_chain)

    assert summary.weak_components == [["r1", "r2", "r3"]]
    assert summary.strong_components == [["r1"], ["r2"], ["r3"]]
    assert summary.is_weakly_connected is True
    assert summary.is_strongly_connected is False


def test_component_summary_lists_separate_components(disconnected_graph) -> None:
    summary = component_summary(disconnected_graph)

    assert summary.weak_components == [["a", "b"], ["c", "d"]]
    assert summary.strong_components == [["a", "b"], ["c", "d"]]
    assert summary.is_weakly_connected is False
    assert summary.is_strongly_connected is False


@pytest.mark.parametrize(
    "fixture_name",
    [
        "weighted_triangle",
        "unequal_diamond",
        "equal_cost_diamond",
        "line_graph",
        "ring_graph",
        "star_graph",
        "directed_chain",
    ],
)
def test_every_returned_path_is_a_valid_walk_with_matching_cost(
    fixture_name: str,
    request: pytest.FixtureRequest,
) -> None:
    topology = request.getfixturevalue(fixture_name)
    graph = build_routing_graph(topology)

    for source in graph.nodes:
        for destination in graph.nodes:
            path = shortest_path(topology, source, destination)
            if not path.reachable:
                continue
            assert path.device_ids[0] == source
            assert path.device_ids[-1] == destination
            assert len(path.hops) == len(path.device_ids) - 1
            for hop in path.hops:
                assert graph.has_edge(hop.source, hop.target)
                assert graph[hop.source][hop.target]["link_id"] == hop.link_id
            walked = sum(
                float(graph[start][end]["cost"])
                for start, end in pairwise(path.device_ids)
            )
            assert path.total_cost == pytest.approx(walked)
            assert path.hop_count == len(path.hops)
