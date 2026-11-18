"""Deterministic default-zone derivation tests."""

from __future__ import annotations

from security import (
    SECURITY_DISCLAIMER,
    PolicyAction,
    ZoneType,
    derive_default_security_model,
)

from .helpers import keyword_twin


def test_default_derivation_is_reproducible_and_labeled() -> None:
    twin = keyword_twin()

    first = derive_default_security_model(twin)
    second = derive_default_security_model(twin)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert twin.security is None
    assert first.default_action is PolicyAction.deny
    assert first.assumptions
    assert SECURITY_DISCLAIMER == (
        "Modeled design-time assessment. Not a vulnerability scan, penetration "
        "test or audit."
    )


def test_keyword_groups_and_priority_build_expected_zones() -> None:
    model = derive_default_security_model(keyword_twin())
    by_type = {zone.type: zone for zone in model.zones}

    assert set(by_type) == {
        ZoneType.management,
        ZoneType.dmz,
        ZoneType.guest,
        ZoneType.iot,
        ZoneType.server,
        ZoneType.user,
        ZoneType.untrusted_external,
    }
    # "public web" contains both DMZ and server keywords; DMZ has priority.
    assert by_type[ZoneType.dmz].member_vlan_ids == (20,)
    assert 20 not in by_type[ZoneType.server].member_vlan_ids
    assert by_type[ZoneType.management].member_vlan_ids == (10,)
    assert by_type[ZoneType.guest].member_vlan_ids == (30,)
    assert by_type[ZoneType.iot].member_vlan_ids == (40,)
    assert by_type[ZoneType.user].member_vlan_ids == (60,)
    assert by_type[ZoneType.untrusted_external].member_vlan_ids == (70,)
    # Unmatched VLAN 80 and core router "core-1" stay unassigned by design.
    assigned_vlans = {
        vlan for zone in model.zones for vlan in zone.member_vlan_ids
    }
    assigned_devices = {
        device for zone in model.zones for device in zone.member_device_ids
    }
    assert 80 not in assigned_vlans
    assert "core-1" not in assigned_devices
    assert "srv-1" in assigned_devices
    assert "ctrl-1" in assigned_devices


def test_derived_default_rules_cover_guest_and_iot_boundaries() -> None:
    model = derive_default_security_model(keyword_twin())

    assert [(rule.order, rule.id) for rule in model.ordered_rules] == [
        (0, "derived-deny-guest-server"),
        (1, "derived-deny-guest-management"),
        (2, "derived-deny-iot-server"),
        (3, "derived-deny-iot-management"),
    ]
    assert all(rule.action is PolicyAction.deny for rule in model.rules)
    assert all(rule.any_service for rule in model.rules)
