"""Public API of the deterministic VLAN and DHCP engine.

Import from ``network.vlan`` rather than from individual modules.
"""

from .dhcp import (
    DEFAULT_LEASE_MINUTES,
    DhcpScopeRow,
    dhcp_scope_rows,
    plan_dhcp_scope,
    plan_dhcp_scopes,
    validate_dhcp_scope,
)
from .plan import (
    DEFAULT_VLAN_START,
    RESERVED_VLAN_IDS,
    RESERVED_VLAN_RANGES,
    VLAN_ID_MAX,
    VLAN_ID_MIN,
    VlanAssignment,
    VlanPlanResult,
    VlanRequest,
    plan_vlans,
)
from .tables import vlan_rows

__all__ = [
    "DEFAULT_LEASE_MINUTES",
    "DEFAULT_VLAN_START",
    "RESERVED_VLAN_IDS",
    "RESERVED_VLAN_RANGES",
    "VLAN_ID_MAX",
    "VLAN_ID_MIN",
    "DhcpScopeRow",
    "VlanAssignment",
    "VlanPlanResult",
    "VlanRequest",
    "dhcp_scope_rows",
    "plan_dhcp_scope",
    "plan_dhcp_scopes",
    "plan_vlans",
    "validate_dhcp_scope",
    "vlan_rows",
]
