"""Additive L3 twin fields keep legacy JSON bytes and fingerprints identical.

Hand check: the legacy fixture fingerprint below was recorded before L1-L4
fields existed. Serializing a twin with every new field at its default must
produce the same bytes, and populating any field must change the fingerprint
while preserving an exact round trip.
"""

from __future__ import annotations

import json

from digital_twin import from_json, to_json
from network.addressing.dual_stack import (
    DualStackAssignment,
    DualStackPlan,
    Ipv6Scope,
)
from network.addressing.nat import NatPlan, NatRule, NatType
from network.routing.ha import HaGroup, HaMember
from network.routing.ospf import OspfArea, OspfDesign
from simulation import twin_fingerprint

from .helpers import make_twin

LEGACY_FINGERPRINT = (
    "4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c"
)
_NEW_FIELD_NAMES = ("ipv6_plan", "nat_plan", "ospf_design", "ha_groups")


def _l3_twin():  # type: ignore[no-untyped-def]
    return make_twin().model_copy(
        update={
            "ipv6_plan": DualStackPlan(
                block="fd00::/48",
                prefix_length=64,
                assignments=(
                    DualStackAssignment(
                        name="users",
                        vlan_id=10,
                        index=0,
                        ipv4_network="10.0.10.0/24",
                        ipv6_network="fd00::/64",
                        prefix_length=64,
                        scope=Ipv6Scope.unique_local,
                        origin="auto",
                    ),
                ),
                unallocated=(),
                prefixes_used=1,
                prefixes_available=65536,  # hand: 2**(64-48)
                utilization_percent=0.0,
            ),
            "nat_plan": NatPlan(
                rules=(
                    NatRule(
                        id="nat-1",
                        name="Users to internet",
                        nat_type=NatType.pat_overload,
                        inside_zone="users",
                        inside_subnets=("10.0.10.0/24",),
                        outside_pools=("203.0.113.10/32",),
                    ),
                )
            ),
            "ospf_design": OspfDesign(
                areas=(
                    OspfArea(area_id=0, name="Backbone", device_ids=("r1",)),
                    OspfArea(area_id=10, name="Users", device_ids=("r1", "sw1")),
                )
            ),
            "ha_groups": (
                HaGroup(
                    id="gw-1",
                    name="User gateway",
                    virtual_ip="10.0.10.1",
                    subnet="10.0.10.0/24",
                    vlan_id=10,
                    members=(
                        HaMember(device_id="r1", priority=150, vlan_ids=(10,)),
                        HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
                    ),
                ),
            ),
        }
    )


def _legacy_twin():  # type: ignore[no-untyped-def]
    twin = make_twin()
    metadata = twin.metadata.model_copy(update={"schema_version": 1})
    return twin.model_copy(update={"metadata": metadata})


def test_default_l3_fields_are_omitted_from_legacy_json() -> None:
    payload = to_json(_legacy_twin())
    data = json.loads(payload)

    assert not any(name in data for name in _NEW_FIELD_NAMES)
    assert twin_fingerprint(from_json(payload)) == LEGACY_FINGERPRINT


def test_l3_fields_round_trip_and_change_the_fingerprint() -> None:
    twin = _l3_twin()
    baseline = twin_fingerprint(make_twin())
    payload = to_json(twin)
    data = json.loads(payload)

    assert all(name in data for name in _NEW_FIELD_NAMES)
    restored = from_json(payload)
    assert restored == twin
    assert to_json(restored) == payload
    assert twin_fingerprint(restored) != baseline


def test_each_l3_field_can_be_omitted_independently() -> None:
    full = _l3_twin()
    baseline = _legacy_twin()
    for field in ("ipv6_plan", "nat_plan", "ospf_design", "ha_groups"):
        partial = full.model_copy(update={field: None if field != "ha_groups" else ()})

        payload = to_json(partial)
        restored = from_json(payload)

        assert restored == partial
        assert field not in json.loads(payload)
        assert twin_fingerprint(restored) != twin_fingerprint(full)
        assert twin_fingerprint(baseline) == LEGACY_FINGERPRINT
