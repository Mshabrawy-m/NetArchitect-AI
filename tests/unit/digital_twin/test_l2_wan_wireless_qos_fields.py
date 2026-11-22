"""Additive L2/WAN/wireless/QoS fields preserve legacy twin bytes.

Hand check: the recorded legacy fingerprint was captured before any of these
fields existed. Default-only fields must be absent from canonical JSON; setting
any new field must change the fingerprint and still round-trip exactly.
"""

from __future__ import annotations

import json

from core.schemas.network import Link, LinkL2Mode, WanLinkType
from core.schemas.organization import Site
from core.schemas.routing import TrafficDemand
from digital_twin import from_json, to_json
from network.l2.models import EtherChannelBundle, L2Design
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.wan.models import SiteType, WanDesign
from network.wireless.models import WirelessArea, WirelessDesign
from simulation import twin_fingerprint

from .helpers import make_twin

LEGACY_FINGERPRINT = (
    "4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c"
)
_NEW_FIELDS = ("l2_design", "wan_design", "wireless_design", "qos_design")


def _populated() -> dict[str, object]:
    return {
        "l2_design": L2Design(
            gateway_by_vlan={10: "sw1"},
            root_priorities={"sw1": 4096},
            etherchannel_bundles=(
                EtherChannelBundle(id="bundle-1", link_ids=("l1", "l2")),
            ),
        ),
        "wan_design": WanDesign(
            site_types={"hq": SiteType.hq, "br1": SiteType.branch},
            hq_site_ids=("hq",),
        ),
        "wireless_design": WirelessDesign(
            areas=(WirelessArea(id="area-1", area_m2=1000, clients=200),),
        ),
        "qos_design": QosDesign(
            class_share_caps=(
                ClassShareCap(
                    link_id="l1",
                    traffic_class=TrafficClass.voice,
                    share_cap=0.2,
                ),
            ),
        ),
    }


def test_default_twin_json_and_fingerprint_are_legacy_identical() -> None:
    twin = make_twin()
    metadata = twin.metadata.model_copy(update={"schema_version": 1})
    twin = twin.model_copy(update={"metadata": metadata})
    payload = json.loads(to_json(twin))
    assert twin_fingerprint(twin) == LEGACY_FINGERPRINT
    for field in _NEW_FIELDS:
        assert field not in payload
    first_link = payload["topology"]["links"][0]
    for field in (
        "l2_mode",
        "l2_access_vlan",
        "l2_native_vlan",
        "l2_peer_native_vlan",
        "l2_allowed_vlans",
        "wan_type",
        "wan_capacity_mbps",
        "wan_monthly_cost_proxy",
        "wan_latency_ms",
        "wan_srg_tag",
    ):
        assert field not in first_link
    assert "traffic_class" not in payload["demands"][0]


def test_each_new_twin_field_changes_fingerprint_and_round_trips() -> None:
    for field, value in _populated().items():
        twin = make_twin(**{field: value})
        metadata = twin.metadata.model_copy(update={"schema_version": 1})
        twin = twin.model_copy(update={"metadata": metadata})
        assert twin_fingerprint(twin) != LEGACY_FINGERPRINT
        restored = from_json(to_json(twin))
        assert restored == twin
        assert to_json(restored) == to_json(twin)


def test_nested_additive_fields_are_omitted_at_defaults_and_round_trip() -> None:
    plain_link = Link(id="x", endpoints=("a", "b"), capacity_mbps=10, cost=1)
    assert "l2_mode" not in plain_link.model_dump_json()
    link = Link(
        id="x",
        endpoints=("a", "b"),
        capacity_mbps=10,
        cost=1,
        l2_mode=LinkL2Mode.access,
        l2_access_vlan=20,
        wan_type=WanLinkType.mpls,
        wan_monthly_cost_proxy=12.5,
    )
    restored_link = Link.model_validate_json(link.model_dump_json())
    assert restored_link == link
    assert restored_link.l2_mode is LinkL2Mode.access
    assert restored_link.wan_monthly_cost_proxy == 12.5

    plain_demand = TrafficDemand(name="d", source="a", destination="b", bandwidth_mbps=1)
    assert "traffic_class" not in plain_demand.model_dump_json()
    demand = TrafficDemand(
        name="d", source="a", destination="b", bandwidth_mbps=1,
        traffic_class=TrafficClass.voice,
    )
    assert TrafficDemand.model_validate_json(demand.model_dump_json()) == demand

    plain_site = Site(id="s", name="Site")
    assert "site_type" not in plain_site.model_dump_json()
    site = Site(id="s", name="Site", site_type=SiteType.branch)
    assert Site.model_validate_json(site.model_dump_json()) == site
