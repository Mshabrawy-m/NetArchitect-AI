"""UI-agnostic row helpers for structural analysis."""

from __future__ import annotations

from network.analysis import (
    analyze_topology,
    centrality_rows,
    component_rows,
    critical_link_rows,
    critical_node_rows,
    diameter_rows,
    redundancy,
    redundancy_rows,
    spof_rows,
)


def test_analysis_rows_reflect_the_report(line_graph) -> None:
    report = analyze_topology(line_graph)

    centrality = centrality_rows(report.centrality)
    assert [row["device_id"] for row in centrality] == ["a", "b", "c", "d"]
    assert centrality[1]["degree"] == 2

    assert component_rows(report.components) == [
        {
            "component": 1,
            "device_count": 4,
            "devices": "a, b, c, d",
        }
    ]
    assert diameter_rows(report.diameter) == [
        {"component": 1, "device_count": 4, "diameter_hops": 3}
    ]
    assert [row["device_id"] for row in critical_node_rows(report.critical_nodes)] == [
        "b",
        "c",
    ]
    assert [row["link_id"] for row in critical_link_rows(report.critical_links)] == [
        "ab",
        "bc",
        "cd",
    ]
    assert [row["kind"] for row in spof_rows(report.spof)] == [
        "device",
        "device",
        "link",
        "link",
        "link",
    ]


def test_redundancy_rows_are_label_value_pairs(ring_graph) -> None:
    rows = redundancy_rows(redundancy(ring_graph, "r1", "r3"))

    assert rows == [
        {"metric": "node-disjoint paths", "value": 2},
        {"metric": "edge-disjoint paths", "value": 2},
    ]
