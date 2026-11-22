"""Public API of the deterministic addressing engine.

Import from ``network.addressing`` rather than from individual modules.
"""

from .cidr import IPNetwork, SubnetInfo, calculate_subnet, coerce_network
from .dual_stack import (
    IPV6_VLAN_PREFIX_LENGTH,
    DualStackAssignment,
    DualStackPlan,
    DualStackRequest,
    Ipv6Scope,
    available_prefixes,
    classify_ipv6_scope,
    dual_stack_rows,
    plan_dual_stack,
    prefix_at,
    requests_from_plan,
    validate_dual_stack,
)
from .nat import (
    DEFAULT_SESSIONS_PER_HOST,
    DEFAULT_USABLE_PORTS_PER_ADDRESS,
    NatAnalysis,
    NatPlan,
    NatRule,
    NatSizing,
    NatType,
    analyze_nat_plan,
    derived_host_count,
)
from .tables import allocation_rows, cidr_rows, utilization_rows
from .utilization import (
    SubnetUtilization,
    UtilizationEntry,
    UtilizationReport,
    build_utilization_report,
)
from .validation import (
    AddressAssignment,
    detect_duplicate_ips,
    detect_overlaps,
    validate_addressing,
)
from .vlsm import (
    VlsmAllocation,
    VlsmRequirement,
    VlsmResult,
    allocate_vlsm,
    default_reserved_addresses,
)

__all__ = [
    "DEFAULT_SESSIONS_PER_HOST",
    "DEFAULT_USABLE_PORTS_PER_ADDRESS",
    "IPV6_VLAN_PREFIX_LENGTH",
    "AddressAssignment",
    "DualStackAssignment",
    "DualStackPlan",
    "DualStackRequest",
    "IPNetwork",
    "Ipv6Scope",
    "NatAnalysis",
    "NatPlan",
    "NatRule",
    "NatSizing",
    "NatType",
    "SubnetInfo",
    "SubnetUtilization",
    "UtilizationEntry",
    "UtilizationReport",
    "VlsmAllocation",
    "VlsmRequirement",
    "VlsmResult",
    "allocate_vlsm",
    "allocation_rows",
    "analyze_nat_plan",
    "available_prefixes",
    "build_utilization_report",
    "calculate_subnet",
    "cidr_rows",
    "classify_ipv6_scope",
    "coerce_network",
    "default_reserved_addresses",
    "derived_host_count",
    "detect_duplicate_ips",
    "detect_overlaps",
    "dual_stack_rows",
    "plan_dual_stack",
    "prefix_at",
    "requests_from_plan",
    "utilization_rows",
    "validate_addressing",
    "validate_dual_stack",
]
