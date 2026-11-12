"""UI-agnostic table rows for routing results."""

from __future__ import annotations

from network.routing.paths import (
    AlternativePaths,
    ReachabilityMatrix,
    RoutePath,
    RoutingTable,
)


def path_rows(path: RoutePath) -> list[dict[str, object]]:
    """Return one row per hop in a path, plus an empty row when unreachable."""
    if not path.reachable:
        return [
            {
                "hop": 0,
                "source": path.source,
                "target": path.destination,
                "link_id": "",
                "cost": 0.0,
                "note": path.reason,
            }
        ]
    if not path.hops:
        return [
            {
                "hop": 0,
                "source": path.source,
                "target": path.destination,
                "link_id": "",
                "cost": 0.0,
                "note": "Source equals destination",
            }
        ]
    return [
        {
            "hop": index,
            "source": hop.source,
            "target": hop.target,
            "link_id": hop.link_id,
            "cost": hop.cost,
            "note": "",
        }
        for index, hop in enumerate(path.hops, start=1)
    ]


def alternative_rows(result: AlternativePaths) -> list[dict[str, object]]:
    """Return one row per alternative path."""
    return [
        {
            "rank": index,
            "reachable": path.reachable,
            "devices": " -> ".join(path.device_ids),
            "hop_count": path.hop_count,
            "total_cost": path.total_cost,
        }
        for index, path in enumerate(result.paths, start=1)
    ]


def routing_table_rows(table: RoutingTable) -> list[dict[str, object]]:
    """Return one row per routing-table destination."""
    return [
        {
            "destination": entry.destination,
            "next_hop": entry.next_hop,
            "link_id": entry.link_id,
            "total_cost": entry.total_cost,
            "hop_count": entry.hop_count,
        }
        for entry in table.entries
    ]


def reachability_rows(matrix: ReachabilityMatrix) -> list[dict[str, object]]:
    """Return one row per source, with one boolean column per destination."""
    rows: list[dict[str, object]] = []
    for source, values in zip(matrix.device_ids, matrix.matrix):
        row: dict[str, object] = {"source": source}
        row.update(
            {
                destination: bool(value)
                for destination, value in zip(matrix.device_ids, values)
            }
        )
        rows.append(row)
    return rows
