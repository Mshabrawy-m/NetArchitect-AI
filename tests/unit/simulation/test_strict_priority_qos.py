"""Default-off strict-priority QoS admission option in the evaluator.

Hand check: a single 100 Mbps link shared by two 80 Mbps demands serves the
higher-priority class and labels the starved class with a modeled reason.
"""

from __future__ import annotations

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.qos.models import QosDesign, TrafficClass
from simulation import evaluate
from simulation.models import RoutingMode, SimulationAssumptions
from tests.unit.digital_twin.helpers import CREATED_AT


def _two_device_twin(demands: tuple[TrafficDemand, ...]) -> DigitalTwin:
    return DigitalTwin(
        metadata=TwinMetadata(name="QoS check", created_at=CREATED_AT),
        topology=Topology(
            name="One link",
            devices=[
                Device(id="a", type=DeviceType.switch, site="hq", role=DeviceRole.access),
                Device(id="b", type=DeviceType.switch, site="hq", role=DeviceRole.access),
            ],
            links=[Link(id="l1", endpoints=("a", "b"), capacity_mbps=100, cost=1)],
        ),
        demands=demands,
    )


def test_strict_priority_serves_voice_and_reports_starved_best_effort() -> None:
    # Hand: link capacity 100 Mbps. Voice 80 Mbps is admitted first. The remaining
    # 20 Mbps cannot carry best effort 80 Mbps, so the modeled reason must be
    # "unserved: class starved" rather than the legacy generic reason.
    twin = _two_device_twin(
        (
            TrafficDemand(
                name="aaa-best-effort",
                source="a",
                destination="b",
                bandwidth_mbps=80,
                traffic_class=TrafficClass.best_effort,
            ),
            TrafficDemand(
                name="zzz-voice",
                source="a",
                destination="b",
                bandwidth_mbps=80,
                traffic_class=TrafficClass.voice,
            ),
        )
    )
    baseline = evaluate(twin, SimulationAssumptions(routing_mode=RoutingMode.capacity_aware))
    assert [item.name for item in baseline.demands if item.served] == ["aaa-best-effort"]
    assert [item.reason for item in baseline.unserved_demands] == ["insufficient capacity"]

    modeled = evaluate(
        twin,
        SimulationAssumptions(
            routing_mode=RoutingMode.capacity_aware,
            enable_strict_priority_qos=True,
        ),
    )
    assert [item.name for item in modeled.demands if item.served] == ["zzz-voice"]
    assert [item.reason for item in modeled.unserved_demands] == [
        "unserved: class starved"
    ]
    assert any("admission model" in note or "not a queueing simulator" in note for note in modeled.warnings)


def test_qos_design_default_class_does_not_change_legacy_order() -> None:
    # Hand: with no explicit traffic classes, two equal 50 Mbps demands keep the
    # legacy bandwidth/name order even when a QosDesign with caps is stored.
    twin = DigitalTwin(
        metadata=TwinMetadata(name="Legacy order", created_at=CREATED_AT),
        topology=Topology(
            name="One link",
            devices=[
                Device(id="a", type=DeviceType.host, site="hq", role=DeviceRole.access),
                Device(id="b", type=DeviceType.host, site="hq", role=DeviceRole.access),
            ],
            links=[Link(id="l1", endpoints=("a", "b"), capacity_mbps=100, cost=1)],
        ),
        demands=[
            TrafficDemand(name="aaa", source="a", destination="b", bandwidth_mbps=50),
            TrafficDemand(name="zzz", source="a", destination="b", bandwidth_mbps=50),
        ],
        qos_design=QosDesign(),
    )
    state = evaluate(twin, SimulationAssumptions(routing_mode=RoutingMode.capacity_aware))
    assert [item.name for item in state.demands if item.served] == ["aaa", "zzz"]
