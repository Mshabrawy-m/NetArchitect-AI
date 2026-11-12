"""Aggregate structural analysis for one topology."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from core.schemas.network import Topology
from core.schemas.validation import Finding

from .findings import analysis_findings
from .graph import build_structural_graph
from .metrics import (
    CentralityReport,
    ComponentAnalysis,
    CriticalLinksReport,
    CriticalNodesReport,
    DiameterReport,
    _centrality_from_graph,
    _components_from_graph,
    _critical_links_from_graph,
    _critical_nodes_from_graph,
    _diameter_from_graph,
)
from .spof import SpofReport, spof_from_reports


class AnalysisReport(BaseModel):
    """All structural metrics and findings for one topology snapshot."""

    centrality: CentralityReport
    components: ComponentAnalysis
    diameter: DiameterReport
    critical_nodes: CriticalNodesReport
    critical_links: CriticalLinksReport
    spof: SpofReport
    findings: list[Finding] = Field(default_factory=list)


def analyze_topology(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> AnalysisReport:
    """Compute the complete structural analysis in one pass over the graph.

    Every metric is a design-time structural indicator. None of the values is
    a measurement of real traffic, latency, utilization, or availability.
    """
    graph = build_structural_graph(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    components = _components_from_graph(graph)
    nodes = _critical_nodes_from_graph(graph)
    links = _critical_links_from_graph(graph)
    spof = spof_from_reports(components.component_count, nodes, links)
    return AnalysisReport(
        centrality=_centrality_from_graph(graph),
        components=components,
        diameter=_diameter_from_graph(graph),
        critical_nodes=nodes,
        critical_links=links,
        spof=spof,
        findings=analysis_findings(spof, components),
    )
