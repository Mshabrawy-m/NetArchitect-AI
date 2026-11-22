"""Opt-in timing checks for the W1-W4 modeled design engines.

Run explicitly with
``pytest -q -m perf -o addopts= tests/unit/test_w5_design_perf.py -s``.
Each input is built at exactly the configured limit and prints its measured
time for the final report. No runtime threshold is asserted: the numbers are
evidence, not acceptance tests.
"""

from __future__ import annotations

from time import perf_counter

import pytest

from config.limits import (
    MAX_ETHERCHANNEL_BUNDLES,
    MAX_ETHERCHANNEL_MEMBERS,
    MAX_QOS_CLASS_CAPS,
    MAX_WAN_DESIGN_SITES,
    MAX_WAN_LINKS,
    MAX_WIRELESS_AREAS,
)
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.l2.models import EtherChannelBundle, L2Design, LinkL2Mode
from network.l2.switching import analyze_l2_design
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.qos.review import qos_findings
from network.wan.models import SiteType, WanDesign, WanLinkType
from network.wan.planning import analyze_wan_design
from network.wireless.models import WirelessArea, WirelessDesign
from network.wireless.planning import analyze_wireless_design
from simulation import RoutingMode, SimulationAssumptions, evaluate
from tests.unit.digital_twin.helpers import CREATED_AT

pytestmark = pytest.mark.perf

_CLASSES = tuple(TrafficClass)


def _twin(*, topology: Topology, **fields: object) -> DigitalTwin:
    return DigitalTwin(
        metadata=TwinMetadata(name="W5 max-size timing", created_at=CREATED_AT),
        topology=topology,
        **fields,  # type: ignore[arg-type]
    )


def test_w1_max_l2_bundles_timing() -> None:
    switches = tuple(
        Device(
            id=f"sw-{index:02d}",
            type=DeviceType.switch,
            site="campus",
            role=DeviceRole.access,
        )
        for index in range(16)
    )
    links = tuple(
        Link(
            id=f"l-{index:03d}",
            endpoints=(
                f"sw-{index % 16:02d}",
                f"sw-{(index + 1) % 16:02d}",
            ),
            capacity_mbps=1000.0,
            cost=1.0,
            l2_mode=LinkL2Mode.trunk,
            l2_allowed_vlans=(10,),
        )
        for index in range(MAX_ETHERCHANNEL_BUNDLES * MAX_ETHERCHANNEL_MEMBERS)
    )
    bundles = tuple(
        EtherChannelBundle(
            id=f"bundle-{index:02d}",
            link_ids=tuple(
                f"l-{index * MAX_ETHERCHANNEL_MEMBERS + member:03d}"
                for member in range(MAX_ETHERCHANNEL_MEMBERS)
            ),
        )
        for index in range(MAX_ETHERCHANNEL_BUNDLES)
    )
    twin = _twin(
        topology=Topology(name="max-l2", devices=switches, links=links),
        l2_design=L2Design(etherchannel_bundles=bundles),
    )

    started = perf_counter()
    analysis = analyze_l2_design(twin)
    elapsed = perf_counter() - started

    # Hand: 32 bundles x 8 existing 1000 Mbps members = 32 x 8000 Mbps.
    assert len(analysis.bundles) == MAX_ETHERCHANNEL_BUNDLES
    assert all(item.capacity_mbps == 8000.0 for item in analysis.bundles)
    print(
        f"W1 max-l2-bundles ({MAX_ETHERCHANNEL_BUNDLES} x "
        f"{MAX_ETHERCHANNEL_MEMBERS}): {elapsed:.4f}s"
    )


