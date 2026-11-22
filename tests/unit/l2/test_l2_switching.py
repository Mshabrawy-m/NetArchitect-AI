"""Unit tests for deterministic Layer-2 switching design analysis.

Graph cases are hand-computed with the cycle-rank identity
``cycle_count = edges - vertices + components`` and an ascending
``(cost, link id)`` minimum spanning forest.
"""

from __future__ import annotations

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from digital_twin import LinkState, OperationalState
from network.l2.models import EtherChannelBundle, L2Design, LinkL2Mode
from network.l2.switching import (
    analyze_l2_design,
    bundle_capacity,
    effective_l2_blocked_links,
    links_carrying_vlan,
)
from network.vlan import VlanAssignment, VlanPlanResult
from tests.unit.digital_twin.helpers import make_twin


def _switch(device_id: str) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.switch,
        site="hq",
        role=DeviceRole.access,
    )


def _router(device_id: str) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.router,
        site="hq",
        role=DeviceRole.core,
    )


def _host(device_id: str) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.host,
        site="hq",
        role=DeviceRole.access,
    )


def _trunk(
    link_id: str,
    endpoints: tuple[str, str],
    vlans: tuple[int, ...] = (10,),
    *,
    cost: float = 1.0,
) -> Link:
    return Link(
        id=link_id,
        endpoints=endpoints,
        capacity_mbps=1000.0,
        cost=cost,
        l2_mode=LinkL2Mode.trunk,
        l2_allowed_vlans=vlans,
    )


def _access(link_id: str, endpoints: tuple[str, str], vlan_id: int) -> Link:
    return Link(
        id=link_id,
        endpoints=endpoints,
        capacity_mbps=100.0,
        cost=1.0,
        l2_mode=LinkL2Mode.access,
        l2_access_vlan=vlan_id,
    )


def _plain(link_id: str, endpoints: tuple[str, str], capacity: float = 100.0) -> Link:
    return Link(
        id=link_id,
        endpoints=endpoints,
        capacity_mbps=capacity,
        cost=1.0,
    )


def _plan(*vlan_ids: int) -> VlanPlanResult:
    return VlanPlanResult(
        assignments=[
            VlanAssignment(
                department=f"dept-{vlan_id}",
                vlan_id=vlan_id,
                vlan_name=f"VLAN {vlan_id}",
                subnet_name=f"subnet-{vlan_id}",
                network=f"10.0.{vlan_id}.0/24",
                purpose="L2 unit test",
            )
            for vlan_id in vlan_ids
        ]
    )


def _twin(
    devices: list[Device],
    links: list[Link],
    *,
    vlan_ids: tuple[int, ...] = (10,),
    design: L2Design | None = None,
    link_states: tuple[LinkState, ...] = (),
):  # type: ignore[no-untyped-def]
    return make_twin(
        topology=Topology(name="L2 test", devices=devices, links=links),
        vlan_plan=_plan(*vlan_ids),
        l2_design=design,
        link_states=link_states,
    )


def _triangle_twin(
    link_states: tuple[LinkState, ...] = (),
    *,
    costs: tuple[float, float, float] = (1.0, 1.0, 1.0),
):  # type: ignore[no-untyped-def]
    return _twin(
        [_switch("sw1"), _switch("sw2"), _switch("sw3")],
        [
            _trunk("l_ab", ("sw1", "sw2"), cost=costs[0]),
            _trunk("l_bc", ("sw2", "sw3"), cost=costs[1]),
            _trunk("l_ca", ("sw3", "sw1"), cost=costs[2]),
        ],
        link_states=link_states,
    )


def _codes(analysis) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    return tuple(finding.code for finding in analysis.findings)


