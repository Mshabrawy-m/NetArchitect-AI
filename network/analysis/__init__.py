"""Public API of the deterministic structural analysis engine.

Import from ``network.analysis`` rather than from the individual modules.
Every function is stateless: it takes a :class:`~core.schemas.network.Topology`
(plus optional failure ids) and returns new typed objects. The input topology
is never modified.

All metrics are design-time structural indicators. They are not measurements
of real network traffic, latency, utilization, or availability.
"""

from .findings import analysis_findings, spof_findings
from .graph import build_structural_graph
from .metrics import (
    METRIC_DEFINITIONS,
    CentralityMetric,
    CentralityReport,
    ComponentAnalysis,
    ComponentDiameter,
    CriticalLink,
    CriticalLinksReport,
    CriticalNode,
    CriticalNodesReport,
    DiameterReport,
    centrality_metrics,
    component_analysis,
    critical_links,
    critical_nodes,
    diameter_analysis,
)
from .redundancy import RedundancyReport, redundancy
from .report import AnalysisReport, analyze_topology
from .spof import SpofEntry, SpofReport, spof_report
from .tables import (
    centrality_rows,
    component_rows,
    critical_link_rows,
    critical_node_rows,
    diameter_rows,
    redundancy_rows,
    spof_rows,
)

__all__ = [
    "METRIC_DEFINITIONS",
    "AnalysisReport",
    "CentralityMetric",
    "CentralityReport",
    "ComponentAnalysis",
    "ComponentDiameter",
    "CriticalLink",
    "CriticalLinksReport",
    "CriticalNode",
    "CriticalNodesReport",
    "DiameterReport",
    "RedundancyReport",
    "SpofEntry",
    "SpofReport",
    "analysis_findings",
    "analyze_topology",
    "build_structural_graph",
    "centrality_metrics",
    "centrality_rows",
    "component_analysis",
    "component_rows",
    "critical_link_rows",
    "critical_links",
    "critical_node_rows",
    "critical_nodes",
    "diameter_analysis",
    "diameter_rows",
    "redundancy",
    "redundancy_rows",
    "spof_findings",
    "spof_report",
    "spof_rows",
]
