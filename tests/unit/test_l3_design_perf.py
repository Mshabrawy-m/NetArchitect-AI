"""Opt-in timing checks for the L1-L4 modeled L3 design engines.

Run explicitly with ``pytest -q -m perf -o addopts= tests/unit/test_l3_design_perf.py -s``.
The sizes come from ``config.limits``; each check is bounded by those limits and
prints its measured time for the final report. No runtime limit is asserted:
these numbers are evidence, not acceptance thresholds.
"""

from __future__ import annotations

from time import perf_counter

import pytest

from config.limits import (
    MAX_HA_GROUPS,
    MAX_HA_MEMBERS,
    MAX_NAT_RULES,
    MAX_OSPF_AREAS,
    MAX_V6_PREFIXES,
)
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from network.addressing import (
    DualStackRequest,
    NatPlan,
    NatRule,
    NatType,
    plan_dual_stack,
    validate_dual_stack,
)
from network.addressing.nat import analyze_nat_plan
from network.routing import (
    HaGroup,
    HaMember,
    OspfArea,
    OspfDesign,
    analyze_ha_groups,
    analyze_ospf_design,
)

pytestmark = pytest.mark.perf


def test_l1_max_v6_prefixes_timing() -> None:
    # Hand: MAX_V6_PREFIXES distinct /64 assignments fit in a /48 because
    # 2**(64-48) = 65536, so this exercises the configured size exactly.
    requests = tuple(
        DualStackRequest(name=f"vlan-{index}", vlan_id=index + 1)
        for index in range(MAX_V6_PREFIXES)
    )
    started = perf_counter()
    plan = plan_dual_stack("2001:db8::/48", requests)
    findings = validate_dual_stack("2001:db8::/48", plan)
    elapsed = perf_counter() - started

    assert len(plan.assignments) == MAX_V6_PREFIXES
    assert plan.prefixes_available == 65536
    assert not findings
    print(
        f"L1 max-v6-prefixes ({MAX_V6_PREFIXES}): {elapsed:.4f}s"
    )


def test_l2_max_nat_rules_timing() -> None:
    # Hand: each /24 contributes 254 modeled hosts; each /28 pool contributes
    # 16 addresses, so 254 PAT sessions fit easily in 16 x 64512 ports.
    rules = tuple(
        NatRule(
            id=f"nat-{index}",
            name=f"rule-{index}",
            nat_type=NatType.pat_overload,
            inside_zone=f"zone-{index}",
            inside_subnets=(f"10.0.{index}.0/24",),
            outside_pools=(
                f"198.51.{index // 16}.{(index % 16) * 16}/28",
            ),
            inside_hosts=254,
        )
        for index in range(MAX_NAT_RULES)
    )
    started = perf_counter()
    analysis = analyze_nat_plan(NatPlan(rules=rules))
    elapsed = perf_counter() - started

    assert len(analysis.sizings) == MAX_NAT_RULES
    assert analysis.findings == ()
    print(f"L2 max-nat-rules ({MAX_NAT_RULES}): {elapsed:.4f}s")


def test_l3_max_ospf_areas_timing() -> None:
    devices = tuple(
        Device(
            id=f"r{index}",
            type=DeviceType.router,
            site="campus",
            role=DeviceRole.core if index == 0 else DeviceRole.distribution,
        )
        for index in range(MAX_OSPF_AREAS + 2)
    )
    links = tuple(
        Link(
            id=f"l-{index}",
            endpoints=(f"r{index}", f"r{index + 1}"),
            capacity_mbps=1000.0,
            cost=1.0,
        )
        for index in range(MAX_OSPF_AREAS + 1)
    )
    topology = Topology(name="max-ospf", devices=devices, links=links)
    # Hand: area 0 and MAX_OSPF_AREAS-1 non-backbone areas are exactly the
    # configured area limit; r0 is the single attached ABR for every area.
    areas = (
        OspfArea(area_id=0, name="Backbone", device_ids=("r0",)),
        *(
            OspfArea(
                area_id=index,
                name=f"Area {index}",
                device_ids=("r0", f"r{index}"),
            )
            for index in range(1, MAX_OSPF_AREAS)
        ),
    )
    design = OspfDesign(areas=areas, reference_bandwidth_mbps=1000.0)

    started = perf_counter()
    analysis = analyze_ospf_design(design, topology)
    elapsed = perf_counter() - started

    # Hand: r0 plus r1..r31 are the 32 area members; r32 is intentionally
    # outside every area so an unmodeled device does not become a router.
    assert len(analysis.routers) == MAX_OSPF_AREAS
    assert len(analysis.link_costs) == MAX_OSPF_AREAS + 1
    print(f"L3 max-ospf-areas ({MAX_OSPF_AREAS}): {elapsed:.4f}s")


def test_l4_max_ha_groups_and_members_timing() -> None:
    devices = tuple(
        Device(
            id=f"gw-{index:03d}",
            type=DeviceType.router,
            site="campus",
            role=DeviceRole.distribution,
        )
        for index in range(MAX_HA_GROUPS * MAX_HA_MEMBERS)
    )
    topology = Topology(name="max-ha", devices=devices, links=())
    groups = tuple(
        HaGroup(
            id=f"group-{group_index}",
            name=f"Group {group_index}",
            virtual_ip=f"10.{group_index}.0.1",
            subnet=f"10.{group_index}.0.0/24",
            members=tuple(
                HaMember(
                    device_id=f"gw-{group_index * MAX_HA_MEMBERS + member_index:03d}",
                    priority=200 - member_index,
                )
                for member_index in range(MAX_HA_MEMBERS)
            ),
        )
        for group_index in range(MAX_HA_GROUPS)
    )

    started = perf_counter()
    analysis = analyze_ha_groups(groups, topology)
    elapsed = perf_counter() - started

    assert len(analysis.active_members) == MAX_HA_GROUPS
    assert analysis.findings == ()
    print(
        f"L4 max-ha-groups ({MAX_HA_GROUPS} x {MAX_HA_MEMBERS}): "
        f"{elapsed:.4f}s"
    )
