"""Deterministic shortest paths, alternatives, tables, and reachability.

Path semantics
--------------
* ``Link.cost`` is the edge weight; ``capacity_mbps`` is not used for path
  selection. Direction follows :mod:`network.routing.graph`.
* Ties are resolved by the lexicographically smallest device-id sequence. In
  practice this means the lowest next-hop id wins first, then the lowest id at
  the following hop, and so on. The rule is deterministic across runs and
  platforms.
* A source equal to its destination is reachable with an empty path (cost 0,
  hop count 0).
* An unreachable pair is a typed result (``reachable=False``), not an
  exception. Unknown device ids and unknown failure ids still raise typed
  not-found errors because they indicate a caller mistake.

Alternative-path enumeration uses Yen's algorithm over the simple routing
graph. Parallel links have already collapsed to the cheapest link, so
alternatives are distinct device sequences. ``k`` is bounded by
``config.limits.MAX_ALTERNATIVE_PATHS``.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable
from itertools import pairwise

import networkx as nx
import numpy as np
from pydantic import BaseModel, Field

from config.limits import MAX_ALTERNATIVE_PATHS, MAX_ECMP_PATHS
from core.exceptions import DeviceNotFoundError, LimitsExceededError
from core.schemas.network import Topology

from .graph import build_routing_graph, excluded_ids
from .sparse import SparseRouter

NodePath = tuple[str, ...]


class RouteHop(BaseModel):
    """One traversed link in a path."""

    source: str
    target: str
    link_id: str
    cost: float


class RoutePath(BaseModel):
    """A shortest or alternative path between two devices."""

    source: str
    destination: str
    reachable: bool
    device_ids: list[str] = Field(default_factory=list)
    hops: list[RouteHop] = Field(default_factory=list)
    total_cost: float = Field(default=0.0, ge=0.0)
    hop_count: int = Field(default=0, ge=0)
    reason: str = ""


class AlternativePaths(BaseModel):
    """Bounded k-shortest simple paths for one pair."""

    source: str
    destination: str
    requested_k: int = Field(ge=1)
    paths: list[RoutePath] = Field(default_factory=list)
    reason: str = ""


class RoutingTableEntry(BaseModel):
    """One destination reachable from the table's source device."""

    destination: str
    next_hop: str
    link_id: str
    total_cost: float = Field(ge=0.0)
    hop_count: int = Field(ge=1)


class RoutingTable(BaseModel):
    """Routing table for one source device.

    Entries exclude the source itself and include only reachable destinations.
    """

    source: str
    entries: list[RoutingTableEntry] = Field(default_factory=list)
    reason: str = ""


class ReachabilityMatrix(BaseModel):
    """Directed reachability matrix over the surviving devices.

    Row ``i`` is the source ``device_ids[i]``; column ``j`` is the destination.
    The diagonal is always true. ``unreachable_pairs`` counts ordered pairs
    with distinct source and destination that cannot reach each other.
    """

    device_ids: list[str] = Field(default_factory=list)
    matrix: list[list[bool]] = Field(default_factory=list)
    unreachable_pairs: int = Field(default=0, ge=0)
    excluded_device_ids: list[str] = Field(default_factory=list)


class ComponentSummary(BaseModel):
    """Weak and strong routing components after failures are applied."""

    weak_components: list[list[str]] = Field(default_factory=list)
    strong_components: list[list[str]] = Field(default_factory=list)
    is_weakly_connected: bool = False
    is_strongly_connected: bool = False
    isolated_device_ids: list[str] = Field(default_factory=list)


def _require_device(topology: Topology, device_id: str) -> None:
    if not any(device.id == device_id for device in topology.devices):
        raise DeviceNotFoundError(
            f"Device {device_id!r} is not present in topology {topology.name!r}"
        )


def _unreachable(source: str, destination: str, reason: str) -> RoutePath:
    return RoutePath(
        source=source,
        destination=destination,
        reachable=False,
        reason=reason,
    )


