"""Deterministic default security-model derivation from a digital twin.

The derivation is a pure function of the twin. It uses only modeled VLAN and
device data, applies fixed keyword groups in a fixed priority order, and records
its assumptions in the returned model. It never inspects a live network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.schemas.network import DeviceRole, DeviceType

from .models import (
    FirewallRule,
    PolicyAction,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

# Priority matters: a "public web" VLAN is a DMZ, not a generic server VLAN.
_KEYWORDS: tuple[tuple[ZoneType, tuple[str, ...]], ...] = (
    (ZoneType.management, ("mgmt", "management", "manage", "admin", "oam", "operations")),
    (ZoneType.dmz, ("dmz", "public", "internet-facing", "internet facing", "web")),
    (ZoneType.guest, ("guest", "visitor")),
    (ZoneType.iot, ("iot", "sensor", "camera", "building")),
    (ZoneType.server, ("server", "app", "database", "backend", "data")),
    (ZoneType.user, ("user", "staff", "office", "corp", "employee", "client")),
    (ZoneType.untrusted_external, ("external", "internet", "wan")),
)

_TITLES: dict[ZoneType, str] = {
    ZoneType.untrusted_external: "Untrusted external",
    ZoneType.dmz: "DMZ",
    ZoneType.server: "Server",
    ZoneType.user: "User",
    ZoneType.management: "Management",
    ZoneType.guest: "Guest",
    ZoneType.iot: "IoT",
    ZoneType.other: "Other",
}

_CRITICALITY: dict[ZoneType, int] = {
    ZoneType.untrusted_external: 2,
    ZoneType.dmz: 3,
    ZoneType.server: 4,
    ZoneType.user: 3,
    ZoneType.management: 5,
    ZoneType.guest: 1,
    ZoneType.iot: 2,
    ZoneType.other: 3,
}

_DEFAULT_SERVICES: tuple[Service, ...] = (
    Service(name="http", protocol="tcp", port_start=80, port_end=80),
    Service(name="https", protocol="tcp", port_start=443, port_end=443),
    Service(name="dns-tcp", protocol="tcp", port_start=53, port_end=53),
    Service(name="dns-udp", protocol="udp", port_start=53, port_end=53),
    Service(name="ssh", protocol="tcp", port_start=22, port_end=22),
    Service(name="icmp", protocol="icmp", port_start=0, port_end=0),
)

_ASSUMPTIONS: tuple[str, ...] = (
    (
        "Zone criticality is a user-set modeling assumption on a 1-5 scale; it is "
        "not measured and is not a CVSS score."
    ),
    (
        "Default zones use fixed keyword groups over VLAN department, VLAN name, "
        "subnet name, and purpose, followed by device type and role."
    ),
    (
        "Devices with no zone-matching VLAN or role remain unassigned so the design "
        "check can report them."
    ),
    (
        "The default policy is deny; explicit deny rules are added from guest and "
        "IoT zones to server and management zones when those zones exist."
    ),
)


def _classify_text(value: str) -> ZoneType | None:
    text = value.lower()
    for zone_type, keywords in _KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return zone_type
    return None


def _device_zone_type(device: object) -> ZoneType | None:
    """Classify one modeled device by explicit role/type, then by its id."""
    role = getattr(device, "role", None)
    device_type = getattr(device, "type", None)
    if role is DeviceRole.dmz:
        return ZoneType.dmz
    if role in {DeviceRole.border, DeviceRole.edge, DeviceRole.wan}:
        return ZoneType.untrusted_external
    if device_type is DeviceType.server:
        return ZoneType.server
    if device_type is DeviceType.controller:
        return ZoneType.management
    return _classify_text(str(getattr(device, "id", "")))


def _default_rules(zone_types: set[ZoneType]) -> tuple[FirewallRule, ...]:
    rules: list[FirewallRule] = []
    order = 0
    for source in (ZoneType.guest, ZoneType.iot):
        if source not in zone_types:
            continue
        for destination in (ZoneType.server, ZoneType.management):
            if destination not in zone_types:
                continue
            rules.append(
                FirewallRule(
                    id=f"derived-deny-{source.value}-{destination.value}",
                    order=order,
                    src_zone=f"zone-{source.value}",
                    dst_zone=f"zone-{destination.value}",
                    any_service=True,
                    action=PolicyAction.deny,
                    note="Derived boundary rule; review against the intended policy.",
                )
            )
            order += 1
    return tuple(rules)


def derive_default_security_model(twin: DigitalTwin) -> SecurityModel:
    """Return the deterministic default zone model for ``twin``.

    The baseline twin is not modified. VLAN ids and device ids are grouped by
    the fixed keyword groups documented in :data:`_ASSUMPTIONS`; unmatched
    members are deliberately left unassigned.
    """
    vlan_ids: dict[ZoneType, set[int]] = {zone_type: set() for zone_type in ZoneType}
    device_ids: dict[ZoneType, set[str]] = {zone_type: set() for zone_type in ZoneType}

    for assignment in twin.vlan_plan.assignments if twin.vlan_plan else ():
        text = (
            f"{assignment.department} {assignment.vlan_name} "
            f"{assignment.subnet_name} {assignment.purpose}"
        )
        zone_type = _classify_text(text)
        if zone_type is not None:
            vlan_ids[zone_type].add(assignment.vlan_id)

    for device in twin.topology.devices:
        zone_type = _device_zone_type(device)
        if zone_type is not None:
            device_ids[zone_type].add(device.id)

    zones: list[Zone] = []
    for zone_type in ZoneType:
        vlans = vlan_ids[zone_type]
        devices = device_ids[zone_type]
        if not vlans and not devices:
            continue
        zones.append(
            Zone(
                id=f"zone-{zone_type.value}",
                name=_TITLES[zone_type],
                type=zone_type,
                criticality=_CRITICALITY[zone_type],
                member_vlan_ids=tuple(sorted(vlans)),
                member_device_ids=tuple(sorted(devices)),
            )
        )

    return SecurityModel(
        zones=tuple(zones),
        services=_DEFAULT_SERVICES,
        rules=_default_rules({zone.type for zone in zones}),
        default_action=PolicyAction.deny,
        assumptions=_ASSUMPTIONS,
    )


__all__ = ["derive_default_security_model"]
