"""Direction-aware node- and link-disjoint path counts between two devices.

Definitions
-----------
* A node-disjoint count is the maximum number of paths that share only the
  source and destination devices. Direction is honored: a directed link only
  permits travel from its first endpoint to its second.
* An edge-disjoint count is the maximum number of paths that share no
  physical link. Parallel links are separate physical links, so they can
  increase this count. An undirected link carries at most one counted path in
  either direction; the engine models each physical link as a capacity-one
  bottleneck for this calculation.

Both counts are structural indicators. They say nothing about traffic load,
bandwidth, or whether the paths would survive simultaneous failures that are
not modeled here.
"""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx
from pydantic import BaseModel, Field

from core.exceptions import DeviceNotFoundError
from core.schemas.network import Topology
from network.routing.graph import build_routing_graph, excluded_ids


class RedundancyReport(BaseModel):
    """Redundancy between one ordered source/destination pair."""

    source: str
    destination: str
    reachable: bool = False
    node_disjoint_paths: int = Field(default=0, ge=0)
    edge_disjoint_paths: int = Field(default=0, ge=0)
    reason: str = ""


def _require_device(topology: Topology, device_id: str) -> None:
    if not any(device.id == device_id for device in topology.devices):
        raise DeviceNotFoundError(
            f"Device {device_id!r} is not present in topology {topology.name!r}"
        )


def _node_disjoint_count(
    graph: nx.DiGraph,
    source: str,
    destination: str,
) -> int:
    try:
        return sum(
            1 for _ in nx.node_disjoint_paths(graph, source, destination)
        )
    except nx.NetworkXNoPath:
        return 0


def _edge_disjoint_count(
    topology: Topology,
    source: str,
    destination: str,
    failed_device_ids: set[str],
    failed_link_ids: set[str],
) -> int:
    """Return the physical-link-disjoint path count via a unit-capacity flow."""
    flow = nx.DiGraph()
    surviving = sorted(
        device.id
        for device in topology.devices
        if device.id not in failed_device_ids
    )
    flow.add_nodes_from(surviving)

    for link in topology.links:
        if link.id in failed_link_ids:
            continue
        first, second = link.endpoints
        if first in failed_device_ids or second in failed_device_ids:
            continue
        in_node = ("__link_in__", link.id)
        out_node = ("__link_out__", link.id)
        # One capacity unit per physical link, shared by both directions.
        flow.add_edge(in_node, out_node, capacity=1)
        directions = [(first, second)]
        if not link.directed:
            directions.append((second, first))
        for start, end in directions:
            flow.add_edge(start, in_node, capacity=1)
            flow.add_edge(out_node, end, capacity=1)

    if source not in flow or destination not in flow:
        return 0
    return int(
        nx.maximum_flow_value(
            flow,
            source,
            destination,
            capacity="capacity",
        )
    )


def redundancy(
    topology: Topology,
    source: str,
    destination: str,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> RedundancyReport:
    """Return node- and edge-disjoint path counts for one ordered pair."""
    _require_device(topology, source)
    _require_device(topology, destination)
    failed_device_ids, failed_link_ids = excluded_ids(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    if source in failed_device_ids or destination in failed_device_ids:
        return RedundancyReport(
            source=source,
            destination=destination,
            reason="A selected endpoint is failed",
        )
    if source == destination:
        return RedundancyReport(
            source=source,
            destination=destination,
            reachable=True,
            reason="Source equals destination; path redundancy is undefined",
        )

    graph = build_routing_graph(
        topology,
        failed_devices=failed_device_ids,
        failed_links=failed_link_ids,
    )
    if not nx.has_path(graph, source, destination):
        return RedundancyReport(
            source=source,
            destination=destination,
            reason="No directed path exists between the selected devices",
        )

    return RedundancyReport(
        source=source,
        destination=destination,
        reachable=True,
        node_disjoint_paths=_node_disjoint_count(graph, source, destination),
        edge_disjoint_paths=_edge_disjoint_count(
            topology,
            source,
            destination,
            failed_device_ids,
            failed_link_ids,
        ),
    )
