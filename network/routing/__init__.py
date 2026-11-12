"""Public API of the deterministic routing engine.

Import from ``network.routing`` rather than from the individual modules.
Every function is stateless: it takes a :class:`~core.schemas.network.Topology`
(plus optional failure ids) and returns new typed objects. The input topology
is never modified.
"""

from .graph import build_routing_graph, excluded_ids
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
    reachability_matrix,
    routing_table,
    shortest_path,
)
from .tables import (
    alternative_rows,
    path_rows,
    reachability_rows,
    routing_table_rows,
)

__all__ = [
    "AlternativePaths",
    "ComponentSummary",
    "ReachabilityMatrix",
    "RouteHop",
    "RoutePath",
    "RoutingTable",
    "RoutingTableEntry",
    "alternative_paths",
    "alternative_rows",
    "build_routing_graph",
    "component_summary",
    "excluded_ids",
    "path_rows",
    "reachability_matrix",
    "reachability_rows",
    "routing_table",
    "routing_table_rows",
    "shortest_path",
]
