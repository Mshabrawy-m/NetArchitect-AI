"""Shared builders for the Phase 5 routing unit tests."""

from __future__ import annotations

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology


def make_device(
    device_id: str,
    device_type: DeviceType = DeviceType.router,
    role: DeviceRole = DeviceRole.core,
    site: str = "site-1",
) -> Device:
    return Device(id=device_id, type=device_type, site=site, role=role)


def make_link(
    link_id: str,
    first: str,
    second: str,
    cost: float = 1.0,
    directed: bool = False,
    capacity_mbps: float = 1000.0,
) -> Link:
    return Link(
        id=link_id,
        endpoints=(first, second),
        capacity_mbps=capacity_mbps,
        cost=cost,
        directed=directed,
    )


def build_topology(
    name: str,
    device_ids: list[str],
    links: list[Link],
) -> Topology:
    return Topology(
        name=name,
        devices=[make_device(device_id) for device_id in device_ids],
        links=links,
    )
