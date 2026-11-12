"""Deterministic connectivity analysis for a topology.

Connectivity is a physical-layer property: whether devices can reach each
other through links, regardless of link direction. Directed links are treated
as usable in both directions for component detection; routing-level
reachability (which honors direction) belongs to the Phase 5 routing engine.

The result is a typed, frozen :class:`ConnectivityReport`, suitable for UI
rendering, JSON export, and assertions in tests without parsing prose.
"""

from __future__ import annotations

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from core.schemas.network import Topology

from .graph import to_networkx


class ConnectedComponent(BaseModel):
    """One connected group of devices and the links inside it."""

    model_config = ConfigDict(frozen=True)

    device_ids: tuple[str, ...] = Field(
        description="Device ids in this component, sorted.",
    )
    link_ids: tuple[str, ...] = Field(
        description="Ids of links with both endpoints in this component, sorted.",
    )


class ConnectivityReport(BaseModel):
    """Typed result of a connectivity check."""

    model_config = ConfigDict(frozen=True)

    is_connected: bool = Field(
        description="True only when every device is in one component.",
    )
    node_count: int = Field(description="Number of devices considered.")
    link_count: int = Field(description="Number of links considered.")
    component_count: int = Field(description="Number of connected components.")
    components: tuple[ConnectedComponent, ...] = Field(
        description="Components ordered by their smallest device id.",
    )
    isolated_device_ids: tuple[str, ...] = Field(
        description="Devices with no attached links, sorted.",
    )


def analyze_connectivity(topology: Topology) -> ConnectivityReport:
    """Check connected components and isolated devices in ``topology``.

    An empty topology is reported as not connected with zero components: it
    models no network yet. A single device counts as connected (one component).
    """
    graph = to_networkx(topology)
    undirected = graph.to_undirected(as_view=False)

    node_groups = [tuple(sorted(group)) for group in nx.connected_components(undirected)]
    node_groups.sort(key=lambda group: group[0])
    groups = [set(group) for group in node_groups]

    components: list[ConnectedComponent] = []
    for nodes, group in zip(node_groups, groups):
        link_ids = tuple(
            sorted(
                link.id
                for link in topology.links
                if link.endpoints[0] in group and link.endpoints[1] in group
            )
        )
        components.append(
            ConnectedComponent(device_ids=nodes, link_ids=link_ids)
        )

    isolated = tuple(
        sorted(node for node, degree in undirected.degree() if degree == 0)
    )

    node_count = len(topology.devices)
    return ConnectivityReport(
        is_connected=node_count > 0 and len(components) == 1,
        node_count=node_count,
        link_count=len(topology.links),
        component_count=len(components),
        components=tuple(components),
        isolated_device_ids=isolated,
    )
