"""UI-agnostic table rows for structural analysis results."""

from __future__ import annotations

from .metrics import (
    CentralityReport,
    ComponentAnalysis,
    CriticalLinksReport,
    CriticalNodesReport,
    DiameterReport,
)
from .redundancy import RedundancyReport
from .spof import SpofReport


def centrality_rows(report: CentralityReport) -> list[dict[str, object]]:
    """Return one row per device, ordered by device id."""
    return [
        {
            "device_id": metric.device_id,
            "degree": metric.degree,
            "degree_centrality": metric.degree_centrality,
            "betweenness_centrality": metric.betweenness_centrality,
        }
        for metric in report.metrics
    ]


def component_rows(analysis: ComponentAnalysis) -> list[dict[str, object]]:
    """Return one row per connected component."""
    return [
        {
            "component": index,
            "device_count": len(component),
            "devices": ", ".join(component),
        }
        for index, component in enumerate(analysis.components, start=1)
    ]


def diameter_rows(report: DiameterReport) -> list[dict[str, object]]:
    """Return one row per component diameter."""
    return [
        {
            "component": index,
            "device_count": len(component.device_ids),
            "diameter_hops": component.diameter,
        }
        for index, component in enumerate(report.per_component, start=1)
    ]


def critical_node_rows(report: CriticalNodesReport) -> list[dict[str, object]]:
    """Return one row per articulation point."""
    return [
        {
            "device_id": node.device_id,
            "components_after_removal": node.components_after_removal,
            "isolated_devices": ", ".join(node.isolated_device_ids),
        }
        for node in report.nodes
    ]


def critical_link_rows(report: CriticalLinksReport) -> list[dict[str, object]]:
    """Return one row per bridge."""
    return [
        {
            "link_id": link.link_id,
            "endpoints": " - ".join(link.endpoints),
            "components_after_removal": link.components_after_removal,
            "isolated_devices": ", ".join(link.isolated_device_ids),
        }
        for link in report.links
    ]


def spof_rows(report: SpofReport) -> list[dict[str, object]]:
    """Return one row per single point of failure."""
    return [
        {
            "kind": entry.kind,
            "entity_id": entry.entity_id,
            "endpoints": " - ".join(entry.endpoints),
            "components_after_removal": entry.components_after_removal,
            "isolated_devices": ", ".join(entry.isolated_device_ids),
        }
        for entry in report.entries
    ]


def redundancy_rows(report: RedundancyReport) -> list[dict[str, object]]:
    """Return the redundancy counts as label/value rows."""
    return [
        {
            "metric": "node-disjoint paths",
            "value": report.node_disjoint_paths,
        },
        {
            "metric": "edge-disjoint paths",
            "value": report.edge_disjoint_paths,
        },
    ]
