"""UI-agnostic table rows for VLAN plans."""

from __future__ import annotations

from network.addressing.cidr import calculate_subnet
from network.vlan.plan import VlanPlanResult


def vlan_rows(result: VlanPlanResult) -> list[dict[str, object]]:
    """Return one row per VLAN assignment."""
    rows: list[dict[str, object]] = []
    for assignment in result.assignments:
        info = calculate_subnet(assignment.network)
        rows.append(
            {
                "department": assignment.department,
                "vlan_id": assignment.vlan_id,
                "vlan_name": assignment.vlan_name,
                "subnet_name": assignment.subnet_name,
                "network": str(assignment.network),
                "prefix_length": info.prefix_length,
                "usable_hosts": info.usable_host_count,
                "purpose": assignment.purpose,
            }
        )
    return rows
