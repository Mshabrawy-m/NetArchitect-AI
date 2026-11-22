"""Unit coverage for the deterministic, design-only WAN analysis.

Hand checks below use plain arithmetic on the modeled assumptions: monthly
proxy 120 + 30.5 = 150.5, a WAN capacity override of 500 replaces the base
100 Mbps, and a two-link branch with distinct shared-risk tags is healthy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.validation import Finding, Severity
from digital_twin import DigitalTwin, LinkState, OperationalState, TwinMetadata
from network.wan.models import SiteType, WanDesign, WanLinkType
from network.wan.planning import (
    LATENCY_NOTE,
    MONTHLY_COST_NOTE,
    analyze_wan_design,
    inter_site_wan_links,
    wan_cost_proxy_total,
)


def _device(device_id: str, site: str, role: DeviceRole = DeviceRole.wan) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.router,
        site=site,
        role=role,
    )


def _link(
    link_id: str,
    first: str,
    second: str,
    *,
    capacity_mbps: float = 100.0,
    wan_type: WanLinkType | None = None,
    wan_capacity_mbps: float | None = None,
    wan_monthly_cost_proxy: float | None = None,
    wan_latency_ms: float | None = None,
    wan_srg_tag: str | None = None,
) -> Link:
    return Link(
        id=link_id,
        endpoints=(first, second),
        capacity_mbps=capacity_mbps,
        cost=1.0,
        wan_type=wan_type,
        wan_capacity_mbps=wan_capacity_mbps,
        wan_monthly_cost_proxy=wan_monthly_cost_proxy,
        wan_latency_ms=wan_latency_ms,
        wan_srg_tag=wan_srg_tag,
    )


def _twin(
    *,
    devices: list[Device],
    links: list[Link],
    link_states: tuple[LinkState, ...] = (),
) -> DigitalTwin:
    return DigitalTwin(
        metadata=TwinMetadata(
            name="WAN planning test",
            created_at=datetime(2026, 11, 22, 9, 0, tzinfo=UTC),
        ),
        topology=Topology(name="WAN planning test", devices=devices, links=links),
        link_states=link_states,
    )


def _codes(findings: tuple[Finding, ...]) -> list[str]:
    return [finding.code for finding in findings]


def _healthy_design() -> WanDesign:
    return WanDesign(
        site_types={
            "hq-1": SiteType.hq,
            "dc-1": SiteType.dc,
            "branch-ok": SiteType.branch,
        },
        hq_site_ids=("hq-1",),
    )


def _healthy_twin() -> DigitalTwin:
    return _twin(
        devices=[
            _device("hq-r", "hq-1", DeviceRole.border),
            _device("dc-r", "dc-1", DeviceRole.border),
            _device("bok-r", "branch-ok", DeviceRole.wan),
            _device("hq-r2", "hq-1", DeviceRole.core),
        ],
        links=[
            _link(
                "ok-a",
                "hq-r",
                "bok-r",
                wan_type=WanLinkType.leased,
                wan_srg_tag="carrier-a",
            ),
            _link(
                "ok-b",
                "dc-r",
                "bok-r",
                wan_type=WanLinkType.mpls,
                wan_srg_tag="carrier-b",
            ),
            _link(
                "core-link",
                "hq-r",
                "dc-r",
                wan_type=WanLinkType.leased,
                wan_srg_tag="carrier-core",
            ),
        ],
    )


def test_cost_proxy_total_is_hand_computable_and_links_are_sorted() -> None:
    twin = _twin(
        devices=[
            _device("hq-r", "hq-site", DeviceRole.border),
            _device("br-r", "branch-1"),
            _device("br2-r", "branch-2"),
        ],
        # Deliberately declared out of id order; the result must still be sorted.
        links=[
            _link(
                "wan-b",
                "hq-r",
                "br2-r",
                wan_type=WanLinkType.mpls,
                wan_monthly_cost_proxy=30.5,
            ),
            _link(
                "wan-a",
                "hq-r",
                "br-r",
                capacity_mbps=100.0,
                wan_type=WanLinkType.leased,
                wan_capacity_mbps=500.0,
                wan_monthly_cost_proxy=120.0,
                wan_latency_ms=12.0,
                wan_srg_tag="carrier-a",
            ),
        ],
    )

    links = inter_site_wan_links(twin)

    assert [info.link_id for info in links] == ["wan-a", "wan-b"]
    # Hand: WAN override 500 Mbps wins over the base link capacity 100 Mbps.
    assert links[0].capacity_mbps == 500.0
    assert links[0].latency_ms == 12.0
    assert links[0].wan_type is WanLinkType.leased
    # Hand: no WAN capacity override, so the base 100 Mbps is used.
    assert links[1].capacity_mbps == 100.0
    assert [info.monthly_cost_proxy for info in links] == [120.0, 30.5]
    # Hand: 120 + 30.5 = 150.5, independent of list order.
    assert wan_cost_proxy_total(twin) == 150.5

    reordered = twin.model_copy(
        update={
            "topology": twin.topology.model_copy(
                update={"links": list(reversed(twin.topology.links))}
            )
        }
    )
    assert inter_site_wan_links(reordered) == links
    assert wan_cost_proxy_total(reordered) == 150.5

    analysis = analyze_wan_design(twin)
    assert analysis.links == links
    assert analysis.total_monthly_cost_proxy == 150.5
    assert analysis.site_ids == ("branch-1", "branch-2", "hq-site")
    assert analysis.findings[-1].code == "wan_cost_proxy_total"
    assert "150.5" in analysis.findings[-1].explanation
    assert MONTHLY_COST_NOTE == (
        "Modeled monthly cost proxy; not a vendor quote or measured charge."
    )
    assert LATENCY_NOTE == (
        "Assumed one-way latency from the modeled WAN design, not a measurement."
    )


def test_spof_same_srg_and_no_path_findings_are_distinct() -> None:
    twin = _twin(
        devices=[
            _device("hq-r", "hq-1", DeviceRole.border),
            _device("b1-r", "branch-1"),
            _device("b2-r", "branch-2"),
            _device("b3-r", "branch-3"),
            _device("cl-r", "cloud-1"),
        ],
        links=[
            _link(
                "link-single",
                "hq-r",
                "b1-r",
                wan_type=WanLinkType.leased,
                wan_srg_tag="carrier-x",
            ),
            _link(
                "link-srg-b",
                "hq-r",
                "b2-r",
                wan_type=WanLinkType.mpls,
                wan_srg_tag="carrier-a",
            ),
            _link(
                "link-srg-a",
                "hq-r",
                "b2-r",
                wan_type=WanLinkType.mpls,
                wan_srg_tag="carrier-a",
            ),
            _link(
                "link-no-path",
                "b3-r",
                "cl-r",
                wan_type=WanLinkType.internet_vpn,
                wan_srg_tag="carrier-z",
            ),
        ],
    )
    design = WanDesign(
        site_types={
            "hq-1": SiteType.hq,
            "branch-1": SiteType.branch,
            "branch-2": SiteType.branch,
            "branch-3": SiteType.branch,
            "cloud-1": SiteType.cloud,
        },
        hq_site_ids=("hq-1",),
    )

    analysis = analyze_wan_design(twin, design=design)
    spof = [item for item in analysis.findings if item.code == "wan_site_single_link_spof"]
    same_srg = [item for item in analysis.findings if item.code == "wan_site_links_same_srg"]
    no_path = [
        item for item in analysis.findings if item.code == "wan_branch_no_path_to_hq_dc"
    ]

    # Hand: branch-1 has one link; branch-3 reaches only a cloud site.
    assert ["branch-1", "link-single"] in [item.affected_entities for item in spof]
    assert ["branch-3", "link-no-path"] in [item.affected_entities for item in spof]
    assert all(item.severity is Severity.error for item in spof)
    # Hand: both branch-2 links are tagged carrier-a, so they share fate.
    assert [item.affected_entities for item in same_srg] == [
        ["branch-2", "link-srg-a", "link-srg-b"]
    ]
    assert all(item.severity is Severity.error for item in same_srg)
    # Hand: branch-3's only path is to cloud-1, never to modeled hq-1.
    assert [item.affected_entities for item in no_path] == [["branch-3"]]
    assert all(item.severity is Severity.critical for item in no_path)
    assert all("modeled" in item.explanation.lower() for item in no_path)
    # hq-1 has three links with mixed tags; no hq SPOF or same-SRG finding.
    assert not any("hq-1" in item.affected_entities for item in same_srg)


def test_healthy_two_link_branch_has_no_structural_false_positives() -> None:
    analysis = analyze_wan_design(_healthy_twin(), design=_healthy_design())

    # Hand: every site has >= 2 links and no site's links share one SRG tag.
    assert _codes(analysis.findings) == ["wan_cost_proxy_total"]
    assert analysis.total_monthly_cost_proxy == 0.0
    assert analysis.evaluated_demand_count == 0


def test_expensive_capacity_shortfall_uses_evaluation_and_cheap_mode_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twin = _healthy_twin()
    design = _healthy_design()

    def _no_evaluator_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("the evaluator must not run in cheap mode")

    monkeypatch.setattr("simulation.evaluator.evaluate", _no_evaluator_call)
    cheap = analyze_wan_design(twin, design=design)
    assert "wan_capacity_shortfall" not in _codes(cheap.findings)
    assert cheap.evaluated_demand_count == 0

    # Hand: the hq-r -> hq-r2 demand stays inside hq-1 and is excluded; only the
    # branch-ok -> hq-1 demand counts as an unserved inter-site shortfall.
    fake_evaluation = SimpleNamespace(
        demands=(
            SimpleNamespace(name="d-branch-hq"),
            SimpleNamespace(name="d-same-site"),
        ),
        unserved_demands=(
            SimpleNamespace(
                name="d-branch-hq",
                source="bok-r",
                destination="hq-r",
                bottleneck_link_id="ok-a",
            ),
            SimpleNamespace(
                name="d-same-site",
                source="hq-r",
                destination="hq-r2",
                bottleneck_link_id="core-link",
            ),
        ),
    )
    expensive = analyze_wan_design(
        twin,
        design=design,
        include_expensive=True,
        evaluation=fake_evaluation,
    )

    shortfalls = [
        item
        for item in expensive.findings
        if item.code == "wan_capacity_shortfall"
    ]
    assert len(shortfalls) == 1
    assert shortfalls[0].severity is Severity.error
    assert shortfalls[0].affected_entities == ["d-branch-hq", "ok-a"]
    assert "d-branch-hq" in shortfalls[0].explanation
    assert "ok-a" in shortfalls[0].explanation
    assert "modeled" in shortfalls[0].explanation.lower()
    assert expensive.evaluated_demand_count == 2


def test_plain_links_are_ignored_down_links_are_excluded_and_empty_twin_is_safe() -> None:
    plain = _twin(
        devices=[
            _device("a", "site-a", DeviceRole.access),
            _device("b", "site-b", DeviceRole.access),
        ],
        links=[_link("plain", "a", "b")],
    )
    assert inter_site_wan_links(plain) == ()
    assert wan_cost_proxy_total(plain) == 0.0
    plain_analysis = analyze_wan_design(plain)
    assert plain_analysis.links == ()
    assert _codes(plain_analysis.findings) == ["wan_cost_proxy_total"]

    down = _twin(
        devices=[
            _device("a", "site-a"),
            _device("b", "site-b"),
        ],
        links=[
            _link(
                "wan-down",
                "a",
                "b",
                wan_type=WanLinkType.leased,
                wan_monthly_cost_proxy=7.0,
            )
        ],
        link_states=(
            LinkState(link_id="wan-down", state=OperationalState.down),
        ),
    )
    assert inter_site_wan_links(down) == ()
    assert wan_cost_proxy_total(down) == 0.0

    empty = analyze_wan_design(_twin(devices=[], links=[]))
    assert empty.links == ()
    assert empty.site_ids == ()
    assert empty.total_monthly_cost_proxy == 0.0
    assert empty.evaluated_demand_count == 0
    assert all(
        item.code == "wan_cost_proxy_total" and item.severity is Severity.info
        for item in empty.findings
    )
