"""Routing graph construction from a typed topology.

Link semantics
--------------
* ``Link.directed`` is honored per link. A directed link contributes exactly
  one arc from ``endpoints[0]`` to ``endpoints[1]``. An undirected link
  contributes two reciprocal arcs (both directions).
* ``Link.cost`` is the edge weight used by every path and routing-table
  calculation. Lower cost is preferred.
* ``Link.capacity_mbps`` is deliberately *not* used for path selection. This
  engine models topology and cost only; capacity-aware traffic engineering
  belongs to a later simulation/optimization phase.
* Parallel links between the same ordered pair collapse to the lowest-cost
  link; an exact cost tie is broken by the lexicographically lowest
  ``link_id``. Distinct device sequences remain available as alternative
  paths, but the same sequence over a parallel link is not returned twice.

Failures
--------
Failed devices and failed links are removed while the routing graph is built.
The original :class:`~core.schemas.network.Topology` is never modified.
Unknown failure ids raise the typed not-found errors; a known device or link
that is marked failed simply does not appear in the graph, so paths that need
it are reported as unreachable by the routing functions.

Bounds
------
``config.limits.MAX_NODES`` bounds graph construction. All-pairs routing work
is therefore bounded to ``MAX_NODES`` sources. Path search itself uses
Dijkstra (``O((V + E) log V)`` per source); the routing table and reachability
matrix run one search per source, giving ``O(V * (V + E) log V)``.
"""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx

from config.limits import MAX_NODES
from core.exceptions import (
    DeviceNotFoundError,
    LimitsExceededError,
    LinkNotFoundError,
)
from core.schemas.network import Topology


def _as_id_set(values: Iterable[str], label: str) -> set[str]:
    """Return a validated set of string ids."""
    ids: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} ids must be non-empty strings")
        ids.add(value)
    return ids


def excluded_ids(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> tuple[set[str], set[str]]:
    """Validate and return the failed device and link id sets.

    Unknown ids raise :class:`~core.exceptions.DeviceNotFoundError` or
    :class:`~core.exceptions.LinkNotFoundError` instead of being ignored.
    """
    device_ids = {device.id for device in topology.devices}
    link_ids = {link.id for link in topology.links}
    devices = _as_id_set(failed_devices, "Failed device")
    links = _as_id_set(failed_links, "Failed link")

    unknown_devices = sorted(devices - device_ids)
    if unknown_devices:
        raise DeviceNotFoundError(
            f"Failed device(s) not present in the topology: "
            f"{', '.join(unknown_devices)}"
        )
    unknown_links = sorted(links - link_ids)
    if unknown_links:
        raise LinkNotFoundError(
            f"Failed link(s) not present in the topology: "
            f"{', '.join(unknown_links)}"
        )
    return devices, links


def build_routing_graph(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> nx.DiGraph:
    """Build a deterministic directed graph for routing calculations.

    The returned graph is a plain ``DiGraph`` whose edges carry ``link_id``,
    ``cost``, ``capacity_mbps``, and ``directed``. Cost is the weight used by
    path search; capacity is metadata only. See the module docstring for
    parallel-link and failure rules.
    """
    if len(topology.devices) > MAX_NODES:
        raise LimitsExceededError(
            f"Routing analysis received {len(topology.devices)} devices; "
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

    # Keep the cheapest arc for each ordered pair; ties go to the lowest id.
    best_arcs: dict[tuple[str, str], dict[str, object]] = {}
    for link in topology.links:
        if link.id in failed_link_ids:
            continue
        source, target = link.endpoints
        if source in failed_device_ids or target in failed_device_ids:
            continue
        directions = [(source, target)]
        if not link.directed:
            directions.append((target, source))
        attributes: dict[str, object] = {
            "link_id": link.id,
            "cost": float(link.cost),
            "capacity_mbps": float(link.capacity_mbps),
            "directed": link.directed,
        }
        for start, end in directions:
            key = (start, end)
            current = best_arcs.get(key)
            if current is None or (
                attributes["cost"],
                str(attributes["link_id"]),
            ) < (
                current["cost"],
                str(current["link_id"]),
            ):
                best_arcs[key] = attributes

    graph = nx.DiGraph()
    graph.graph["name"] = topology.name
    graph.add_nodes_from(surviving_devices)
    for (source, target), attributes in sorted(best_arcs.items()):
        graph.add_edge(source, target, **attributes)
    return graph
