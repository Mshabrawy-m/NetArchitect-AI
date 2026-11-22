"""Report coverage for the four optional W1-W4 modeled design sections.

Hand checks used below:

* L2: a triangle of trunk links carrying VLAN 10 has cycle rank
  ``3 - 3 + 1 = 1``. Ascending ``(cost, id)`` spanning forest keeps
  ``l_ab`` and ``l_bc``, so ``l_ca`` is blocked. Of nine topology links,
  eight remain effective. The bundle sums 100 + 200 = 300 Mbps and warns
  about mismatched member speeds.
* WAN: 120 (leased) + 30.5 (MPLS) + 0 (interconnect proxy) = 150.5.
  Three sites, three active inter-site links, and no capacity-aware
  evaluation in this report (0 demands evaluated).
* Wireless: floor capacity is ceil(200 * 10 / (100 * 0.5)) = 40 APs while
  coverage is ceil(1000 / (pi * 20**2 * 0.8)) = 1, so 40 APs / 2000 Mbps.
  Hall capacity is ceil(10 * 10 / (1000 * 1)) = 1 while coverage is
  ceil(10000 / (pi * 10**2 * 0.5)) = 64, so 64 APs / 64000 Mbps.
  Totals: 104 recommended APs and 66000 Mbps of uplink requirement.
* QoS: voice 80 Mbps is admitted first on the 100 Mbps WAN link, leaving
  20 Mbps, so the 30 Mbps best-effort demand is starved (1 admitted,
  1 starved). The admission model reports ``qos_demand_starved``; it says
  nothing about queues.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.routing import TrafficDemand
from network.l2.models import EtherChannelBundle, L2Design, LinkL2Mode
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.wan.models import SiteType, WanDesign, WanLinkType
from network.wireless.models import WirelessArea, WirelessDesign
from services.reporting import (
    NoteBlock,
    ReportDocument,
    ReportSection,
    ReportSources,
    TableBlock,
    build_report,
    check_consistency,
    numeric_tokens,
    parse_display,
)
from tests.unit.digital_twin.helpers import make_twin

GENERATED_AT = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

W5_SECTIONS = (
    "l2_switching_design",
    "wan_design",
    "wireless_design",
    "qos_design",
)
W5_PREFIXES = ("l2.", "wan.", "wireless.", "qos.")


def _w5_twin():  # type: ignore[no-untyped-def]
    devices = [
        Device(id="r1", type=DeviceType.router, site="hq", role=DeviceRole.core),
        Device(id="sw1", type=DeviceType.switch, site="hq", role=DeviceRole.access),
        Device(id="sw2", type=DeviceType.switch, site="hq", role=DeviceRole.access),
        Device(id="sw3", type=DeviceType.switch, site="hq", role=DeviceRole.access),
        Device(id="br1", type=DeviceType.router, site="branch", role=DeviceRole.wan),
        Device(id="dc1", type=DeviceType.router, site="dc", role=DeviceRole.border),
    ]
    links = [
        Link(id="l_ab", endpoints=("sw1", "sw2"), capacity_mbps=1000.0, cost=1.0,
             l2_mode=LinkL2Mode.trunk, l2_allowed_vlans=(10,)),
        Link(id="l_bc", endpoints=("sw2", "sw3"), capacity_mbps=1000.0, cost=1.0,
             l2_mode=LinkL2Mode.trunk, l2_allowed_vlans=(10,)),
        Link(id="l_ca", endpoints=("sw3", "sw1"), capacity_mbps=1000.0, cost=2.0,
             l2_mode=LinkL2Mode.trunk, l2_allowed_vlans=(10,)),
        Link(id="l_gw", endpoints=("sw1", "r1"), capacity_mbps=100.0, cost=1.0,
             l2_mode=LinkL2Mode.access, l2_access_vlan=10),
        Link(id="l_bun_a", endpoints=("sw2", "sw3"), capacity_mbps=100.0, cost=5.0),
        Link(id="l_bun_b", endpoints=("sw2", "sw3"), capacity_mbps=200.0, cost=6.0),
        Link(id="wan_a", endpoints=("r1", "br1"), capacity_mbps=100.0, cost=1.0,
             wan_type=WanLinkType.leased, wan_monthly_cost_proxy=120.0,
             wan_latency_ms=12.0, wan_srg_tag="carrier-a"),
        Link(id="wan_b", endpoints=("br1", "dc1"), capacity_mbps=100.0, cost=1.0,
             wan_type=WanLinkType.mpls, wan_capacity_mbps=10.0,
             wan_monthly_cost_proxy=30.5, wan_latency_ms=20.0,
             wan_srg_tag="carrier-b"),
        Link(id="core_link", endpoints=("r1", "dc1"), capacity_mbps=1000.0, cost=10.0,
             wan_type=WanLinkType.leased, wan_monthly_cost_proxy=0.0,
             wan_latency_ms=5.0, wan_srg_tag="carrier-core"),
    ]
    demands = (
        TrafficDemand(name="voice-call", source="r1", destination="br1",
                      bandwidth_mbps=80.0, traffic_class=TrafficClass.voice),
        TrafficDemand(name="bulk-transfer", source="r1", destination="br1",
                      bandwidth_mbps=30.0, traffic_class=TrafficClass.best_effort),
    )
    return make_twin(
        topology=Topology(name="W5 report test", devices=devices, links=links),
        demands=demands,
        l2_design=L2Design(
            gateway_by_vlan={10: "r1"},
            root_priorities={"sw1": 100},
            vlan_spread_threshold=3,
            etherchannel_bundles=(
                EtherChannelBundle(id="bundle-1", link_ids=("l_bun_a", "l_bun_b")),
            ),
        ),
        wan_design=WanDesign(
            site_types={
                "hq": SiteType.hq,
                "branch": SiteType.branch,
                "dc": SiteType.dc,
            },
            hq_site_ids=("hq",),
        ),
        wireless_design=WirelessDesign(
            areas=(
                WirelessArea(
                    id="floor-1", name="Floor 1", area_m2=1000, clients=200,
                    client_mbps=10, ap_capacity_mbps=100, utilization_target=0.5,
                    uplink_switch_id="sw1",
                ),
                WirelessArea(
                    id="hall", name="Hall", area_m2=10000, clients=10,
                    client_mbps=10, ap_capacity_mbps=1000, utilization_target=1,
                    coverage_radius_m=10, overlap_factor=0.5,
                ),
            )
        ),
        qos_design=QosDesign(
            default_class=TrafficClass.best_effort,
            class_share_caps=(
                ClassShareCap(link_id="l_ab", traffic_class=TrafficClass.best_effort,
                              share_cap=0.5),
            ),
        ),
    )


def _document(twin=None) -> ReportDocument:  # type: ignore[no-untyped-def]
    return build_report(
        ReportSources(twin=twin if twin is not None else make_twin(),
                      generated_at=GENERATED_AT)
    )


def _value(document: ReportDocument, key: str):  # type: ignore[no-untyped-def]
    return next(record for record in document.values if record.key == key)


def _notes(section: ReportSection) -> str:
    return " ".join(
        block.text for block in section.blocks if isinstance(block, NoteBlock)
    )


def _section_text(section: ReportSection) -> str:
    return " ".join(getattr(block, "text", "") for block in section.blocks)


def _rendered_numbers(section: ReportSection) -> list[str]:
    tokens: list[str] = []
    for block in section.blocks:
        if isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row:
                    tokens.extend(numeric_tokens(cell))
        else:
            tokens.extend(numeric_tokens(block.text))
    return tokens


def test_w5_sections_are_inserted_before_graph_analysis() -> None:
    ids = _document().section_ids()
    assert ids.index("gateway_redundancy") + 1 == ids.index("l2_switching_design")
    assert tuple(ids[ids.index("l2_switching_design"):ids.index("graph_analysis")]) == (
        W5_SECTIONS
    )


def test_default_twin_has_four_not_run_sections_pointing_to_l2_design() -> None:
    document = _document()

    assert check_consistency(document).ok
    for section_id in W5_SECTIONS:
        section = document.section(section_id)
        assert section is not None
        assert section.status.value == "not_run"
        assert section.unavailable_reason
        assert section.producer_page == "L2 Design"
        assert section.blocks == ()
    assert not any(
        record.key.startswith(W5_PREFIXES) for record in document.values
    )


def test_populated_w5_sections_are_available_with_hand_checked_totals() -> None:
    document = _document(_w5_twin())

    assert check_consistency(document).ok, [
        (item.code, item.message) for item in check_consistency(document).errors
    ]
    for section_id in W5_SECTIONS:
        section = document.section(section_id)
        assert section is not None
        assert section.status.value == "available"
        assert section.blocks
        assert section.producer_page == ""
        assert section.unavailable_reason == ""

    # L2: 1 loop review, 1 blocked link (l_ca), 8 effective links, 1 bundle.
    assert _value(document, "l2.loops").numeric == 1
    assert _value(document, "l2.loop.0.vlan").numeric == 10
    assert _value(document, "l2.loop.0.cycles").numeric == 1
    assert _value(document, "l2.loop.0.components").numeric == 1
    assert _value(document, "l2.loop.0.switches").numeric == 3
    assert _value(document, "l2.blocked_links").numeric == 1
    assert _value(document, "l2.effective_links").numeric == 8
    assert _value(document, "l2.bundles").numeric == 1
    assert _value(document, "l2.bundle.0.capacity").numeric == 300
    assert _value(document, "l2.findings").numeric == 2
    # Hand: findings are emitted in review order, loop before bundle review.
    assert "[l2_loop_needs_blocking]" in _notes(document.section("l2_switching_design"))
    assert "[l2_mismatched_bundle_speeds]" in _notes(document.section("l2_switching_design"))

    # WAN: 120 + 30.5 + 0 = 150.5 modeled monthly proxy; 3 sites and 3 links.
    assert _value(document, "wan.sites").numeric == 3
    assert _value(document, "wan.links").numeric == 3
    assert _value(document, "wan.cost_proxy_monthly").numeric == 150.5
    assert _value(document, "wan.evaluated_demands").numeric == 0
    assert _value(document, "wan.link.0.id").display == "core_link"
    assert _value(document, "wan.link.0.cost_proxy").numeric == 0
    assert _value(document, "wan.link.1.cost_proxy").numeric == 120
    assert _value(document, "wan.link.1.latency").numeric == 12
    assert _value(document, "wan.link.2.cost_proxy").numeric == 30.5
    assert _value(document, "wan.link.2.capacity").numeric == 10
    assert "[wan_cost_proxy_total]" in _notes(document.section("wan_design"))

    # Wireless: 40 + 64 = 104 APs; 2000 + 64000 = 66000 Mbps uplink.
    assert _value(document, "wireless.areas").numeric == 2
    assert _value(document, "wireless.total_aps").numeric == 104
    assert _value(document, "wireless.total_uplink_mbps").numeric == 66000
    assert _value(document, "wireless.plan.0.recommended_aps").numeric == 40
    assert _value(document, "wireless.plan.0.uplink_mbps").numeric == 2000
    assert _value(document, "wireless.plan.0.binding").display == "capacity"
    assert _value(document, "wireless.plan.1.recommended_aps").numeric == 64
    assert _value(document, "wireless.plan.1.uplink_mbps").numeric == 64000
    assert _value(document, "wireless.plan.1.binding").display == "coverage"
    wireless_notes = _notes(document.section("wireless_design"))
    assert "[wireless_capacity_binding]" in wireless_notes
    assert "[wireless_coverage_binding]" in wireless_notes

    # QoS: voice 80 admitted, best effort 30 starved behind it.
    assert _value(document, "qos.default_class").display == "best_effort"
    assert _value(document, "qos.caps").numeric == 1
    assert _value(document, "qos.cap.0.share").numeric == 0.5
    assert _value(document, "qos.demands").numeric == 2
    assert _value(document, "qos.served").numeric == 1
    assert _value(document, "qos.starved").numeric == 1
    assert _value(document, "qos.demand.0.bandwidth").numeric == 80
    assert _value(document, "qos.demand.0.class").display == "voice"
    assert _value(document, "qos.demand.1.bandwidth").numeric == 30
    assert _value(document, "qos.demand.1.class").display == "best_effort"
    qos_notes = _notes(document.section("qos_design"))
    assert "[qos_demand_starved]" in qos_notes
    assert "not a queue simulation" in _section_text(document.section("qos_design"))


def test_w5_values_have_provenance_and_all_rendered_numbers_are_sourced() -> None:
    document = _document(_w5_twin())
    fingerprint = document.twin.fingerprint
    w5_records = [
        record for record in document.values
        if record.key.startswith(W5_PREFIXES)
    ]
    assert w5_records
    for record in w5_records:
        assert record.provenance.step
        assert record.provenance.tool
        assert record.provenance.twin_version == fingerprint
        assert record.label

    allowed = {
        round(number, 6)
        for record in document.values
        for number in (
            [float(record.numeric)] if record.numeric is not None else []
        ) + ([parse_display(record.display)] if parse_display(record.display) is not None else [])
    }
    checked = 0
    for section_id in W5_SECTIONS:
        section = document.section(section_id)
        assert section is not None
        for token in _rendered_numbers(section):
            checked += 1
            assert round(float(token), 6) in allowed, (section_id, token)
        for block in section.blocks:
            if isinstance(block, TableBlock):
                assert block.provenance.twin_version == fingerprint
                assert block.total_rows >= len(block.rows)
    assert checked > 0


def test_w5_notes_state_the_model_scope() -> None:
    document = _document(_w5_twin())
    scope = {
        section_id: _notes(document.section(section_id)).lower()
        for section_id in W5_SECTIONS
    }
    assert "design rules only" in scope["l2_switching_design"]
    assert "cost proxies" in scope["wan_design"]
    assert "assumed latency" in scope["wan_design"]
    assert "no rf propagation" in scope["wireless_design"]
    assert "admission model" in scope["qos_design"]
    assert "queue behavior" in scope["qos_design"]
