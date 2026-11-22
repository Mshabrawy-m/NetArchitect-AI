"""L4 tests for modeled first-hop gateway redundancy design rules."""

from __future__ import annotations

import pytest

from config.limits import MAX_HA_GROUPS, MAX_HA_MEMBERS
from core.exceptions import LimitsExceededError
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from network.routing import (
    HaGroup,
    HaMember,
    active_member,
    analyze_ha_groups,
)


def _device(device_id: str) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.router,
        site="campus",
        role=DeviceRole.distribution,
    )


def _link(link_id: str, start: str, end: str) -> Link:
    return Link(endpoints=(start, end), id=link_id, capacity_mbps=100.0, cost=1.0)


def _group(**overrides: object) -> HaGroup:
    defaults: dict[str, object] = {
        "id": "gw",
        "name": "Users gateway",
        "virtual_ip": "10.0.1.1",
        "subnet": "10.0.1.0/24",
        "vlan_id": 10,
        "members": (
            HaMember(device_id="r1", priority=150, vlan_ids=(10,)),
            HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
        ),
    }
    defaults.update(overrides)
    return HaGroup.model_validate(defaults)


def _codes(analysis: object) -> set[str]:
    return {finding.code for finding in analysis.findings}  # type: ignore[attr-defined]


def test_election_uses_priority_then_device_id_and_skips_failed() -> None:
    group = _group()
    # Hand: r1 has priority 150 > r2 100, so r1 is nominal active.
    assert active_member(group).device_id == "r1"  # type: ignore[union-attr]
    # Hand: r1 modeled down -> r2 (priority 100) takes over.
    assert active_member(group, failed_devices={"r1"}).device_id == "r2"  # type: ignore[union-attr]
    assert active_member(group, failed_devices={"r1", "r2"}) is None

    tie = _group(
        members=(
            HaMember(device_id="z", priority=100),
            HaMember(device_id="a", priority=100),
        )
    )
    # Hand: equal priority 100, lexicographically lowest id 'a' wins.
    assert active_member(tie).device_id == "a"  # type: ignore[union-attr]


def test_vip_rules_and_collisions_are_typed_findings() -> None:
    topology = Topology(
        name="vip",
        devices=[_device("r1"), _device("r2")],
        links=[_link("l1", "r1", "r2")],
    )
    outside = analyze_ha_groups((_group(virtual_ip="10.9.9.1"),), topology)
    assert "ha_vip_outside_subnet" in _codes(outside)

    network_address = analyze_ha_groups((_group(virtual_ip="10.0.1.0"),), topology)
    assert "ha_vip_collision" in _codes(network_address)

    reserved = analyze_ha_groups(
        (_group(reserved_addresses=("10.0.1.1",)),), topology
    )
    assert "ha_vip_collision" in _codes(reserved)

    duplicate = analyze_ha_groups(
        (
            _group(id="gw-a"),
            _group(id="gw-b"),
        ),
        topology,
    )
    assert "ha_vip_collision" in _codes(duplicate)


def test_member_attachment_priority_and_single_member_rules() -> None:
    topology = Topology(name="members", devices=[_device("r1"), _device("r2")], links=[])
    bad_vlan = analyze_ha_groups(
        (
            _group(
                members=(
                    HaMember(device_id="r1", priority=150, vlan_ids=(20,)),
                    HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
                )
            ),
        ),
        topology,
    )
    assert "ha_member_not_on_vlan" in _codes(bad_vlan)

    tie = analyze_ha_groups(
        (
            _group(
                members=(
                    HaMember(device_id="r1", priority=100, vlan_ids=(10,)),
                    HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
                )
            ),
        ),
        topology,
    )
    codes = _codes(tie)
    assert "ha_priority_tie" in codes
    assert "ha_preempt_disabled" not in codes

    single = analyze_ha_groups(
        (_group(members=(HaMember(device_id="r1", priority=100, vlan_ids=(10,)),)),),
        topology,
    )
    assert "ha_single_member" in _codes(single)

    unknown = analyze_ha_groups(
        (
            _group(
                members=(
                    HaMember(device_id="r1", priority=150, vlan_ids=(10,)),
                    HaMember(device_id="ghost", priority=100, vlan_ids=(10,)),
                )
            ),
        ),
        topology,
    )
    assert "ha_unknown_member" in _codes(unknown)


def test_shared_fate_uses_single_common_upstream_neighbor() -> None:
    shared = Topology(
        name="shared-uplink",
        devices=[_device("r1"), _device("r2"), _device("upstream")],
        links=[_link("u1", "upstream", "r1"), _link("u2", "upstream", "r2")],
    )
    finding = next(
        finding
        for finding in analyze_ha_groups((_group(),), shared).findings
        if finding.code == "ha_shared_fate_uplink"
    )
    assert finding.affected_entities == ["gw", "upstream"]

    redundant = Topology(
        name="redundant-uplink",
        devices=[*_shared_devices(), _device("second")],
        links=[
            _link("u1", "upstream", "r1"),
            _link("u2", "upstream", "r2"),
            _link("u3", "second", "r2"),
        ],
    )
    assert "ha_shared_fate_uplink" not in _codes(
        analyze_ha_groups((_group(),), redundant)
    )


def _shared_devices() -> list[Device]:
    return [_device("r1"), _device("r2"), _device("upstream")]


def test_preempt_flag_is_recorded_as_info_only() -> None:
    topology = Topology(
        name="preempt", devices=[_device("r1"), _device("r2")], links=[]
    )
    analysis = analyze_ha_groups((_group(preempt=False),), topology)
    finding = next(
        finding for finding in analysis.findings if finding.code == "ha_preempt_disabled"
    )
    # Hand: preempt=false is modeled metadata, not a blocking design error.
    assert finding.severity.value == "info"
    assert analysis.active_members == {"gw": "r1"}


def test_ha_group_and_member_limits_are_enforced() -> None:
    topology = Topology(name="limits", devices=[_device("r1")], links=[])
    too_many_groups = tuple(
        _group(id=f"gw-{index}") for index in range(MAX_HA_GROUPS + 1)
    )
    with pytest.raises(LimitsExceededError, match="limit is"):
        analyze_ha_groups(too_many_groups, topology)

    too_many_members = _group(
        members=tuple(
            HaMember(device_id=f"m{index}", priority=index)
            for index in range(MAX_HA_MEMBERS + 1)
        )
    )
    with pytest.raises(LimitsExceededError, match="limit is"):
        analyze_ha_groups((too_many_members,), topology)