def test_triangle_cycle_rank_one_and_exactly_one_blocked_link() -> None:
    twin = _triangle_twin()
    analysis = analyze_l2_design(twin)

    loop = analysis.loops[0]
    # Hand check: E=3, V=3, C=1 => 3-3+1=1 cycle. Equal costs sorted by id
    # give l_ab, l_bc as the spanning tree; l_ca closes the triangle.
    assert loop.vlan_id == 10
    assert loop.cycle_count == 1
    assert loop.component_count == 1
    assert loop.switch_ids == ("sw1", "sw2", "sw3")
    assert loop.carrying_link_ids == ("l_ab", "l_bc", "l_ca")
    assert loop.blocked_link_ids == ("l_ca",)
    assert loop.forwarding_link_ids == ("l_ab", "l_bc")
    assert loop.root_bridge == "sw1"  # all default 32768; lowest id wins
    assert _codes(analysis).count("l2_loop_needs_blocking") == 1
    assert analysis.blocked_link_ids == ("l_ca",)
    assert analysis.effective_link_ids == ("l_ab", "l_bc")

    without_loops = analyze_l2_design(twin, include_loops=False)
    assert without_loops.loops == ()
    assert without_loops.blocked_link_ids == ()
    assert "l2_loop_needs_blocking" not in _codes(without_loops)


def test_mst_uses_cost_before_link_id() -> None:
    # Hand check: l_ab has cost 5 while l_bc/l_ca cost 1. The forest keeps
    # l_bc and l_ca, so l_ab is blocked despite being lexicographically first.
    analysis = analyze_l2_design(_triangle_twin(costs=(5.0, 1.0, 1.0)))
    loop = analysis.loops[0]

    assert loop.cycle_count == 1
    assert loop.blocked_link_ids == ("l_ab",)
    assert loop.forwarding_link_ids == ("l_bc", "l_ca")


def test_root_priority_overrides_default_tie_break() -> None:
    design = L2Design(root_priorities={"sw3": 100, "sw1": 40000})
    analysis = analyze_l2_design(_triangle_twin(), design=design)

    # Hand check: sw3 (100) beats sw1 (40000) and sw2 (default 32768).
    assert analysis.loops[0].root_bridge == "sw3"


def test_square_cycle_rank_one() -> None:
    twin = _twin(
        [_switch(name) for name in ("sw1", "sw2", "sw3", "sw4")],
        [
            _trunk("l_ab", ("sw1", "sw2")),
            _trunk("l_bc", ("sw2", "sw3")),
            _trunk("l_cd", ("sw3", "sw4")),
            _trunk("l_da", ("sw4", "sw1")),
        ],
    )
    loop = analyze_l2_design(twin).loops[0]

    # Hand check: E=4, V=4, C=1 => 4-4+1=1. Kruskal takes l_ab, l_bc, l_cd;
    # l_da is the extra edge and is blocked.
    assert loop.component_count == 1
    assert loop.cycle_count == 1
    assert loop.carrying_link_ids == ("l_ab", "l_bc", "l_cd", "l_da")
    assert loop.blocked_link_ids == ("l_da",)


def test_two_disjoint_triangles_cycle_rank_two() -> None:
    twin = _twin(
        [_switch(name) for name in ("a1", "a2", "a3", "b1", "b2", "b3")],
        [
            _trunk("l_a1_a2", ("a1", "a2")),
            _trunk("l_a2_a3", ("a2", "a3")),
            _trunk("l_a3_a1", ("a3", "a1")),
            _trunk("l_b1_b2", ("b1", "b2")),
            _trunk("l_b2_b3", ("b2", "b3")),
            _trunk("l_b3_b1", ("b3", "b1")),
        ],
    )
    analysis = analyze_l2_design(twin)
    loop = analysis.loops[0]

    # Hand check: E=6, V=6, C=2 => 6-6+2=2. Each triangle blocks its
    # lexicographically last edge after the two cheaper-by-id joins.
    assert loop.component_count == 2
    assert loop.cycle_count == 2
    assert len(loop.switch_ids) == 6
    assert loop.blocked_link_ids == ("l_a3_a1", "l_b3_b1")
    assert len(analysis.blocked_link_ids) == 2
    assert _codes(analysis).count("l2_loop_needs_blocking") == 1


