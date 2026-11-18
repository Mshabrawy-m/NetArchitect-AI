"""Design fixtures for deterministic security-engine tests."""

from __future__ import annotations

from core.schemas.addressing import AddressingPlan, Subnet, VlanPlan
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from digital_twin import DigitalTwin, set_topology
from security import (
    FirewallRule,
    PolicyAction,
    SecurityModel,
    Zone,
    ZoneType,
    set_security_model,
)
from tests.unit.digital_twin.helpers import make_twin

from .helpers import make_rule, make_service, make_zone

DEVICE_IDS = (
    "ext-rtr",
    "fw-1",
    "fw-2",
    "mgmt-sw",
    "srv-app",
    "web-01",
    "user-sw",
    "guest-sw",
    "iot-sw",
)


def _topology(*, include_fw2: bool = True) -> Topology:
    devices = [
        Device(id="ext-rtr", type=DeviceType.router, site="hq", role=DeviceRole.core),
        Device(id="fw-1", type=DeviceType.firewall, site="hq", role=DeviceRole.border),
        Device(id="mgmt-sw", type=DeviceType.layer3_switch, site="hq", role=DeviceRole.core),
        Device(id="srv-app", type=DeviceType.server, site="hq", role=DeviceRole.access),
        Device(id="web-01", type=DeviceType.server, site="hq", role=DeviceRole.dmz),
        Device(id="user-sw", type=DeviceType.switch, site="hq", role=DeviceRole.access),
        Device(id="guest-sw", type=DeviceType.switch, site="hq", role=DeviceRole.access),
        Device(id="iot-sw", type=DeviceType.switch, site="hq", role=DeviceRole.access),
    ]
    if include_fw2:
        devices.insert(
            2,
            Device(
                id="fw-2",
                type=DeviceType.firewall,
                site="hq",
                role=DeviceRole.border,
            ),
        )

    links: list[Link] = []
    link_id = 0

    def add(source: str, target: str) -> None:
        nonlocal link_id
        link_id += 1
        links.append(
            Link(
                id=f"sl-{link_id}",
                endpoints=(source, target),
                capacity_mbps=1000.0,
                cost=1.0,
            )
        )

    add("ext-rtr", "fw-1")
    for target in ("mgmt-sw", "srv-app", "web-01", "user-sw", "guest-sw", "iot-sw"):
        add("fw-1", target)
    if include_fw2:
        add("ext-rtr", "fw-2")
        add("fw-1", "fw-2")
        for target in ("mgmt-sw", "srv-app", "web-01", "user-sw", "guest-sw", "iot-sw"):
            add("fw-2", target)
    return Topology(name="Hardened security campus", devices=devices, links=links)


def _zones(*, all_on_one: bool = False) -> tuple[Zone, ...]:
    if all_on_one:
        return (
            Zone(
                id="z-flat",
                name="Flat",
                type=ZoneType.other,
                criticality=3,
                member_device_ids=DEVICE_IDS,
            ),
        )
    return (
        make_zone("z-ext", zone_type=ZoneType.untrusted_external, vlan_id=None, device_id="ext-rtr", criticality=2),
        make_zone("z-dmz", zone_type=ZoneType.dmz, vlan_id=None, device_id="fw-1", criticality=3).model_copy(
            update={"member_device_ids": ("fw-1", "fw-2", "web-01")}
        ),
        make_zone("z-srv", zone_type=ZoneType.server, vlan_id=None, device_id="srv-app", criticality=4),
        make_zone("z-mgmt", zone_type=ZoneType.management, vlan_id=None, device_id="mgmt-sw", criticality=5),
        make_zone("z-user", zone_type=ZoneType.user, vlan_id=None, device_id="user-sw", criticality=3),
        make_zone("z-guest", zone_type=ZoneType.guest, vlan_id=None, device_id="guest-sw", criticality=1),
        make_zone("z-iot", zone_type=ZoneType.iot, vlan_id=None, device_id="iot-sw", criticality=2),
    )


def _deny(rule_id: str, order: int, src: str, dst: str) -> FirewallRule:
    return make_rule(
        rule_id,
        order=order,
        src_zone=src,
        dst_zone=dst,
        services=(),
        any_service=True,
        action=PolicyAction.deny,
    )


