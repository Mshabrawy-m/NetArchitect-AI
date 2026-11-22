"""L3 tests for the modeled OSPF area design rules.

Every expected role, cost, and summary is hand-computed in the comments.
"""

from __future__ import annotations

import pytest

from config.limits import MAX_OSPF_AREAS
from core.exceptions import LimitsExceededError
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from network.routing import (
    OspfArea,
    OspfDesign,
    OspfRouterRole,
    analyze_ospf_design,
)


def _device(device_id: str, role: DeviceRole = DeviceRole.distribution) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.router,
        site="campus",
        role=role,
    )


def _link(link_id: str, start: str, end: str, *, capacity: float = 1000.0) -> Link:
    return Link(
        id=link_id,
        endpoints=(start, end),
        capacity_mbps=capacity,
        cost=1.0,
    )


def _codes(analysis: object) -> set[str]:
    return {finding.code for finding in analysis.findings}  # type: ignore[attr-defined]


def test_roles_are_derived_from_area_membership_and_device_role() -> None:
    topology = Topology(
        name="campus",
        devices=[
            _device("core", DeviceRole.core),
            _device("r1"),
            _device("r2", DeviceRole.access),
            _device("r3"),
            _device("gw", DeviceRole.border),
        ],
        links=[
            _link("l-core-r1", "core", "r1"),
            _link("l-r1-r2", "r1", "r2"),
            _link("l-r2-r3", "r2", "r3"),
            _link("l-r3-gw", "r3", "gw"),
        ],
    )
    design = OspfDesign(
        areas=[
            OspfArea(area_id=0, name="Backbone", device_ids=("core", "r1")),
            OspfArea(area_id=10, name="Users", device_ids=("r1", "r2", "r3")),
            OspfArea(area_id=20, name="Edge", device_ids=("r3", "gw")),
        ],
        declared_abr_device_ids=("r1", "r3"),
    )
    analysis = analyze_ospf_design(design, topology)

    # Hand: core in only area 0 -> internal; r1 in {0,10} -> ABR;
    # r2 in only {10} -> internal; r3 in {10,20} -> ABR;
    # gw has border role -> ASBR even though it is in one area.
    expected = {
        "core": (OspfRouterRole.internal, (0,)),
        "r1": (OspfRouterRole.abr, (0, 10)),
        "r2": (OspfRouterRole.internal, (10,)),
        "r3": (OspfRouterRole.abr, (10, 20)),
        "gw": (OspfRouterRole.asbr, (20,)),
    }
    for router in analysis.routers:
        assert (router.role, router.area_ids) == expected[router.device_id]

    # Hand: area 10 has ABR r1 attached to area 0, area 20 only has r3 which
    # is not in area 0, so area 20 is the one flagged virtual-link-needed.
    virtual = next(
        finding
        for finding in analysis.findings
        if finding.code == "ospf_virtual_link_needed"
    )
    assert virtual.affected_entities == ["20"]


def test_missing_backbone_and_single_area_declared_abr_are_errors() -> None:
    topology = Topology(
        name="no-backbone",
        devices=[_device("core"), _device("r1")],
        links=[_link("l1", "core", "r1")],
    )
    design = OspfDesign(
        areas=[OspfArea(area_id=10, name="Users", device_ids=("core", "r1"))],
        declared_abr_device_ids=("core",),
    )
    analysis = analyze_ospf_design(design, topology)
    codes = _codes(analysis)

    assert "ospf_no_backbone" in codes
    assert "ospf_virtual_link_needed" in codes
    # Hand: core appears in exactly one area, so it cannot be an ABR.
    assert "ospf_abr_not_multi_area" in codes


def test_area_size_threshold_is_a_heuristic_not_a_protocol_limit() -> None:
    topology = Topology(
        name="large",
        devices=[_device("a"), _device("b"), _device("c")],
        links=[_link("l1", "a", "b"), _link("l2", "b", "c")],
    )
    design = OspfDesign(
        areas=[
            OspfArea(area_id=0, name="Backbone", device_ids=("a",)),
            OspfArea(area_id=10, name="Users", device_ids=("a", "b", "c")),
        ],
        area_size_threshold=2,
    )
    analysis = analyze_ospf_design(design, topology)
    finding = next(
        finding
        for finding in analysis.findings
        if finding.code == "ospf_area_too_large"
    )
    # Hand: 3 devices > threshold 2, so one warning for area 10.
    assert "3 device(s)" in finding.explanation
    assert "NOT an OSPF protocol limit" in finding.explanation
    assert finding.severity.value == "warning"


def test_discontiguous_backbone_is_detected() -> None:
    split = Topology(
        name="split",
        devices=[_device("a"), _device("b")],
        links=[],
    )
    design = OspfDesign(
        areas=[OspfArea(area_id=0, name="Backbone", device_ids=("a", "b"))]
    )
    analysis = analyze_ospf_design(design, split)
    finding = next(
        finding
        for finding in analysis.findings
        if finding.code == "ospf_backbone_discontiguous"
    )
    # Hand: no links between a and b -> 2 weak components.
    assert "2 disconnected component(s)" in finding.explanation

    joined = split.model_copy(update={"links": [_link("l1", "a", "b")]})
    connected = analyze_ospf_design(design, joined)
    assert "ospf_backbone_discontiguous" not in _codes(connected)