def _path_from_nodes(graph: nx.DiGraph, source: str, nodes: NodePath) -> RoutePath:
    hops: list[RouteHop] = []
    for start, end in pairwise(nodes):
        attributes = graph[start][end]
        hops.append(
            RouteHop(
                source=start,
                target=end,
                link_id=str(attributes["link_id"]),
                cost=float(attributes["cost"]),
            )
        )
    total_cost = sum(hop.cost for hop in hops)
    return RoutePath(
        source=source,
        destination=nodes[-1],
        reachable=True,
        device_ids=list(nodes),
        hops=hops,
        total_cost=total_cost,
        hop_count=len(hops),
    )


def _path_from_sparse(
    source: str,
    destination: str,
    result: tuple[
        tuple[str, ...], tuple[tuple[str, str, str, float], ...], float
    ]
    | None,
) -> RoutePath:
    """Wrap a sparse path result in the public typed model."""
    if result is None:
        return _unreachable(
            source,
            destination,
            "No directed path exists between the selected devices",
        )
    nodes, hops, total_cost = result
    return RoutePath(
        source=source,
        destination=destination,
        reachable=True,
        device_ids=list(nodes),
        hops=[
            RouteHop(
                source=source_id,
                target=target_id,
                link_id=link_id,
                cost=cost,
            )
            for source_id, target_id, link_id, cost in hops
        ],
        total_cost=total_cost,
        hop_count=len(hops),
    )


def shortest_path_from_router(
    router: SparseRouter,
    source: str,
    destination: str,
) -> RoutePath:
    """Route one pair using a precomputed sparse router.

    The caller is responsible for endpoint validation and failed-endpoint
    messages; this helper only converts the sparse result to the public type.
    """
    if source not in router.node_ids:
        return _unreachable(source, destination, f"Source device {source!r} is failed")
    if destination not in router.node_ids:
        return _unreachable(
            source, destination, f"Destination device {destination!r} is failed"
        )
    if source == destination:
        return RoutePath(
            source=source,
            destination=destination,
            reachable=True,
            device_ids=[source],
        )
    return _path_from_sparse(source, destination, router.path(source, destination))


def equal_cost_paths_from_router(
    router: SparseRouter,
    source: str,
    destination: str,
    *,
    limit: int = MAX_ECMP_PATHS,
) -> tuple[list[RoutePath], bool]:
    """Return the lexicographically first equal-cost paths and a truncation flag.

    This function reuses the same sparse arrays and deterministic arc order as
    :func:`shortest_path_from_router`. Every returned path has the same total
    cost as the single shortest path, with equal-cost ties resolved by the
    lexicographically smallest device sequence. Simple paths only: a visited
    node is never revisited, so zero-cost cycles cannot produce infinite paths.

    At most ``limit`` paths are returned (bounded by ``MAX_ECMP_PATHS``). The
    boolean is ``True`` when at least one additional equal-cost path exists;
    callers must surface that truncation instead of silently splitting across a
    subset. Failed or unknown endpoints return no paths.
    """
    if limit < 1:
        raise ValueError(f"ECMP path limit must be positive, got {limit}")
    if source not in router.node_ids or destination not in router.node_ids:
        return [], False
    if source == destination:
        return [
            RoutePath(
                source=source,
                destination=destination,
                reachable=True,
                device_ids=[source],
            )
        ], False

    distances = router.forward_distances
    target_index = router.node_ids.index(destination)
    start_index = router.node_ids.index(source)
    if not math.isfinite(float(distances[start_index, target_index])):
        return [], False

    results: list[RoutePath] = []
    found_extra = False

    def visit(
        current_index: int,
        nodes: tuple[str, ...],
        hops: tuple[RouteHop, ...],
        total_cost: float,
        visited: frozenset[int],
    ) -> None:
        nonlocal found_extra
        if found_extra:
            return
        if current_index == target_index:
            if len(results) < limit:
                results.append(
                    RoutePath(
                        source=source,
                        destination=destination,
                        reachable=True,
                        device_ids=list(nodes),
                        hops=list(hops),
                        total_cost=float(total_cost),
                        hop_count=len(hops),
                    )
                )
            else:
                found_extra = True
            return

        budget = float(distances[current_index, target_index])
        if not math.isfinite(budget):
            return
        for position in range(
            router.indptr[current_index], router.indptr[current_index + 1]
        ):
            neighbor = int(router.indices[position])
            cost = float(router.costs[position])
            remaining = float(distances[neighbor, target_index])
            if not math.isfinite(remaining) or cost + remaining != budget:
                continue
            if neighbor in visited:
                continue
            visit(
                neighbor,
                (*nodes, router.node_ids[neighbor]),
                (
                    *hops,
                    RouteHop(
                        source=router.node_ids[current_index],
                        target=router.node_ids[neighbor],
                        link_id=router.link_ids[position],
                        cost=cost,
                    ),
                ),
                total_cost + cost,
                visited | {neighbor},
            )
            if found_extra:
                return

    visit(start_index, (source,), (), 0.0, frozenset({start_index}))
    return results, found_extra


