"""UI-agnostic row helpers for routing results."""

from __future__ import annotations

from network.routing import (
    alternative_paths,
    alternative_rows,
    path_rows,
    reachability_matrix,
    reachability_rows,
    routing_table,
    routing_table_rows,
    shortest_path,
)


def test_path_rows_describe_each_hop(weighted_triangle) -> None:
    rows = path_rows(shortest_path(weighted_triangle, "a", "c"))

    assert rows == [
        {
            "hop": 1,
            "source": "a",
            "target": "b",
            "link_id": "ab",
            "cost": 1.0,
            "note": "",
        },
        {
            "hop": 2,
            "source": "b",
            "target": "c",
            "link_id": "bc",
            "cost": 2.0,
            "note": "",
        },
    ]


def test_path_rows_report_unreachable_and_self_pairs(
    disconnected_graph,
    line_graph,
) -> None:
    unreachable = path_rows(shortest_path(disconnected_graph, "a", "d"))
    self_pair = path_rows(shortest_path(line_graph, "b", "b"))

    assert unreachable[0]["hop"] == 0
    assert "No directed path" in unreachable[0]["note"]
    assert self_pair[0]["note"] == "Source equals destination"


def test_alternative_rows_are_ranked(equal_cost_diamond) -> None:
    rows = alternative_rows(alternative_paths(equal_cost_diamond, "a", "d", k=2))

    assert [row["rank"] for row in rows] == [1, 2]
    assert rows[0]["devices"] == "a -> b -> d"
    assert rows[0]["total_cost"] == 2.0
    assert rows[0]["hop_count"] == 2


def test_routing_table_rows_match_entries(line_graph) -> None:
    rows = routing_table_rows(routing_table(line_graph, "a"))

    assert rows == [
        {
            "destination": "b",
            "next_hop": "b",
            "link_id": "ab",
            "total_cost": 1.0,
            "hop_count": 1,
        },
        {
            "destination": "c",
            "next_hop": "b",
            "link_id": "ab",
            "total_cost": 2.0,
            "hop_count": 2,
        },
        {
            "destination": "d",
            "next_hop": "b",
            "link_id": "ab",
            "total_cost": 3.0,
            "hop_count": 3,
        },
    ]


def test_reachability_rows_have_one_column_per_device(directed_chain) -> None:
    rows = reachability_rows(reachability_matrix(directed_chain))

    assert rows == [
        {"source": "r1", "r1": True, "r2": True, "r3": True},
        {"source": "r2", "r1": False, "r2": True, "r3": True},
        {"source": "r3", "r1": False, "r2": False, "r3": True},
    ]
