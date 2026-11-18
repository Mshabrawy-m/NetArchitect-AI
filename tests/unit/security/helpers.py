"""Shared builders for design-time security tests."""

from __future__ import annotations

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from digital_twin import DigitalTwin
from network.vlan import VlanAssignment, VlanPlanResult
from security import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
)
from tests.unit.digital_twin.helpers import CREATED_AT, make_twin


def make_zone(
    zone_id: str = "z-user",
    *,
    zone_type: ZoneType = ZoneType.user,
    vlan_id: int | None = 10,
    device_id: str | None = None,
    criticality: int = 3,
    expected_hosts: int | None = None,
) -> Zone:
    return Zone(
        id=zone_id,
        name=f"Zone {zone_id}",
        type=zone_type,
        criticality=criticality,
        member_vlan_ids=() if vlan_id is None else (vlan_id,),
        member_device_ids=() if device_id is None else (device_id,),
        expected_hosts=expected_hosts,
    )


def make_service(
    name: str = "http",
    *,
    protocol: Protocol = Protocol.tcp,
    port_start: int = 80,
    port_end: int = 80,
) -> Service:
    return Service(
        name=name,
        protocol=protocol,
        port_start=port_start,
        port_end=port_end,
    )


def make_rule(
    rule_id: str = "r1",
    *,
    order: int = 0,
    src_zone: str = "z-user",
    dst_zone: str = "z-server",
    services: tuple[str, ...] = ("http",),
    any_service: bool = False,
    action: PolicyAction = PolicyAction.allow,
    enabled: bool = True,
) -> FirewallRule:
    return FirewallRule(
        id=rule_id,
        order=order,
        src_zone=src_zone,
        dst_zone=dst_zone,
        services=services,
        any_service=any_service,
        action=action,
        enabled=enabled,
    )


def keyword_twin() -> DigitalTwin:
    """Return a twin whose VLAN names exercise deterministic classification."""
    topology = Topology(
        name="Security keyword campus",
        devices=[
            Device(
                id="core-1",
                type=DeviceType.router,
                site="hq",
                role=DeviceRole.core,
            ),
            Device(
                id="srv-1",
                type=DeviceType.server,
                site="hq",
                role=DeviceRole.access,
            ),
            Device(
                id="ctrl-1",
                type=DeviceType.controller,
                site="hq",
                role=DeviceRole.core,
            ),
        ],
        links=[
            Link(
                id="sec-l1",
                endpoints=("core-1", "srv-1"),
                capacity_mbps=1000.0,
                cost=1.0,
            )
        ],
    )
    vlan_plan = VlanPlanResult(
        assignments=[
            VlanAssignment(
                department="network operations",
                vlan_id=10,
                vlan_name="Management",
                subnet_name="mgmt",
                network="10.10.0.0/24",
                purpose="device management",
            ),
            VlanAssignment(
                department="public web",
                vlan_id=20,
                vlan_name="Web DMZ",
                subnet_name="dmz-web",
                network="10.20.0.0/24",
                purpose="internet-facing services",
            ),
            VlanAssignment(
                department="guest services",
                vlan_id=30,
                vlan_name="Guest",
                subnet_name="guest",
                network="10.30.0.0/24",
                purpose="visitor access",
            ),
            VlanAssignment(
                department="building sensors",
                vlan_id=40,
                vlan_name="IoT",
                subnet_name="iot",
                network="10.40.0.0/24",
                purpose="camera network",
            ),
            VlanAssignment(
                department="application team",
                vlan_id=50,
                vlan_name="App Servers",
                subnet_name="server-apps",
                network="10.50.0.0/24",
                purpose="backend services",
            ),
            VlanAssignment(
                department="office staff",
                vlan_id=60,
                vlan_name="Corporate Users",
                subnet_name="users",
                network="10.60.0.0/24",
                purpose="employee access",
            ),
            VlanAssignment(
                department="external partner",
                vlan_id=70,
                vlan_name="WAN",
                subnet_name="external",
                network="10.70.0.0/24",
                purpose="wan transport",
            ),
            VlanAssignment(
                department="unknown",
                vlan_id=80,
                vlan_name="Misc",
                subnet_name="misc",
                network="10.80.0.0/24",
                purpose="unclassified",
            ),
        ]
    )
    return make_twin(
        metadata=make_twin().metadata.model_copy(update={"name": "Keyword twin"}),
        topology=topology,
        vlan_plan=vlan_plan,
        addressing=None,
        dhcp_scopes=(),
        demands=(),
        assumptions=(),
    )


def simple_secured_twin() -> DigitalTwin:
    """Return a twin with a small, explicit policy used by operation tests."""
    model = SecurityModel(
        zones=(
            make_zone("z-user", vlan_id=10),
            make_zone("z-server", zone_type=ZoneType.server, vlan_id=20),
            make_zone("z-mgmt", zone_type=ZoneType.management, vlan_id=30),
            make_zone("z-guest", zone_type=ZoneType.guest, vlan_id=40),
        ),
        services=(make_service("http"),),
        rules=(make_rule("allow-web", order=0, src_zone="z-user", dst_zone="z-server"),),
        default_action=PolicyAction.deny,
    )
    from security import set_security_model

    return set_security_model(make_twin(), model)


__all__ = [
    "CREATED_AT",
    "keyword_twin",
    "make_rule",
    "make_service",
    "make_zone",
    "simple_secured_twin",
]
