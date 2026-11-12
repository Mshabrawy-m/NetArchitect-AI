"""UI-agnostic table rows for addressing results.

These helpers return plain ``list[dict[str, object]]`` rows so the UI layer can
turn them into DataFrames, CSV, or another presentation without importing
pandas into the engineering modules.
"""

from __future__ import annotations

from network.addressing.cidr import SubnetInfo
from network.addressing.utilization import UtilizationReport
from network.addressing.vlsm import VlsmResult


def cidr_rows(info: SubnetInfo) -> list[dict[str, object]]:
    """Return a one-row table describing a calculated subnet."""
    return [
        {
            "name": info.name,
            "network": str(info.network),
            "version": info.version,
            "prefix_length": info.prefix_length,
            "netmask": info.netmask or "",
            "network_address": info.network_address,
            "broadcast_address": info.broadcast_address or "",
            "first_usable": info.first_usable or "",
            "last_usable": info.last_usable or "",
            "usable_hosts": info.usable_host_count,
            "total_addresses": info.total_addresses,
            "special_case": info.special_case,
        }
    ]


def allocation_rows(result: VlsmResult) -> list[dict[str, object]]:
    """Return one row per VLSM allocation."""
    return [
        {
            "name": allocation.name,
            "network": str(allocation.network),
            "prefix_length": allocation.prefix_length,
            "netmask": allocation.netmask or "",
            "gateway": str(allocation.gateway) if allocation.gateway else "",
            "first_host": str(allocation.first_host) if allocation.first_host else "",
            "last_host": str(allocation.last_host) if allocation.last_host else "",
            "requested_hosts": allocation.required_hosts,
            "host_capacity": allocation.host_capacity,
            "reserved_addresses": allocation.reserved_addresses,
            "total_addresses": allocation.total_addresses,
        }
        for allocation in result.allocations
    ]


def utilization_rows(report: UtilizationReport) -> list[dict[str, object]]:
    """Return one row per subnet in a utilization report."""
    return [
        {
            "name": row.name,
            "network": str(row.network),
            "used_addresses": row.used_addresses,
            "usable_addresses": row.usable_addresses,
            "remaining_addresses": row.remaining_addresses,
            "utilization_percent": row.utilization_percent,
        }
        for row in report.subnets
    ]
