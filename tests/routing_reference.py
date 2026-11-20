"""Frozen NetworkX reference for the V2 sparse-routing equivalence tests.

This file keeps the pre-V2 shortest-path, reachability, and component
algorithms verbatim. The production code may change for speed; this module may
not. It is test-only and is never imported by the application.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from itertools import pairwise

import networkx as nx

from core.schemas.network import Topology
from network.routing.graph import build_routing_graph, excluded_ids

NodePath = tuple[str, ...]


def _dijkstra_tree(
    graph: nx.DiGraph,
    source: str,
) -> dict[str, tuple[float, NodePath]]:
    """Return the deterministic shortest path to every reachable node."""
    if source not in graph:
        return {}
    best: dict[str, tuple[float, NodePath]] = {source: (0.0, (source,))}
    heap: list[tuple[float, NodePath, str]] = [(0.0, (source,), source)]
    while heap:
        cost, path, node = heapq.heappop(heap)
        if best.get(node) != (cost, path):
            continue
        for neighbor in sorted(graph[node]):
            attributes = graph[node][neighbor]
            candidate = (
                cost + float(attributes["cost"]),
                path + (neighbor,),
            )
            current = best.get(neighbor)
            if current is None or candidate < current:
                best[neighbor] = candidate
                heapq.heappush(heap, (candidate[0], candidate[1], neighbor))
    return best


def _path_from_nodes(
    graph: nx.DiGraph,
    source: str,
    nodes: NodePath,
) -> dict[str, object]:
    hops: list[dict[str, object]] = []
    for start, end in pairwise(nodes):
        attributes = graph[start][end]
        hops.append(
            {
                "source": start,
                "target": end,
                "link_id": str(attributes["link_id"]),
                "cost": float(attributes["cost"]),
            }
        )
    return {
        "source": source,
        "destination": nodes[-1],
        "reachable": True,
        "device_ids": list(nodes),
        "hops": hops,
        "total_cost": sum(float(hop["cost"]) for hop in hops),
        "hop_count": len(hops),
        "reason": "",
    }


def _unreachable(source: str, destination: str, reason: str) -> dict[str, object]:
    return {
        "source": source,
        "destination": destination,
        "reachable": False,
        "device_ids": [],
        "hops": [],
        "total_cost": 0.0,
        "hop_count": 0,
        "reason": reason,
    }


def _require_device(topology: Topology, device_id: str) -> None:
    if not any(device.id == device_id for device in topology.devices):
        raise ValueError(f"Device {device_id!r} is not present in topology")


def shortest_path(
    topology: Topology,
    source: str,
    destination: str,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> dict[str, object]:
    """Pre-V2 NetworkX shortest path as a plain comparison dictionary."""
    _require_device(topology, source)
    _require_device(topology, destination)
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    if source in failed_device_ids:
        return _unreachable(source, destination, f"Source device {source!r} is failed")
    if destination in failed_device_ids:
        return _unreachable(
            source, destination, f"Destination device {destination!r} is failed"
        )
    if source == destination:
        return {
            "source": source,
            "destination": destination,
            "reachable": True,
            "device_ids": [source],
            "hops": [],
            "total_cost": 0.0,
            "hop_count": 0,
            "reason": "",
        }

    graph = build_routing_graph(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    result = _dijkstra_tree(graph, source).get(destination)
    if result is None:
        return _unreachable(
            source,
            destination,
            "No directed path exists between the selected devices",
        )
    return _path_from_nodes(graph, source, result[1])


def reachability_matrix(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> dict[str, object]:
    """Pre-V2 NetworkX all-pairs reachability comparison dictionary."""
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    device_ids = sorted(
        device.id
        for device in topology.devices
        if device.id not in failed_device_ids
    )
    graph = build_routing_graph(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    matrix: list[list[bool]] = []
    unreachable = 0
    for source in device_ids:
        reachable = {source}
        reachable.update(_dijkstra_tree(graph, source))
        row = [destination in reachable for destination in device_ids]
        unreachable += sum(
            1
            for destination, value in zip(device_ids, row)
            if destination != source and not value
        )
        matrix.append(row)
    return {
        "device_ids": device_ids,
        "matrix": matrix,
        "unreachable_pairs": unreachable,
        "excluded_device_ids": sorted(failed_device_ids),
    }


def component_summary(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> dict[str, object]:
    """Pre-V2 NetworkX weak/strong component comparison dictionary."""
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    graph = build_routing_graph(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    weak = [sorted(component) for component in nx.weakly_connected_components(graph)]
    strong = [
        sorted(component) for component in nx.strongly_connected_components(graph)
    ]
    weak.sort(key=lambda component: component[0] if component else "")
    strong.sort(key=lambda component: component[0] if component else "")
    isolated = sorted(node for node, degree in graph.degree() if degree == 0)
    return {
        "weak_components": weak,
        "strong_components": strong,
        "is_weakly_connected": graph.number_of_nodes() > 0 and len(weak) == 1,
        "is_strongly_connected": graph.number_of_nodes() > 0 and len(strong) == 1,
        "isolated_device_ids": isolated,
    }
