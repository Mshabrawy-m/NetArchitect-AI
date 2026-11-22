"""Public API of the deterministic routing engine.

Import from ``network.routing`` rather than from the individual modules.
Every function is stateless: it takes a :class:`~core.schemas.network.Topology`
(plus optional failure ids) and returns new typed objects. The input topology
is never modified.
"""

from .graph import build_routing_graph, excluded_ids
from .ospf import (
    BACKBONE_AREA_ID,
    OspfAnalysis,
    OspfArea,
    OspfDesign,
    OspfLinkCost,
    OspfRouter,
    OspfRouterRole,
    OspfSummary,
    analyze_ospf_design,
)
from .paths import (
    AlternativePaths,
    ComponentSummary,
    ReachabilityMatrix,
    RouteHop,
    RoutePath,
    RoutingTable,
    RoutingTableEntry,
    alternative_paths,
    component_summary,
    component_summary_from_router,
    equal_cost_paths_from_router,
    reachability_matrix,
    routing_table,
    shortest_path,
    shortest_path_from_router,
)
from .sparse import SparseRouter
from .tables import (
    alternative_rows,
    path_rows,
    reachability_rows,
    routing_table_rows,
)

__all__ = [
    "BACKBONE_AREA_ID",
    "AlternativePaths",
    "ComponentSummary",
    "OspfAnalysis",
    "OspfArea",
    "OspfDesign",
    "OspfLinkCost",
    "OspfRouter",
    "OspfRouterRole",
    "OspfSummary",
    "ReachabilityMatrix",
    "RouteHop",
    "RoutePath",
    "RoutingTable",
    "RoutingTableEntry",
    "SparseRouter",
    "alternative_paths",
    "alternative_rows",
    "analyze_ospf_design",
    "build_routing_graph",
    "component_summary",
    "component_summary_from_router",
    "equal_cost_paths_from_router",
    "excluded_ids",
    "path_rows",
    "reachability_matrix",
    "reachability_rows",
    "routing_table",
    "routing_table_rows",
    "shortest_path",
    "shortest_path_from_router",
]