def test_w2_max_wan_sites_and_links_timing() -> None:
    sites = tuple(f"site-{index:03d}" for index in range(MAX_WAN_DESIGN_SITES))
    devices = tuple(
        Device(
            id=f"r-{site}",
            type=DeviceType.router,
            site=site,
            role=DeviceRole.border if index == 0 else DeviceRole.wan,
        )
        for index, site in enumerate(sites)
    )
    links = tuple(
        Link(
            id=f"wan-{index:03d}",
            endpoints=(
                f"r-{sites[index % len(sites)]}",
                f"r-{sites[(index + 1) % len(sites)]}",
            ),
            capacity_mbps=100.0,
            cost=1.0,
            wan_type=WanLinkType.leased,
            wan_monthly_cost_proxy=1.0,
        )
        for index in range(MAX_WAN_LINKS)
    )
    design = WanDesign(
        site_types={
            site: SiteType.hq if index == 0 else SiteType.branch
            for index, site in enumerate(sites)
        },
        hq_site_ids=(sites[0],),
    )
    twin = _twin(
        topology=Topology(name="max-wan", devices=devices, links=links),
        wan_design=design,
    )

    started = perf_counter()
    analysis = analyze_wan_design(twin, design=design, include_expensive=False)
    elapsed = perf_counter() - started

    # Hand: 128 active links at a 1.0 proxy each give a 128.0 monthly total.
    assert len(analysis.links) == MAX_WAN_LINKS
    assert len(analysis.site_ids) == MAX_WAN_DESIGN_SITES
    assert analysis.total_monthly_cost_proxy == float(MAX_WAN_LINKS)
    assert analysis.evaluated_demand_count == 0
    print(
        f"W2 max-wan-design ({MAX_WAN_DESIGN_SITES} sites, "
        f"{MAX_WAN_LINKS} links): {elapsed:.4f}s"
    )


def test_w3_max_wireless_areas_timing() -> None:
    design = WirelessDesign(
        areas=tuple(
            WirelessArea(
                id=f"area-{index:02d}",
                area_m2=1000,
                clients=100,
                client_mbps=10,
                ap_capacity_mbps=100,
                utilization_target=0.5,
            )
            for index in range(MAX_WIRELESS_AREAS)
        )
    )

    started = perf_counter()
    analysis = analyze_wireless_design(design)
    elapsed = perf_counter() - started

    # Hand: ceil(100*10/(100*0.5)) = 20 APs per area; 32 x 20 = 640 APs.
    # Uplink per area is 20 * 100 * 0.5 = 1000 Mbps, so 32 areas need 32000.
    assert len(analysis.plans) == MAX_WIRELESS_AREAS
    assert analysis.total_recommended_aps == 640
    assert analysis.total_uplink_required_mbps == 32000.0
    print(f"W3 max-wireless-areas ({MAX_WIRELESS_AREAS}): {elapsed:.4f}s")


def test_w4_max_qos_caps_timing() -> None:
    devices = (
        Device(id="a", type=DeviceType.router, site="campus", role=DeviceRole.core),
        Device(id="b", type=DeviceType.router, site="campus", role=DeviceRole.core),
    )
    link_count = MAX_QOS_CLASS_CAPS // len(_CLASSES)
    links = tuple(
        Link(
            id=f"l-{index:02d}",
            endpoints=("a", "b"),
            capacity_mbps=100.0,
            cost=float(index + 1),
        )
        for index in range(link_count)
    )
    caps = tuple(
        ClassShareCap(
            link_id=f"l-{index:02d}",
            traffic_class=traffic_class,
            share_cap=0.25,
        )
        for index in range(link_count)
        for traffic_class in _CLASSES
    )
    demands = tuple(
        TrafficDemand(
            name=f"demand-{traffic_class.value}",
            source="a",
            destination="b",
            bandwidth_mbps=10.0,
            traffic_class=traffic_class,
        )
        for traffic_class in _CLASSES
    )
    twin = _twin(
        topology=Topology(name="max-qos", devices=devices, links=links),
        demands=demands,
        qos_design=QosDesign(class_share_caps=caps),
    )

    started = perf_counter()
    state = evaluate(
        twin,
        SimulationAssumptions(
            routing_mode=RoutingMode.capacity_aware,
            enable_strict_priority_qos=True,
        ),
    )
    findings = qos_findings(twin, state)
    elapsed = perf_counter() - started

    # Hand: 32 links x 4 classes = 128 unique caps; 4 x 10 Mbps fits on any
    # modeled 100 Mbps path, so neither unknown-cap nor starvation findings fire.
    assert len(caps) == MAX_QOS_CLASS_CAPS
    assert findings == ()
    assert len(state.demands) == len(_CLASSES)
    print(f"W4 max-qos-caps ({MAX_QOS_CLASS_CAPS}): {elapsed:.4f}s")