def _rules() -> tuple[FirewallRule, ...]:
    return (
        _deny("deny-user-mgmt", 0, "z-user", "z-mgmt"),
        _deny("deny-user-srv", 1, "z-user", "z-srv"),
        _deny("deny-guest-dmz", 2, "z-guest", "z-dmz"),
        _deny("deny-guest-srv", 3, "z-guest", "z-srv"),
        _deny("deny-guest-mgmt", 4, "z-guest", "z-mgmt"),
        _deny("deny-guest-user", 5, "z-guest", "z-user"),
        _deny("deny-iot-dmz", 6, "z-iot", "z-dmz"),
        _deny("deny-iot-srv", 7, "z-iot", "z-srv"),
        _deny("deny-iot-mgmt", 8, "z-iot", "z-mgmt"),
        _deny("deny-iot-user", 9, "z-iot", "z-user"),
        _deny("deny-srv-mgmt", 10, "z-srv", "z-mgmt"),
        _deny("deny-mgmt-srv", 11, "z-mgmt", "z-srv"),
    )


def hardened_design() -> tuple[DigitalTwin, SecurityModel]:
    twin = make_twin(
        topology=_topology(),
        addressing=None,
        vlan_plan=None,
        dhcp_scopes=(),
        demands=(),
        assumptions=(),
    )
    model = SecurityModel(
        zones=_zones(),
        services=(make_service("http"),),
        rules=_rules(),
        default_action=PolicyAction.deny,
    )
    return set_security_model(twin, model), model


def _replace_zone(
    model: SecurityModel, zone_id: str, **changes: object
) -> SecurityModel:
    zones = tuple(
        zone.model_copy(update=changes) if zone.id == zone_id else zone
        for zone in model.zones
    )
    return model.model_copy(update={"zones": zones})


def _without_rules(model: SecurityModel, rule_ids: set[str]) -> SecurityModel:
    rules = tuple(rule for rule in model.rules if rule.id not in rule_ids)
    return model.model_copy(update={"rules": rules})


def case_design(rule_id: str) -> tuple[DigitalTwin, SecurityModel]:
    """Return a deterministic twin/model pair that triggers ``rule_id``."""
    twin, model = hardened_design()

    if rule_id == "SEC-DW-001":
        flat = SecurityModel(
            zones=_zones(all_on_one=True),
            services=(),
            rules=(),
            default_action=PolicyAction.deny,
        )
        return set_security_model(twin, flat), flat

    if rule_id == "SEC-DW-002":
        candidate = _replace_zone(model, "z-mgmt", type=ZoneType.server)
        return set_security_model(twin, candidate), candidate

    if rule_id == "SEC-DW-003":
        candidate = _replace_zone(
            model, "z-dmz", member_device_ids=("fw-1", "fw-2")
        )
        candidate = _replace_zone(
            candidate, "z-srv", member_device_ids=("srv-app", "web-01")
        )
        return set_security_model(twin, candidate), candidate

    if rule_id == "SEC-DW-004":
        candidate = _without_rules(model, {"deny-user-mgmt", "deny-user-srv"})
        return set_security_model(twin, candidate), candidate

    if rule_id == "SEC-DW-005":
        candidate = _without_rules(model, {"deny-guest-srv"})
        allow_guest = make_rule(
            "allow-guest-srv",
            order=3,
            src_zone="z-guest",
            dst_zone="z-srv",
            services=(),
            any_service=True,
            action=PolicyAction.allow,
        )
        rules = candidate.rules + (allow_guest,)
        candidate = candidate.model_copy(update={"rules": rules})
        return set_security_model(twin, candidate), candidate

    if rule_id == "SEC-DW-006":
        topology = twin.topology.model_copy(
            update={
                "devices": tuple(
                    device for device in twin.topology.devices if device.id != "fw-2"
                ),
                "links": tuple(
                    link
                    for link in twin.topology.links
                    if "fw-2" not in link.endpoints
                ),
            }
        )
        reduced_twin = set_topology(twin, topology)
        candidate = _replace_zone(model, "z-dmz", member_device_ids=("fw-1", "web-01"))
        return set_security_model(reduced_twin, candidate), candidate

    if rule_id == "SEC-DW-007":
        candidate = _replace_zone(
            model, "z-user", member_vlan_ids=(60,), expected_hosts=10
        )
        addressing = AddressingPlan(
            vlan_plans=[
                VlanPlan(
                    vlan_id=60,
                    name="Users",
                    subnets=[Subnet(name="users", network="10.60.0.0/24")],
                )
            ]
        )
        addressed_twin = twin.model_copy(update={"addressing": addressing})
        return set_security_model(addressed_twin, candidate), candidate

    if rule_id == "SEC-DW-008":
        candidate = _replace_zone(
            model, "z-iot", member_device_ids=(), member_vlan_ids=(40,)
        )
        return set_security_model(twin, candidate), candidate

    if rule_id == "SEC-DW-009":
        candidate = _without_rules(model, {"deny-srv-mgmt", "deny-mgmt-srv"})
        return set_security_model(twin, candidate), candidate

    raise ValueError(f"No crafted design for {rule_id}")


__all__ = ["case_design", "hardened_design"]