def test_single_abr_spof_uses_existing_analysis_engine() -> None:
    topology = Topology(
        name="single-abr",
        devices=[_device("core", DeviceRole.core), _device("abr"), _device("leaf")],
        links=[_link("l1", "core", "abr"), _link("l2", "abr", "leaf")],
    )
    design = OspfDesign(
        areas=[
            OspfArea(area_id=0, name="Backbone", device_ids=("core", "abr")),
            OspfArea(area_id=10, name="Users", device_ids=("abr", "leaf")),
        ]
    )
    analysis = analyze_ospf_design(design, topology)
    finding = next(
        finding for finding in analysis.findings if finding.code == "ospf_single_abr_spof"
    )
    # Hand: removing 'abr' disconnects 'leaf' from 'core', so SPOF flags it.
    assert finding.affected_entities == ["10", "abr"]

    redundant = Topology(
        name="dual-abr",
        devices=[
            _device("core", DeviceRole.core),
            _device("abr1"),
            _device("abr2"),
            _device("leaf"),
        ],
        links=[
            _link("l1", "core", "abr1"),
            _link("l2", "abr1", "leaf"),
            _link("l3", "core", "abr2"),
            _link("l4", "abr2", "leaf"),
        ],
    )
    dual_design = OspfDesign(
        areas=[
            OspfArea(
                area_id=0,
                name="Backbone",
                device_ids=("core", "abr1", "abr2"),
            ),
            OspfArea(
                area_id=10,
                name="Users",
                device_ids=("abr1", "abr2", "leaf"),
            ),
        ]
    )
    dual = analyze_ospf_design(dual_design, redundant)
    # Hand: two attached ABRs, so the single-ABR SPOF rule does not fire.
    assert "ospf_single_abr_spof" not in _codes(dual)


def test_summarization_suggestion_is_inert_and_hand_computed() -> None:
    topology = Topology(name="summaries", devices=[_device("a")], links=[])
    design = OspfDesign(
        areas=[
            OspfArea(area_id=0, name="Backbone", device_ids=("a",)),
            OspfArea(
                area_id=10,
                name="Users",
                device_ids=("a",),
                subnets=[
                    "10.1.0.0/24",
                    "10.1.1.0/24",
                    "10.1.2.0/24",
                    "10.1.3.0/24",
                    "10.2.0.0/24",
                ],
            ),
        ]
    )
    analysis = analyze_ospf_design(design, topology)

    # Hand: four contiguous /24s from 10.1.0.0 through 10.1.3.255 have the
    # common 22-bit prefix 10.1.0.0/22. 10.2.0.0/24 cannot join that summary.
    assert len(analysis.summaries) == 1
    summary = analysis.summaries[0]
    assert (summary.area_id, summary.summary) == (10, "10.1.0.0/22")
    assert len(summary.covered_subnets) == 4
    assert summary.inert is True
    assert "ospf_summarization_opportunity" in _codes(analysis)


def test_link_cost_formula_reuses_existing_cost_and_documents_reference_bw() -> None:
    topology = Topology(
        name="costs",
        devices=[_device("a"), _device("b")],
        links=[_link("l1", "a", "b", capacity=1000.0)],
    )
    # Link.cost is 1.0; capacity 1000 Mbps is metadata only in the base model.
    base = OspfDesign(
        areas=[OspfArea(area_id=0, name="Backbone", device_ids=("a", "b"))]
    )
    base_cost = analyze_ospf_design(base, topology).link_costs[0]
    assert (base_cost.base_cost, base_cost.effective_cost) == (1.0, 1.0)
    assert base_cost.formula == "Link.cost (existing routing-engine cost semantics)"

    # Hand: ceil(10000 / 1000) = 10; the optional modeled formula replaces cost.
    modeled = base.model_copy(update={"reference_bandwidth_mbps": 10000.0})
    reference_cost = analyze_ospf_design(modeled, topology).link_costs[0]
    assert reference_cost.effective_cost == 10.0
    assert "ceil(10000 / 1000) = 10" in reference_cost.formula


def test_area_membership_can_come_from_links_and_area_limit_is_enforced() -> None:
    topology = Topology(
        name="links",
        devices=[_device("a"), _device("b")],
        links=[_link("l1", "a", "b")],
    )
    design = OspfDesign(
        areas=[
            OspfArea(area_id=0, name="Backbone", device_ids=("a",)),
            OspfArea(area_id=10, name="Users", link_ids=("l1",)),
        ]
    )
    analysis = analyze_ospf_design(design, topology)
    # Hand: link l1 endpoints a,b join area 10; a is in {0,10} -> ABR,
    # b is only in {10} -> internal.
    roles = {router.device_id: router.role for router in analysis.routers}
    assert roles == {"a": OspfRouterRole.abr, "b": OspfRouterRole.internal}

    too_many = OspfDesign(
        areas=tuple(
            OspfArea(area_id=index, name=f"area-{index}")
            for index in range(MAX_OSPF_AREAS + 1)
        )
    )
    with pytest.raises(LimitsExceededError, match="limit is"):
        analyze_ospf_design(too_many, topology)
