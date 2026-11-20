"""Sparse adjacency arrays for deterministic routing hot paths.

The arrays built here mirror :func:`network.routing.graph.build_routing_graph`:
directed links contribute one arc, undirected links two, and parallel arcs
collapse to the lowest ``(cost, link_id)``. Distances and reachability use
:mod:`scipy.sparse.csgraph`. Path extraction stays deterministic: at every hop
the lowest device id that still lies on a shortest path to the destination wins,
which is exactly the lexicographic tie-break of the original NetworkX Dijkstra
implementation.

This module deliberately returns plain tuples, not Pydantic models, so
``network.routing.paths`` remains the only public wrapper.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from core.exceptions import LimitsExceededError
from core.schemas.network import Topology

from . import graph
from .graph import excluded_ids


@dataclass(frozen=True)
class SparseRouter:
    """Immutable adjacency arrays for one topology and failure state."""

    node_ids: tuple[str, ...]
    indptr: np.ndarray
    indices: np.ndarray
    costs: np.ndarray
    link_ids: tuple[str, ...]
    matrix: csr_matrix
    reverse: csr_matrix
    reverse_link_ids: tuple[str, ...]

    @classmethod
    def from_topology(
        cls,
        topology: Topology,
        *,
        failed_devices: Iterable[str] = (),
        failed_links: Iterable[str] = (),
    ) -> SparseRouter:
        """Build arrays with the same validation and arc rules as the old graph."""
        if len(topology.devices) > graph.MAX_NODES:
            raise LimitsExceededError(
                f"Routing analysis received {len(topology.devices)} devices; "
                f"the limit is {graph.MAX_NODES}"
            )
        failed_device_ids, failed_link_ids = excluded_ids(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
        node_ids = tuple(
            sorted(
                device.id
                for device in topology.devices
                if device.id not in failed_device_ids
            )
        )
        index = {device_id: position for position, device_id in enumerate(node_ids)}

        # Keep the cheapest arc for each ordered pair; ties go to the lowest id.
        best_arcs: dict[tuple[str, str], tuple[float, str]] = {}
        for link in topology.links:
            if link.id in failed_link_ids:
                continue
            source, target = link.endpoints
            if source in failed_device_ids or target in failed_device_ids:
                continue
            candidate = (float(link.cost), str(link.id))
            directions = [(source, target)]
            if not link.directed:
                directions.append((target, source))
            for start, end in directions:
                current = best_arcs.get((start, end))
                if current is None or candidate < current:
                    best_arcs[(start, end)] = candidate

        forward_rows: list[list[tuple[int, float, str]]] = [[] for _ in node_ids]
        reverse_rows: list[list[tuple[int, float, str]]] = [[] for _ in node_ids]
        for (source, target), (cost, link_id) in best_arcs.items():
            row, column = index[source], index[target]
            forward_rows[row].append((column, cost, link_id))
            reverse_rows[column].append((row, cost, link_id))

        indptr, indices, costs, link_ids = _pack_rows(forward_rows)
        reverse_indptr, reverse_indices, reverse_costs, reverse_link_ids = _pack_rows(
            reverse_rows
        )
        size = len(node_ids)
        matrix = csr_matrix((costs, indices, indptr), shape=(size, size))
        reverse = csr_matrix(
            (reverse_costs, reverse_indices, reverse_indptr),
            shape=(size, size),
        )
        return cls(
            node_ids=node_ids,
            indptr=indptr,
            indices=indices,
            costs=costs,
            link_ids=tuple(link_ids),
            matrix=matrix,
            reverse=reverse,
            reverse_link_ids=tuple(reverse_link_ids),
        )

    @property
    def size(self) -> int:
        return len(self.node_ids)

    def distances_from(
        self, source: int | None = None
    ) -> np.ndarray:
        """Return shortest distances from ``source`` (or every node)."""
        if self.size == 0:
            return np.empty((0, 0) if source is None else 0, dtype=float)
        return dijkstra(
            self.matrix,
            directed=True,
            indices=source,
            return_predecessors=False,
        )

    @cached_property
    def forward_distances(self) -> np.ndarray:
        """Return the full forward distance matrix, computed once per router.

        Path extraction needs the suffix cost from each candidate neighbor in
        the same left-to-right float order used by the original Dijkstra tree.
        A row computed from that neighbor as source provides exactly that; a
        reverse-graph search does not, because float addition is not
        associative.
        """
        return self.distances_from()

    def distances_to(self, target: int) -> np.ndarray:
        """Return every node's shortest distance ``to`` ``target``."""
        if self.size == 0:
            return np.empty(0, dtype=float)
        return dijkstra(
            self.reverse,
            directed=True,
            indices=target,
            return_predecessors=False,
        )

    def path(
        self, source: str, destination: str
    ) -> tuple[tuple[str, ...], tuple[tuple[str, str, str, float], ...], float] | None:
        """Return the deterministic shortest path as plain tuples.

        The result is ``(device_ids, hops, total_cost)`` where each hop is
        ``(source, target, link_id, cost)``. ``None`` means unreachable.
        """
        if source not in self.node_ids or destination not in self.node_ids:
            return None
        source_index = self.node_ids.index(source)
        target_index = self.node_ids.index(destination)
        if source_index == target_index:
            return (source,), (), 0.0

        distances = self.forward_distances
        nodes = [source]
        hops: list[tuple[str, str, str, float]] = []
        total = 0.0
        current = source_index
        visited = {current}
        while current != target_index:
            limit = float(distances[current, target_index])
            if not math.isfinite(limit):
                return None
            chosen: tuple[int, float, str] | None = None
            for position in range(self.indptr[current], self.indptr[current + 1]):
                neighbor = int(self.indices[position])
                cost = float(self.costs[position])
                remaining = float(distances[neighbor, target_index])
                if not math.isfinite(remaining):
                    continue
                if _on_shortest_path(cost, remaining, limit):
                    chosen = (neighbor, cost, self.link_ids[position])
                    break
            if chosen is None or chosen[0] in visited:
                return None
            neighbor, cost, link_id = chosen
            hops.append((self.node_ids[current], self.node_ids[neighbor], link_id, cost))
            total += cost
            current = neighbor
            visited.add(current)
            nodes.append(self.node_ids[current])
        return tuple(nodes), tuple(hops), total

    def components(
        self,
    ) -> tuple[
        tuple[tuple[str, ...], ...],
        tuple[tuple[str, ...], ...],
        tuple[str, ...],
    ]:
        """Return weak groups, strong groups, and isolated device ids."""
        if self.size == 0:
            return (), (), ()
        weak = _groups(self.matrix, self.node_ids, directed=False)
        strong = _groups(self.matrix, self.node_ids, directed=True)
        isolated = tuple(
            self.node_ids[i]
            for i in range(self.size)
            if self.indptr[i] == self.indptr[i + 1]
            and (self.reverse.indptr[i] == self.reverse.indptr[i + 1])
        )
        return weak, strong, isolated