def test_bundle_capacity_math_and_failure_states() -> None:
    bundle = EtherChannelBundle(id="b1", link_ids=("l2", "l1"))
    links = (_plain("l1", ("r1", "r2"), 100.0), _plain("l2", ("r1", "r2"), 200.0))

    healthy = bundle_capacity(bundle, links)
    # Hand check: 100 + 200 = 300 Mbps across two canonicalized members.
    assert healthy.member_link_ids == ("l1", "l2")
    assert healthy.member_speeds_mbps == (100.0, 200.0)
    assert healthy.capacity_mbps == 300.0
    assert healthy.down is False
    assert healthy.failed_member_link_ids == ()

    partially_failed = bundle_capacity(bundle, links, ("l1",))
    # Hand check: the surviving 200 Mbps member is the only contributor.
    assert partially_failed.capacity_mbps == 200.0
    assert partially_failed.failed_member_link_ids == ("l1",)
    assert partially_failed.member_speeds_mbps == (100.0, 200.0)

    all_failed = bundle_capacity(bundle, links, ("l1", "l2"))
    assert all_failed.capacity_mbps == 0.0
    assert all_failed.down is True
    assert all_failed.failed_member_link_ids == ("l1", "l2")


def test_bundle_findings_for_single_member_and_speed_mismatch() -> None:
    design = L2Design(
        etherchannel_bundles=(
            EtherChannelBundle(id="b-mismatch", link_ids=("l100", "l200")),
            EtherChannelBundle(id="b-single", link_ids=("l100", "missing")),
        )
    )
    twin = _twin(
        [_router("r1"), _switch("sw1")],
        [_plain("l100", ("r1", "sw1"), 100.0), _plain("l200", ("r1", "sw1"), 200.0)],
        design=design,
    )
    analysis = analyze_l2_design(twin)

    mismatch = next(
        finding
        for finding in analysis.findings
        if finding.code == "l2_mismatched_bundle_speeds"
    )
    single = next(
        finding
        for finding in analysis.findings
        if finding.code == "l2_single_member_bundle"
    )
    assert mismatch.severity.value == "warning"
    assert mismatch.affected_entities == ["b-mismatch", "l100", "l200"]
    assert single.severity.value == "warning"
    assert single.affected_entities == ["b-single", "l100"]
    assert [bundle.bundle_id for bundle in analysis.bundles] == [
        "b-mismatch",
        "b-single",
    ]
    assert analysis.bundles[0].capacity_mbps == 300.0
    assert analysis.bundles[1].capacity_mbps == 100.0


def test_native_vlan_mismatch_is_an_error() -> None:
    link = _trunk("l_trunk", ("sw1", "sw2"))
    link = link.model_copy(
        update={"l2_native_vlan": 10, "l2_peer_native_vlan": 20}
    )
    analysis = analyze_l2_design(_twin([_switch("sw1"), _switch("sw2")], [link]))

    finding = next(
        item for item in analysis.findings if item.code == "l2_native_vlan_mismatch"
    )
    assert finding.severity.value == "error"
    assert finding.affected_entities[0] == "l_trunk"


def test_access_vlan_outside_plan_is_informational() -> None:
    analysis = analyze_l2_design(
        _twin(
            [_switch("sw1"), _host("h1")],
            [_access("l_acc", ("sw1", "h1"), 99)],
            vlan_ids=(10,),
        )
    )
    finding = next(
        item
        for item in analysis.findings
        if item.code == "l2_access_vlan_not_in_plan"
    )

    assert finding.severity.value == "info"
    assert finding.affected_entities == ["l_acc", "vlan-99"]


def test_trunk_missing_downstream_vlan() -> None:
    # Hand check: removing l_trunk leaves VLAN 20's access port beyond sw2.
    # The trunk allows only VLAN 10, so VLAN 20 is missing from its list.
    analysis = analyze_l2_design(
        _twin(
            [_switch("sw1"), _switch("sw2"), _host("h1")],
            [
                _trunk("l_trunk", ("sw1", "sw2"), (10,)),
                _access("l_acc", ("sw2", "h1"), 20),
            ],
            vlan_ids=(10, 20),
        )
    )
    finding = next(
        item
        for item in analysis.findings
        if item.code == "l2_trunk_missing_downstream_vlan"
    )

    assert finding.severity.value == "warning"
    assert finding.affected_entities == ["l_trunk", "vlan-20"]


