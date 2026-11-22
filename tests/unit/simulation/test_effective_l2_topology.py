"""Default-off effective Layer-2 topology option in the evaluator.

Hand check: a three-switch triangle with three equal-cost modeled trunk links
blocks exactly one deterministic link, so a demand takes the two-hop path.
"""

from __future__ import annotations

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.l2.models import L2Design, LinkL2Mode
from simulation import evaluate
from simulation.models import SimulationAssumptions
from tests.unit.digital_twin.helpers import CREATED_AT

LEGACY_ASSUMPTIONS_JSON = (
    '{"thresholds":{"warning_percent":70.0,"critical_percent":90.0,'
    '"overload_percent":100.0},"link_delay_ms":{}}'
)


def test_default_assumptions_json_is_legacy_byte_identical() -> None:
    assert SimulationAssumptions().model_dump_json() == LEGACY_ASSUMPTIONS_JSON


def test_effective_l2_topology_removes_the_deterministic_blocked_link() -> None:
    # Hand: triangle links l1, l2, l3 all cost 1 and carry VLAN 10. The
    # deterministic spanning forest keeps l1 and l2 and blocks l3, so a demand
    # from sw1 to sw3 travels sw1->sw2->sw3 instead of the direct l3 hop.
    twin = DigitalTwin(
        metadata=TwinMetadata(name="Triangle", created_at=CREATED_AT),
        topology=Topology(
            name="Triangle",
            devices=[
                Device(id=f"sw{n}", type=DeviceType.switch, site="hq", role=DeviceRole.access)
                for n in (1, 2, 3)
            ],
            links=[
                Link(
                    id=link_id,
                    endpoints=endpoints,
                    capacity_mbps=100,
                    cost=1,
                    l2_mode=LinkL2Mode.trunk,
                    l2_allowed_vlans=(10,),
                )
                for link_id, endpoints in (
                    ("l1", ("sw1", "sw2")),
                    ("l2", ("sw2", "sw3")),
                    ("l3", ("sw1", "sw3")),
                )
            ],
        ),
        demands=[
            TrafficDemand(name="across", source="sw1", destination="sw3", bandwidth_mbps=1)
        ],
        l2_design=L2Design(gateway_by_vlan={10: "sw1"}),
    )
    baseline = evaluate(twin)
    assert baseline.demands[0].link_ids == ("l3",)

    modeled = evaluate(twin, SimulationAssumptions(use_effective_l2_topology=True))
    assert modeled.demands[0].link_ids == ("l1", "l2")
    assert "l3" in modeled.failed_links
    assert any("modeled spanning-tree" in note for note in modeled.warnings)
