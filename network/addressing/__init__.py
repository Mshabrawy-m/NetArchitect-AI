"""Public API of the deterministic addressing engine.

Import from ``network.addressing`` rather than from individual modules.
"""

from .cidr import IPNetwork, SubnetInfo, calculate_subnet, coerce_network
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
    "AddressAssignment",
    "IPNetwork",
    "SubnetInfo",
    "SubnetUtilization",
    "UtilizationEntry",
    "UtilizationReport",
    "VlsmAllocation",
    "VlsmRequirement",
    "VlsmResult",
    "allocate_vlsm",
    "allocation_rows",
    "build_utilization_report",
    "calculate_subnet",
    "cidr_rows",
    "coerce_network",
    "default_reserved_addresses",
    "detect_duplicate_ips",
    "detect_overlaps",
    "utilization_rows",
    "validate_addressing",
]