def _pack_rows(
    rows: list[list[tuple[int, float, str]]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Pack sorted per-row arcs into aligned CSR arrays."""
    indptr = [0]
    indices: list[int] = []
    costs: list[float] = []
    link_ids: list[str] = []
    for row in rows:
        for column, cost, link_id in sorted(row):
            indices.append(column)
            costs.append(cost)
            link_ids.append(link_id)
        indptr.append(len(indices))
    return (
        np.asarray(indptr, dtype=np.int32),
        np.asarray(indices, dtype=np.int32),
        np.asarray(costs, dtype=float),
        link_ids,
    )


def _on_shortest_path(cost: float, remaining: float, limit: float) -> bool:
    """Return whether an arc preserves the exact Python-float shortest cost."""
    return cost + remaining == limit


def _groups(
    matrix: csr_matrix,
    node_ids: tuple[str, ...],
    *,
    directed: bool,
) -> tuple[tuple[str, ...], ...]:
    _, labels = connected_components(
        matrix,
        directed=directed,
        connection="strong" if directed else "weak",
    )
    grouped: dict[int, list[str]] = {}
    for position, label in enumerate(labels):
        grouped.setdefault(int(label), []).append(node_ids[position])
    return tuple(sorted(tuple(sorted(group)) for group in grouped.values()))


__all__ = ["SparseRouter"]
