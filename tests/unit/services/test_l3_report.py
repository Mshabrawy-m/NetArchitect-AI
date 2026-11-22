"""Report coverage for optional L1-L4 modeled L3 design sections.

Hand checks: a ``/48`` holds ``2**(64-48) = 65536`` ``/64`` prefixes, and one
PAT pool address with ``65535 - 1024 + 1 = 64512`` usable ports can hold 508
modeled sessions for 254 hosts at two sessions each.
"""

from __future__ import annotations

from datetime import UTC, datetime

from network.addressing.dual_stack import plan_dual_stack, requests_from_plan
from network.addressing.nat import NatPlan, NatRule, NatType
from network.routing.ha import HaGroup, HaMember
from network.routing.ospf import OspfArea, OspfDesign
from services.reporting import ReportSources, build_report, check_consistency
from tests.unit.digital_twin.helpers import make_twin

GENERATED_AT = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

L3_SECTIONS = (
    "ipv6_dual_stack",
    "nat_plan",
    "ospf_area_design",
    "gateway_redundancy",
)


def _l3_twin():  # type: ignore[no-untyped-def]
    twin = make_twin()
    dual_stack = plan_dual_stack("fd00::/48", requests_from_plan(twin.addressing))
    nat = NatPlan(
        rules=(
            NatRule(
                id="nat-1",
                name="Users to internet",
                nat_type=NatType.pat_overload,
                inside_zone="users",
                inside_subnets=("10.0.0.0/24",),
                outside_pools=("203.0.113.10/32",),
                inside_hosts=254,
                sessions_per_host=2,
            ),
        )
    )
    ospf = OspfDesign(
        areas=(
            OspfArea(area_id=0, name="Backbone", device_ids=("r1",)),
            OspfArea(area_id=10, name="Users", device_ids=("r1", "sw1")),
        )
    )
    gateway = (
        HaGroup(
            id="gw-1",
            name="User gateway",
            virtual_ip="10.0.0.1",
            subnet="10.0.0.0/24",
            vlan_id=10,
            members=(
                HaMember(device_id="r1", priority=150, vlan_ids=(10,)),
                HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
            ),
        ),
    )
    return twin.model_copy(
        update={
            "ipv6_plan": dual_stack,
            "nat_plan": nat,
            "ospf_design": ospf,
            "ha_groups": gateway,
        }
    )


def _value(document, key: str):  # type: ignore[no-untyped-def]
    return next(record for record in document.values if record.key == key)


def test_l3_sections_are_available_and_consistency_passes() -> None:
    twin = _l3_twin()
    # Hand: two IPv4 subnets carve two /64 prefixes from the /48.
    assert (
        twin.ipv6_plan.prefixes_used,
        twin.ipv6_plan.prefixes_available,
    ) == (2, 65536)

    document = build_report(ReportSources(twin=twin, generated_at=GENERATED_AT))
    result = check_consistency(document)

    assert result.ok, [(item.code, item.message) for item in result.errors]
    for section_id in L3_SECTIONS:
        section = document.section(section_id)
        assert section is not None
        assert section.status.value == "available"
        assert section.blocks
        assert section.producer_page == ""
    assert _value(document, "ipv6.prefixes_available").numeric == 65536
    assert _value(document, "nat.sizing.0.sessions").numeric == 508
    assert _value(document, "nat.sizing.0.capacity").numeric == 64512
    assert _value(document, "ospf.areas").numeric == 2
    assert _value(document, "ha.groups").numeric == 1


def test_l3_sections_without_plans_are_not_run() -> None:
    document = build_report(
        ReportSources(twin=make_twin(), generated_at=GENERATED_AT)
    )

    assert check_consistency(document).ok
    for section_id in L3_SECTIONS:
        section = document.section(section_id)
        assert section is not None
        assert section.status.value == "not_run"
        assert section.producer_page == "L3 Design"
        assert section.unavailable_reason
        assert section.blocks == ()