def component_summary_from_router(router: SparseRouter) -> ComponentSummary:
    """Summarize weak/strong components from precomputed sparse arrays."""
    weak, strong, isolated = router.components()
    weak_list = [list(component) for component in weak]
    strong_list = [list(component) for component in strong]
    return ComponentSummary(
        weak_components=weak_list,
        strong_components=strong_list,
        is_weakly_connected=router.size > 0 and len(weak_list) == 1,
        is_strongly_connected=router.size > 0 and len(strong_list) == 1,
        isolated_device_ids=list(isolated),
    )


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


def shortest_path(
    topology: Topology,
    source: str,
    destination: str,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> RoutePath:
    """Return the lowest-cost directed path from ``source`` to ``destination``.

    Capacity is ignored; cost is the only weight. Failed endpoints produce an
    unreachable result. See the module docstring for tie-breaking.
    """
    _require_device(topology, source)
    _require_device(topology, destination)
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    if source in failed_device_ids:
        return _unreachable(
            source, destination, f"Source device {source!r} is failed"
        )
    if destination in failed_device_ids:
        return _unreachable(
            source, destination, f"Destination device {destination!r} is failed"
        )
    if source == destination:
        return RoutePath(
            source=source,
            destination=destination,
            reachable=True,
            device_ids=[source],
        )

    router = SparseRouter.from_topology(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    return shortest_path_from_router(router, source, destination)


def _dijkstra_single(
    graph: nx.DiGraph,
    source: str,
    target: str,
    *,
    banned_nodes: set[str],
    banned_edges: set[tuple[str, str]],
) -> tuple[float, NodePath] | None:
    """Deterministic shortest path with nodes and directed edges banned."""
    if source in banned_nodes or target in banned_nodes:
        return None
    best: dict[str, tuple[float, NodePath]] = {source: (0.0, (source,))}
    heap: list[tuple[float, NodePath, str]] = [(0.0, (source,), source)]
    while heap:
        cost, path, node = heapq.heappop(heap)
        if best.get(node) != (cost, path):
            continue
        if node == target:
            return cost, path
        for neighbor in sorted(graph[node]):
            if neighbor in banned_nodes or (node, neighbor) in banned_edges:
                continue
            attributes = graph[node][neighbor]
            candidate = (cost + float(attributes["cost"]), path + (neighbor,))
            current = best.get(neighbor)
            if current is None or candidate < current:
                best[neighbor] = candidate
                heapq.heappush(heap, (candidate[0], candidate[1], neighbor))
    return None


def _k_shortest_paths(
    graph: nx.DiGraph,
    source: str,
    target: str,
    k: int,
) -> list[tuple[float, NodePath]]:
    """Enumerate up to ``k`` simple paths in deterministic cost/path order."""
    if source not in graph or target not in graph:
        return []
    if source == target:
        return [(0.0, (source,))]

    first = _dijkstra_single(
        graph,
        source,
        target,
        banned_nodes=set(),
        banned_edges=set(),
    )
    if first is None:
        return []

    accepted: list[tuple[float, NodePath]] = [first]
    candidates: list[tuple[float, NodePath]] = []
    while len(accepted) < k:
        _, previous = accepted[-1]
        for spur_index in range(len(previous) - 1):
            spur_node = previous[spur_index]
            root = previous[: spur_index + 1]
            banned_nodes = set(root[:-1])
            banned_edges = {
                (path[spur_index], path[spur_index + 1])
                for _, path in accepted
                if len(path) > spur_index + 1
                and path[: spur_index + 1] == root
            }
            spur = _dijkstra_single(
                graph,
                spur_node,
                target,
                banned_nodes=banned_nodes,
                banned_edges=banned_edges,
            )
            if spur is None:
                continue
            total_path = root[:-1] + spur[1]
            total_cost = sum(
                float(graph[start][end]["cost"])
                for start, end in pairwise(total_path)
            )
            if any(path == total_path for _, path in accepted):
                continue
            if any(path == total_path for _, path in candidates):
                continue
            heapq.heappush(candidates, (total_cost, total_path))

        if not candidates:
            break
        next_cost, next_path = heapq.heappop(candidates)
        if any(path == next_path for _, path in accepted):
            continue
        accepted.append((next_cost, next_path))
    return accepted


def alternative_paths(
    topology: Topology,
    source: str,
    destination: str,
    *,
    k: int = 3,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> AlternativePaths:
    """Return up to ``k`` simple paths ordered by cost, then device sequence.

    ``k`` is bounded by ``MAX_ALTERNATIVE_PATHS``. The first returned path is
    the same deterministic shortest path as :func:`shortest_path`.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if k > MAX_ALTERNATIVE_PATHS:
        raise LimitsExceededError(
            f"Requested {k} alternative paths; the limit is "
            f"{MAX_ALTERNATIVE_PATHS}"
        )
    _require_device(topology, source)
    _require_device(topology, destination)
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    if source in failed_device_ids or destination in failed_device_ids:
        return AlternativePaths(
            source=source,
            destination=destination,
            requested_k=k,
            reason="A selected endpoint is failed",
        )
    if source == destination:
        return AlternativePaths(
            source=source,
            destination=destination,
            requested_k=k,
            paths=[
                RoutePath(
                    source=source,
                    destination=destination,
                    reachable=True,
                    device_ids=[source],
                )
            ],
        )

    graph = build_routing_graph(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    paths = _k_shortest_paths(graph, source, destination, k)
    return AlternativePaths(
        source=source,
        destination=destination,
        requested_k=k,
        paths=[
            _path_from_nodes(graph, source, path)
            for _, path in paths
        ],
        reason="" if paths else "No directed path exists between the selected devices",
    )


def routing_table(
    topology: Topology,
    source: str,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> RoutingTable:
    """Build the deterministic routing table for ``source``.

    Each reachable destination gets the first hop of its lowest-cost path,
    the link id, total cost, and hop count. Equal-cost paths are resolved by
    the lexicographically smallest device sequence (lowest next hop first).
    A failed source returns an empty table with a reason.
    """
    _require_device(topology, source)
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    if source in failed_device_ids:
        return RoutingTable(
            source=source,
            reason=f"Source device {source!r} is failed",
        )
    graph = build_routing_graph(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    tree = _dijkstra_tree(graph, source)
    entries: list[RoutingTableEntry] = []
    for destination in sorted(tree):
        if destination == source:
            continue
        cost, path = tree[destination]
        first_hop = path[1]
        entries.append(
            RoutingTableEntry(
                destination=destination,
                next_hop=first_hop,
                link_id=str(graph[source][first_hop]["link_id"]),
                total_cost=cost,
                hop_count=len(path) - 1,
            )
        )
    return RoutingTable(source=source, entries=entries)


def reachability_matrix(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> ReachabilityMatrix:
    """Return the directed all-pairs reachability matrix.

    Failed devices are omitted from the matrix and listed separately. One
    deterministic Dijkstra search runs per surviving device, so the work is
    bounded by ``MAX_NODES`` sources.
    """
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
    router = SparseRouter.from_topology(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    distances = router.distances_from()
    finite = np.isfinite(distances)
    matrix = [[bool(finite[row, column]) for column in range(len(device_ids))] for row in range(len(device_ids))]
    unreachable = sum(
        1
        for row in range(len(device_ids))
        for column in range(len(device_ids))
        if row != column and not matrix[row][column]
    )
    return ReachabilityMatrix(
        device_ids=device_ids,
        matrix=matrix,
        unreachable_pairs=unreachable,
        excluded_device_ids=sorted(failed_device_ids),
    )


def component_summary(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> ComponentSummary:
    """Summarize weak and strong components of the routing graph.

    Weak components ignore link direction; strong components require mutual
    directed reachability. Components are sorted by their first device id.
    """
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    router = SparseRouter.from_topology(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    return component_summary_from_router(router)
