"""Pure model validation tests for the design-time security package."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.limits import MAX_FIREWALL_RULES, MAX_SERVICES, MAX_ZONES
from security import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Zone,
    ZoneType,
)

from .helpers import make_rule, make_service, make_zone


def test_zone_requires_a_member_and_canonicalizes_ids() -> None:
    zone = make_zone(
        vlan_id=None,
        device_id="sw-2",
    ).model_copy(update={"member_device_ids": ("sw-2", "sw-1", "sw-1")})

    validated = Zone.model_validate(zone.model_dump())

    assert validated.member_device_ids == ("sw-1", "sw-2")
    with pytest.raises(ValidationError, match="must name at least one"):
        Zone(id="empty", name="Empty", type=ZoneType.other, criticality=3)


def test_zone_criticality_is_bounded() -> None:
    for invalid in (0, 6):
        with pytest.raises(ValidationError):
            make_zone(f"z-{invalid}", criticality=invalid)


def test_service_validates_ranges_and_matches_modeled_flows() -> None:
    http = make_service()
    assert http.matches(Protocol.tcp, 80)
    assert not http.matches(Protocol.tcp, 81)
    assert not http.matches(Protocol.udp, 80)

    any_service = make_service("any", protocol=Protocol.any, port_start=0, port_end=0)
    assert any_service.matches(Protocol.udp, 9999)

    with pytest.raises(ValidationError, match="after"):
        make_service("bad-range", port_start=443, port_end=80)
    with pytest.raises(ValidationError, match="must be 0-0"):
        make_service("bad-icmp", protocol=Protocol.icmp, port_start=1, port_end=1)


def test_firewall_rule_requires_exactly_one_service_mode() -> None:
    with pytest.raises(ValidationError, match="must set any_service"):
        FirewallRule(id="r", order=0, src_zone="a", dst_zone="b")
    with pytest.raises(ValidationError, match="cannot set any_service"):
        FirewallRule(
            id="r",
            order=0,
            src_zone="a",
            dst_zone="b",
            services=("http",),
            any_service=True,
        )

    rule = make_rule(services=("ssh", "http"))
    assert rule.services == ("http", "ssh")
    assert rule.action is PolicyAction.allow


def test_security_model_rejects_duplicate_identities_and_orders() -> None:
    base = make_zone("z1", vlan_id=10)
    duplicate_zone = base.model_copy(update={"name": "Duplicate"})
    with pytest.raises(ValidationError, match="zone ids must be unique"):
        SecurityModel(zones=(base, duplicate_zone))

    with pytest.raises(ValidationError, match="service names must be unique"):
        SecurityModel(services=(make_service("http"), make_service("http")))

    with pytest.raises(ValidationError, match="rule ids must be unique"):
        SecurityModel(rules=(make_rule("r1"), make_rule("r1", order=1)))

    with pytest.raises(ValidationError, match="rule orders must be unique"):
        SecurityModel(rules=(make_rule("r1"), make_rule("r2")))


def test_security_model_enforces_declared_bounds() -> None:
    zones = tuple(
        make_zone(f"z-{index}", vlan_id=index + 1) for index in range(MAX_ZONES)
    )
    services = tuple(
        make_service(f"svc-{index}", port_start=1000 + index, port_end=1000 + index)
        for index in range(MAX_SERVICES)
    )
    rules = tuple(
        make_rule(f"r-{index}", order=index) for index in range(MAX_FIREWALL_RULES)
    )
    SecurityModel(zones=zones, services=services, rules=rules)

    with pytest.raises(ValidationError):
        SecurityModel(
            zones=zones + (make_zone("too-many", vlan_id=MAX_ZONES + 1),)
        )
    with pytest.raises(ValidationError):
        SecurityModel(
            services=services
            + (make_service("too-many", port_start=2000, port_end=2000),)
        )
    with pytest.raises(ValidationError):
        SecurityModel(
            rules=rules
            + (
                make_rule(
                    "too-many",
                    order=MAX_FIREWALL_RULES,
                    services=("svc-0",),
                ),
            )
        )
