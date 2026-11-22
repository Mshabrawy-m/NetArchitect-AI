"""Spreadsheet-safe inventory export for a digital twin.

One UTF-8 CSV carries every section as tagged rows with a leading ``section``
column. Cells are neutralized at serialization time only; the stored twin is
never modified. Output is bounded by the same report byte cap as other exports.
"""

from __future__ import annotations

import csv
import io

from config.limits import MAX_EDGES, MAX_NODES, MAX_REPORT_BYTES, MAX_SUBNETS
from core.csv_safe import neutralize_cell
from core.exceptions import ReportLimitError
from digital_twin import DigitalTwin

from .common import enforce_size

INVENTORY_COLUMNS: tuple[str, ...] = (
    "section",
    "entity_id",
    "field",
    "value",
    "notes",
)
_CRLF = "\r\n"


def _number(value: float) -> str:
    return str(value)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _empty(section: str) -> tuple[str, str, str, str, str]:
    return (section, "", "empty", f"No {section} modeled", "")


def _rows(twin: DigitalTwin) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []

    devices = sorted(twin.topology.devices, key=lambda item: item.id)[:MAX_NODES]
    if devices:
        for device in devices:
            notes = (
                f"type={device.type.value};site={device.site};"
                f"role={device.role.value}"
            )
            rows.append(("devices", device.id, "device", device.id, notes))
    else:
        rows.append(_empty("devices"))

    links = sorted(twin.topology.links, key=lambda item: item.id)[:MAX_EDGES]
    if links:
        for link in links:
            first, second = link.endpoints
            notes = (
                f"endpoints={first}|{second};"
                f"capacity_mbps={_number(link.capacity_mbps)};"
                f"cost={_number(link.cost)};"
                f"directed={'true' if link.directed else 'false'}"
            )
            rows.append(("links", link.id, "link", link.id, notes))
    else:
        rows.append(_empty("links"))

    subnets: list[tuple[str, str, str]] = []
    plan = twin.addressing
    if plan is not None:
        for vlan_plan in plan.vlan_plans[:MAX_SUBNETS]:
            for subnet in vlan_plan.subnets[:MAX_SUBNETS]:
                subnets.append(
                    (subnet.name, str(vlan_plan.vlan_id), str(subnet.network))
                )
        for subnet in plan.subnets[:MAX_SUBNETS]:
            subnets.append((subnet.name, "", str(subnet.network)))
    subnets = subnets[:MAX_SUBNETS]
    if subnets:
        for name, vlan_id, network in subnets:
            rows.append(("subnets", name, "subnet", name, f"vlan={vlan_id};network={network}"))
    else:
        rows.append(_empty("subnets"))

    assignments = (
        twin.vlan_plan.assignments[:MAX_SUBNETS] if twin.vlan_plan is not None else []
    )
    if assignments:
        for assignment in assignments:
            notes = (
                f"name={assignment.vlan_name};department={assignment.department};"
                f"subnet={assignment.subnet_name};network={assignment.network}"
            )
            rows.append(
                ("vlans", str(assignment.vlan_id), "vlan", str(assignment.vlan_id), notes)
            )
    else:
        rows.append(_empty("vlans"))

    scopes = twin.dhcp_scopes[:MAX_SUBNETS]
    if scopes:
        for scope in scopes:
            excluded = ", ".join(
                f"{_text(start)}-{_text(end)}"
                for start, end in scope.excluded_ranges[:MAX_SUBNETS]
            )
            notes = (
                f"network={scope.network};gateway={_text(scope.gateway)};"
                f"start={_text(scope.start_address)};"
                f"end={_text(scope.end_address)};"
                f"lease_minutes={scope.lease_minutes};"
                f"excluded={excluded or 'none'}"
            )
            rows.append(("dhcp", scope.name, "scope", scope.name, notes))
    else:
        rows.append(_empty("dhcp"))

    return rows


def to_inventory_csv(twin: DigitalTwin) -> bytes:
    """Return deterministic UTF-8/CRLF CSV bytes for ``twin``'s inventory."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator=_CRLF)
    writer.writerow(tuple(neutralize_cell(cell) for cell in INVENTORY_COLUMNS))
    for row in _rows(twin):
        writer.writerow(tuple(neutralize_cell(cell) for cell in row))

    payload = buffer.getvalue().encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ReportLimitError(
            f"The inventory CSV export is {len(payload)} bytes, above the "
            f"{MAX_REPORT_BYTES}-byte limit."
        )
    return enforce_size(payload, kind="inventory CSV")


__all__ = ["INVENTORY_COLUMNS", "to_inventory_csv"]
