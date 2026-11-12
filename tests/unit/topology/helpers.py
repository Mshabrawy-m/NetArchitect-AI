"""Shared topology builders for the Phase 3 unit tests."""

from __future__ import annotations

from core.schemas.network import Device, DeviceRole, DeviceType, Link


def make_device(
    device_id: str,
    device_type: DeviceType = DeviceType.router,
    role: DeviceRole = DeviceRole.core,
    site: str = "site-1",
) -> Device:
    return Device(id=device_id, type=device_type, site=site, role=role)


def make_link(
    link_id: str,
    first: str = "r1",
    second: str = "r2",
    capacity_mbps: float = 1000.0,
    cost: float = 1.0,
    directed: bool = False,
) -> Link:
    return Link(
        id=link_id,
        endpoints=(first, second),
        capacity_mbps=capacity_mbps,
        cost=cost,
        directed=directed,
    )
