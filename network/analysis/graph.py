"""Structural graph projection used by the analysis engine.

Metric basis
------------
All physical metrics are computed from a simple undirected projection of the
topology:

* A link contributes one undirected edge regardless of ``Link.directed``.
  Connectivity, centrality, articulation points, bridges, components, and
  diameter describe physical adjacency, so direction is ignored here.
  Direction-aware reachability belongs to :mod:`network.routing`.
* Parallel links between the same pair of devices collapse to one edge. The
  edge keeps every participating ``link_id`` and the lowest ``cost``, so a
  pair joined by two links is not treated as a single-link chokepoint.
* ``Link.cost`` is the edge weight used only by weighted betweenness
  centrality. Other metrics are hop-based and ignore cost.

These are design-time structural indicators. They are not measurements of
real network traffic, latency, utilization, or availability.

Failures
--------
Failed devices and failed links are removed while the projection is built.
The input :class:`~core.schemas.network.Topology` is never modified. Unknown
failure ids raise the same typed errors as the routing engine.
"""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx

from config.limits import MAX_NODES
from core.exceptions import LimitsExceededError
from core.schemas.network import Topology
from network.routing.graph import excluded_ids


def build_structural_graph(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> nx.Graph:
    """Return the deterministic undirected projection of a topology.

    Nodes are sorted device ids. Edges carry ``link_ids`` (sorted tuple),
    ``link_count``, and ``cost`` (the lowest cost among parallel links).
    """
    if len(topology.devices) > MAX_NODES:
        raise LimitsExceededError(
            f"Analysis received {len(topology.devices)} devices; "
            f"the limit is {MAX_NODES}"
        )

    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    surviving_devices = sorted(
        device.id for device in topology.devices if device.id not in failed_device_ids
    )

    parallel: dict[frozenset[str], list[tuple[str, float]]] = {}
    for link in topology.links:
        if link.id in failed_link_ids:
            continue
        if (
            link.endpoints[0] in failed_device_ids
            or link.endpoints[1] in failed_device_ids
        ):
            continue
        pair = frozenset(link.endpoints)
        parallel.setdefault(pair, []).append((link.id, float(link.cost)))

    graph = nx.Graph()
    graph.graph["name"] = topology.name
    graph.add_nodes_from(surviving_devices)
    for pair in sorted(parallel, key=lambda value: tuple(sorted(value))):
        links = sorted(parallel[pair], key=lambda item: (item[1], item[0]))
        first, second = sorted(pair)
        graph.add_edge(
            first,
            second,
            link_ids=tuple(sorted(link_id for link_id, _ in links)),
            link_count=len(links),
            cost=links[0][1],
        )
    return graph
