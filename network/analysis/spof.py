"""Single-point-of-failure report for devices and physical links.

A single point of failure is an entity whose individual removal increases the
number of connected components. That covers both disconnecting the topology
and cutting off one or more devices. The report is derived from articulation
points and bridges on the undirected physical projection; parallel links are
never reported as a single-link failure point.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import networkx as nx
from pydantic import BaseModel, Field

from core.schemas.network import Topology

from .graph import build_structural_graph
from .metrics import (
    CriticalLinksReport,
    CriticalNodesReport,
    _critical_links_from_graph,
    _critical_nodes_from_graph,
)


class SpofEntry(BaseModel):
    """One device or physical link whose removal splits the topology."""

    kind: Literal["device", "link"]
    entity_id: str = Field(description="Device id or link id.")
    endpoints: list[str] = Field(
        default_factory=list,
        description="Sorted link endpoints; empty for a device entry.",
    )
    components_after_removal: int = Field(ge=0)
    isolated_device_ids: list[str] = Field(default_factory=list)


class SpofReport(BaseModel):
    """All single points of failure, ordered by kind then id."""

    baseline_component_count: int = Field(ge=0)
    entries: list[SpofEntry] = Field(default_factory=list)


def spof_from_reports(
    baseline_component_count: int,
    nodes: CriticalNodesReport,
    links: CriticalLinksReport,
) -> SpofReport:
    """Combine critical-node and critical-link results into a SPOF report."""
    entries = [
        SpofEntry(
            kind="device",
            entity_id=node.device_id,
            components_after_removal=node.components_after_removal,
            isolated_device_ids=node.isolated_device_ids,
        )
        for node in nodes.nodes
    ]
    entries.extend(
        SpofEntry(
            kind="link",
            entity_id=link.link_id,
            endpoints=link.endpoints,
            components_after_removal=link.components_after_removal,
            isolated_device_ids=link.isolated_device_ids,
        )
        for link in links.links
    )
    entries.sort(key=lambda entry: (entry.kind, entry.entity_id))
    return SpofReport(
        baseline_component_count=baseline_component_count,
        entries=entries,
    )


def spof_report(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> SpofReport:
    """Return devices and links whose removal increases component count."""
    graph = build_structural_graph(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    baseline = (
        nx.number_connected_components(graph)
        if graph.number_of_nodes()
        else 0
    )
    return spof_from_reports(
        baseline,
        _critical_nodes_from_graph(graph),
        _critical_links_from_graph(graph),
    )