def test_vlan_with_no_gateway_path() -> None:
    links = [
        _plain("l_r1_sw1", ("r1", "sw1")),
        _trunk("l_trunk", ("sw1", "sw2"), (10,)),
        _access("l_acc", ("sw2", "h1"), 10),
    ]
    devices = [_router("r1"), _switch("sw1"), _switch("sw2"), _host("h1")]
    design = L2Design(gateway_by_vlan={10: "r1"})
    twin = _twin(devices, links, design=design)
    analysis = analyze_l2_design(twin)

    finding = next(
        item for item in analysis.findings if item.code == "l2_vlan_no_gateway_path"
    )
    assert finding.severity.value == "error"
    assert finding.affected_entities[:2] == ["vlan-10", "r1"]
    assert set(finding.affected_entities[2:]) == {"sw1", "sw2"}

    # Carrying VLAN 10 on the gateway's link restores the modeled path.
    carried = tuple(
        link.model_copy(
            update={
                "l2_mode": LinkL2Mode.trunk,
                "l2_allowed_vlans": (10,),
            }
        )
        if link.id == "l_r1_sw1"
        else link
        for link in links
    )
    repaired = analyze_l2_design(
        _twin(devices, list(carried), design=design)
    )
    assert "l2_vlan_no_gateway_path" not in _codes(repaired)


def test_vlan_sprawl_uses_configured_threshold() -> None:
    design = L2Design(vlan_spread_threshold=2)
    analysis = analyze_l2_design(
        _twin(
            [_switch("sw1"), _switch("sw2"), _switch("sw3")],
            [
                _trunk("l_sw1_sw2", ("sw1", "sw2"), (10,)),
                _trunk("l_sw2_sw3", ("sw2", "sw3"), (10,)),
            ],
            design=design,
        )
    )
    finding = next(
        item for item in analysis.findings if item.code == "l2_vlan_sprawl"
    )

    # Hand check: 3 carrying switches > threshold 2, so the heuristic warns.
    assert finding.severity.value == "warning"
    assert finding.affected_entities == ["vlan-10", "sw1", "sw2", "sw3"]


def test_empty_twin_has_no_l2_results_and_missing_member_is_down() -> None:
    twin = make_twin(topology=Topology(name="empty"), vlan_plan=None)
    analysis = analyze_l2_design(twin)

    assert analysis.findings == ()
    assert analysis.loops == ()
    assert analysis.blocked_link_ids == ()
    assert analysis.effective_link_ids == ()
    assert analysis.bundles == ()

    empty = bundle_capacity(EtherChannelBundle(id="b-empty", link_ids=("missing",)), ())
    assert empty.member_link_ids == ("missing",)
    assert empty.member_speeds_mbps == ()
    assert empty.capacity_mbps == 0.0
    assert empty.down is True
    assert empty.failed_member_link_ids == ()


def test_effective_blocked_links_and_link_carrying_respect_failed_state() -> None:
    failed = (LinkState(link_id="l_ca", state=OperationalState.down),)
    twin = _triangle_twin(failed)
    analysis = analyze_l2_design(twin)

    # Hand check: l_ca is failed, leaving 2 edges, 3 vertices, 1 component:
    # 2-3+1=0 cycles, so there is nothing to block.
    assert effective_l2_blocked_links(twin) == frozenset()
    assert analysis.loops[0].carrying_link_ids == ("l_ab", "l_bc")
    assert analysis.loops[0].cycle_count == 0
    assert analysis.blocked_link_ids == ()
    assert analysis.effective_link_ids == ("l_ab", "l_bc", "l_ca")
    assert tuple(link.id for link in links_carrying_vlan(twin, 10)) == (
        "l_ab",
        "l_bc",
    )

    healthy = _triangle_twin()
    assert effective_l2_blocked_links(healthy) == frozenset({"l_ca"})
    assert tuple(
        link.id
        for link in links_carrying_vlan(healthy, 10, blocked_link_ids=("l_bc",))
    ) == ("l_ab", "l_ca")
