"""Design-health coverage for optional L3 design models.

Hand checks use the documented formulas: a /48 holds 2**(64-48) = 65536 /64
prefixes; a PAT pool of one address with 64512 ports cannot hold 64513
modeled sessions.
"""

from __future__ import annotations

from core.schemas.validation import Severity
from network.addressing.dual_stack import plan_dual_stack, requests_from_plan
from network.addressing.nat import NatPlan, NatRule, NatType
from network.routing.ha import HaGroup, HaMember
from network.routing.ospf import OspfArea, OspfDesign
from services.validation import ValidationCategory, build_design_health
from tests.unit.digital_twin.helpers import make_twin


def _codes(health, category: ValidationCategory) -> set[str]:  # type: ignore[no-untyped-def]
    return {item.code for item in health.findings_for(category)}


def test_optional_l3_categories_are_present_but_empty_by_default() -> None:
    health = build_design_health(make_twin())

    categories = {group.category for group in health.groups}
    for category in (
        ValidationCategory.dual_stack,
        ValidationCategory.nat,
        ValidationCategory.ospf,
        ValidationCategory.ha,
    ):
        assert category in categories
        assert health.findings_for(category) == ()
    assert "IPv6 dual-stack" in health.notes[0]
    assert "OSPF area design" in health.notes[0]


def test_dual_stack_findings_use_prefix_not_host_utilization() -> None:
    twin = make_twin()
    plan = plan_dual_stack("fd00::/48", requests_from_plan(twin.addressing))
    # Hand: two IPv4 subnets (users/10 and transit) each carve one /64.
    assert (plan.prefixes_used, plan.prefixes_available) == (2, 65536)
    assert plan.utilization_percent == 0.0

    health = build_design_health(twin.model_copy(update={"ipv6_plan": plan}))

    assert _codes(health, ValidationCategory.dual_stack) == {
        "ipv6_scope_unique_local"
    }


def test_nat_capacity_error_is_a_basic_check() -> None:
    twin = make_twin()
    plan = NatPlan(
        rules=(
            NatRule(
                id="r1",
                name="Overloaded",
                nat_type=NatType.pat_overload,
                inside_zone="users",
                inside_subnets=("10.0.0.0/24",),
                outside_pools=("203.0.113.1/32",),
                inside_hosts=64513,  # hand: one more than 64512 ports
            ),
        )
    )

    health = build_design_health(twin.model_copy(update={"nat_plan": plan}))

    assert "nat_pat_port_capacity_exceeded" in _codes(health, ValidationCategory.nat)
    assert not health.include_expensive


def test_ospf_and_ha_findings_are_basic_and_categorized() -> None:
    twin = make_twin()
    design = OspfDesign(
        areas=(OspfArea(area_id=10, name="Users", device_ids=("sw1",)),)
    )
    groups = (
        HaGroup(
            id="gw",
            name="Gateway",
            virtual_ip="10.0.10.1",
            subnet="10.0.10.0/24",
            members=(HaMember(device_id="r1", priority=100),),
        ),
    )

    health = build_design_health(
        twin.model_copy(update={"ospf_design": design, "ha_groups": groups})
    )

    assert {"ospf_no_backbone", "ospf_virtual_link_needed"} <= _codes(
        health, ValidationCategory.ospf
    )
    assert {"ha_single_member", "ha_shared_fate_uplink"} <= _codes(
        health, ValidationCategory.ha
    )
    assert any(
        finding.severity is Severity.error
        for finding in health.findings_for(ValidationCategory.ospf)
    )


def test_expensive_toggle_still_controls_only_all_pairs_and_spof() -> None:
    twin = make_twin(ipv6_plan=plan_dual_stack("fd00::/48", []))
    basic = build_design_health(twin)
    expensive = build_design_health(twin, include_expensive=True)

    assert basic.findings_for(ValidationCategory.dual_stack)
    assert (
        basic.findings_for(ValidationCategory.dual_stack)
        == expensive.findings_for(ValidationCategory.dual_stack)
    )
    assert expensive.include_expensive
    assert "all-pairs" in expensive.notes[1].lower()
