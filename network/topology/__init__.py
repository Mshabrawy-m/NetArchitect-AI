"""Public API of the deterministic topology engine.

Import from ``network.topology`` rather than from the individual modules.
"""

from .connectivity import ConnectedComponent, ConnectivityReport, analyze_connectivity
from .generators import (
    generate_hierarchical_campus,
    generate_hybrid,
    generate_mesh,
    generate_ring,
    generate_spine_leaf,
    generate_star,
    generate_tree,
)
from .graph import from_networkx, to_networkx, topology_directedness
from .operations import (
    add_device,
    add_link,
    enforce_limits,
    remove_device,
    remove_link,
    update_device,
    update_link,
)
from .serialization import from_json, to_json

__all__ = [
    "ConnectedComponent",
    "ConnectivityReport",
    "add_device",
    "add_link",
    "analyze_connectivity",
    "enforce_limits",
    "from_json",
    "from_networkx",
    "generate_hierarchical_campus",
    "generate_hybrid",
    "generate_mesh",
    "generate_ring",
    "generate_spine_leaf",
    "generate_star",
    "generate_tree",
    "remove_device",
    "remove_link",
    "to_json",
    "to_networkx",
    "topology_directedness",
    "update_device",
    "update_link",
]
