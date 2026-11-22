"""Tests for deterministic, default-off QoS admission inputs."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.qos.admission import (
    ADMISSION_NOTE,
    STARVED_REASON,
    build_qos_admission_plan,
    class_caps_for_link,
    demand_traffic_class,
    per_class_cap_mbps,
    qos_admission_order,
    starved_reason_for,
)
from network.qos.models import ClassShareCap, QosDesign, TrafficClass

_CREATED_AT = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


def _demand(
    name: str,
    bandwidth_mbps: float = 10.0,
    traffic_class: TrafficClass | None = None,
    *,
    source: str = "a",
    destination: str = "b",
) -> TrafficDemand:
    return TrafficDemand(
        name=name,
        source=source,
        destination=destination,
        bandwidth_mbps=bandwidth_mbps,
        traffic_class=traffic_class,
    )


def _twin(
    demands: tuple[TrafficDemand, ...] = (),
    *,
    design: QosDesign | None = None,
) -> DigitalTwin:
    return DigitalTwin(
        metadata=TwinMetadata(name="QoS test", created_at=_CREATED_AT),
        topology=Topology(
            name="QoS test",
            devices=[
                Device(id="a", type=DeviceType.router, site="s", role=DeviceRole.core),
                Device(id="b", type=DeviceType.router, site="s", role=DeviceRole.core),
            ],
            links=[
                Link(
                    id="l1",
                    endpoints=("a", "b"),
                    capacity_mbps=100.0,
                    cost=1.0,
                ),
                Link(
                    id="l2",
                    endpoints=("a", "b"),
                    capacity_mbps=100.0,
                    cost=2.0,
                ),
            ],
        ),
        demands=demands,
        qos_design=design,
    )


def test_order_uses_class_priority() -> None:
    twin = _twin(
        (
            _demand("bulk", 90.0, TrafficClass.best_effort),  # index 0, priority 3
            _demand("voice", 5.0, TrafficClass.voice),  # index 1, priority 0
            _demand("video", 40.0, TrafficClass.video),  # index 2, priority 1
            _demand("critical", 10.0, TrafficClass.critical),  # index 3, priority 2
        )
    )

    # Hand-computed: priorities 0 (voice), 1 (video), 2 (critical), 3 (bulk).
    assert qos_admission_order(twin) == (1, 2, 3, 0)


def test_order_ties_break_on_bandwidth_name_source_and_destination() -> None:
    twin = _twin(
        (
            _demand("v", 10.0, TrafficClass.voice, source="b", destination="x"),
            _demand("v", 10.0, TrafficClass.voice, source="a", destination="z"),
            _demand("v", 10.0, TrafficClass.voice, source="a", destination="y"),
            _demand("big", 10.0, TrafficClass.voice, source="a", destination="y"),
            _demand("huge", 20.0, TrafficClass.voice, source="z", destination="z"),
        )
    )

    # Hand-computed: 20 Mbps first (4); then 10 Mbps by name "big" (3),
    # "v"/a/y (2) before "v"/a/z (1); "v"/b/x (0) has the last source.
    assert qos_admission_order(twin) == (4, 3, 2, 1, 0)


def test_class_caps_and_cap_mbps_conversion() -> None:
    design = QosDesign(
        class_share_caps=(
            ClassShareCap(
                link_id="l1", traffic_class=TrafficClass.voice, share_cap=0.2
            ),
            ClassShareCap(
                link_id="l1",
                traffic_class=TrafficClass.best_effort,
                share_cap=0.5,
            ),
            ClassShareCap(
                link_id="l2", traffic_class=TrafficClass.video, share_cap=0.1
            ),
        )
    )

    assert class_caps_for_link(design, "l1") == {
        TrafficClass.voice: 0.2,
        TrafficClass.best_effort: 0.5,
    }
    # Video is capped only on l2; critical has no cap on either link.
    assert class_caps_for_link(design, "l2") == {TrafficClass.video: 0.1}
    assert TrafficClass.critical not in class_caps_for_link(design, "l1")

    caps = class_caps_for_link(design, "l1")
    # Hand-computed on a 100 Mbps link: 0.2 * 100 = 20, 0.5 * 100 = 50.
    assert per_class_cap_mbps(100.0, caps) == {
        TrafficClass.voice: 20.0,
        TrafficClass.best_effort: 50.0,
    }
    assert per_class_cap_mbps(100.0, {}) == {}
    # Hand-computed: 0.2 * 33.333333 = 6.6666666 -> 6.666667 (6 decimals).
    assert per_class_cap_mbps(33.333333, {TrafficClass.voice: 0.2}) == {
        TrafficClass.voice: 6.666667
    }


def test_starved_reason_labels_are_modeled_not_measured() -> None:
    # Hand-computed: cap 20 reached by 20 admitted Mbps -> starved.
    assert starved_reason_for(TrafficClass.best_effort, 20.0, 20.0) == STARVED_REASON
    # A lower-priority class behind admitted traffic is labeled starved.
    assert starved_reason_for(TrafficClass.critical, 20.0, None) == STARVED_REASON
    # Nothing admitted yet and cap not reached -> generic capacity label.
    assert (
        starved_reason_for(TrafficClass.best_effort, 0.0, 50.0)
        == "insufficient capacity"
    )
    assert starved_reason_for(TrafficClass.voice, 0.0, None) == "insufficient capacity"
    # Voice has no higher-priority class, so it cannot be starved by one.
    assert starved_reason_for(TrafficClass.voice, 20.0, None) == (
        "insufficient capacity"
    )


def test_default_design_none_keeps_legacy_behavior() -> None:
    twin = _twin(
        (
            _demand("big", 80.0),
            _demand("small-a", 20.0),
            _demand("small-b", 20.0),
        )
    )

    assert all(
        demand_traffic_class(demand) is TrafficClass.best_effort
        for demand in twin.demands
    )
    assert class_caps_for_link(None, "l1") == {}
    # Hand-computed: all best effort -> 80 Mbps first, then "small-a" <
    # "small-b" on the 20 Mbps tie.
    assert qos_admission_order(twin) == (0, 1, 2)

    plan = build_qos_admission_plan(twin)
    assert plan.demand_indices == (0, 1, 2)
    assert plan.class_caps == {}
    assert plan.note == ADMISSION_NOTE

    empty_twin = _twin()
    assert qos_admission_order(empty_twin) == ()
    assert build_qos_admission_plan(empty_twin).demand_indices == ()
    assert build_qos_admission_plan(empty_twin).class_caps == {}


def test_explicit_class_and_design_precedence() -> None:
    twin_design = QosDesign(default_class=TrafficClass.critical)
    twin = _twin(
        (
            _demand("explicit", 1.0, TrafficClass.voice),
            _demand("implicit", 1.0),
        ),
        design=twin_design,
    )
    explicit_design = QosDesign(default_class=TrafficClass.video)

    assert demand_traffic_class(twin.demands[0]) is TrafficClass.voice
    assert demand_traffic_class(twin.demands[1], twin_design) is (TrafficClass.critical)
    # Explicit class wins over either design default.
    assert demand_traffic_class(twin.demands[0], explicit_design) is (
        TrafficClass.voice
    )
    # An explicit design overrides the design stored on the twin.
    assert demand_traffic_class(twin.demands[1], explicit_design) is (
        TrafficClass.video
    )
    # Both demands have priority 1 under the explicit design; equal bandwidth
    # ties on name, so "explicit" (0) precedes "implicit" (1).
    assert qos_admission_order(twin, explicit_design) == (0, 1)


def test_build_plan_includes_only_links_with_caps() -> None:
    design = QosDesign(
        class_share_caps=(
            ClassShareCap(
                link_id="l1", traffic_class=TrafficClass.voice, share_cap=0.2
            ),
        )
    )
    twin = _twin((_demand("voice", 5.0, TrafficClass.voice),), design=design)

    plan = build_qos_admission_plan(twin)

    assert plan.demand_indices == (0,)
    assert plan.class_caps == {"l1": {TrafficClass.voice: 0.2}}
    assert plan.note == ADMISSION_NOTE
    # Building the plan never mutates the twin or its design.
    assert twin.qos_design == design


def test_qos_design_json_round_trip_and_unique_keys() -> None:
    voice_cap = ClassShareCap(
        link_id="l1", traffic_class=TrafficClass.voice, share_cap=0.2
    )
    best_effort_cap = ClassShareCap(
        link_id="l1", traffic_class=TrafficClass.best_effort, share_cap=0.5
    )
    design = QosDesign(
        default_class=TrafficClass.critical,
        class_share_caps=(voice_cap, best_effort_cap),
    )

    assert QosDesign.model_validate_json(design.model_dump_json()) == design
    assert _twin(design=design).qos_design == design

    with pytest.raises(ValidationError, match="unique"):
        QosDesign(
            class_share_caps=(
                voice_cap,
                ClassShareCap(
                    link_id="l1", traffic_class=TrafficClass.voice, share_cap=0.4
                ),
            )
        )
