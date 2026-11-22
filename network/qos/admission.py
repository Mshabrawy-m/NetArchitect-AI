"""Deterministic inputs for modeled strict-priority QoS admission.

This module classifies designer-supplied demands and prepares per-link class
caps for an admission model. It is not a queueing simulator: it does not model
queues, drops, schedulers, or device hardware, and it never mutates its inputs.
With no QoS design, every helper reduces to legacy behavior (best effort, no
caps), so default-off results are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.schemas.routing import TrafficDemand
from digital_twin.models import DigitalTwin

from .models import TRAFFIC_CLASS_PRIORITY, QosDesign, TrafficClass

STARVED_REASON = "unserved: class starved"
ADMISSION_NOTE = (
    "Modeled strict-priority admission by class on each link; not a queueing simulator."
)

# This is a modeled label, not a runtime measurement. It intentionally matches
# the generic legacy evaluator label without importing that engine here.
_INSUFFICIENT_CAPACITY_REASON = "insufficient capacity"


def _resolved_design(
    twin: DigitalTwin,
    design: QosDesign | None,
) -> QosDesign | None:
    """Prefer an explicit design, then the additive design stored on the twin."""
    return design if design is not None else twin.qos_design


def demand_traffic_class(
    demand: TrafficDemand,
    design: QosDesign | None = None,
) -> TrafficClass:
    """Return the demand's explicit class, the design default, or best effort."""
    if demand.traffic_class is not None:
        return demand.traffic_class
    if design is not None:
        return design.default_class
    return TrafficClass.best_effort


def class_caps_for_link(
    design: QosDesign | None,
    link_id: str,
) -> dict[TrafficClass, float]:
    """Return modeled class share caps for ``link_id`` (fractions of capacity).

    Classes without a cap on this link are absent from the result. An absent
    design means no modeled caps.
    """
    if design is None:
        return {}
    return {
        cap.traffic_class: cap.share_cap
        for cap in design.class_share_caps
        if cap.link_id == link_id
    }


def qos_admission_order(
    twin: DigitalTwin,
    design: QosDesign | None = None,
) -> tuple[int, ...]:
    """Return demand indices in modeled strict-priority admission order.

    The deterministic key is ``(class priority, -bandwidth, name, source,
    destination)``. Python's stable sort leaves demands identical under that
    key in their original twin order.
    """
    resolved = _resolved_design(twin, design)
    return tuple(
        index
        for index, _ in sorted(
            enumerate(twin.demands),
            key=lambda item: (
                TRAFFIC_CLASS_PRIORITY[demand_traffic_class(item[1], resolved)],
                -item[1].bandwidth_mbps,
                item[1].name,
                item[1].source,
                item[1].destination,
            ),
        )
    )


def per_class_cap_mbps(
    link_capacity_mbps: float,
    caps: Mapping[TrafficClass, float],
) -> dict[TrafficClass, float]:
    """Convert class share caps to Mbps on one link, rounded to 6 decimals."""
    return {
        traffic_class: round(share_cap * link_capacity_mbps, 6)
        for traffic_class, share_cap in caps.items()
    }


def starved_reason_for(
    traffic_class: TrafficClass,
    admitted_mbps: float,
    cap_mbps: float | None,
) -> str:
    """Return a modeled label for why a class's demand was not served.

    ``admitted_mbps`` is bandwidth already admitted on the link before this
    class; a positive value means a higher-priority class was served, so a
    lower-priority class is labeled starved. Reaching a class cap is also
    starvation. These are admission-model labels only, not queue observations.
    """
    behind_admitted_class = (
        TRAFFIC_CLASS_PRIORITY[traffic_class] > 0 and admitted_mbps > 0.0
    )
    cap_reached = cap_mbps is not None and admitted_mbps >= cap_mbps
    if behind_admitted_class or cap_reached:
        return STARVED_REASON
    return _INSUFFICIENT_CAPACITY_REASON


@dataclass(frozen=True)
class QosAdmissionPlan:
    """Precomputed, immutable-shaped admission inputs; no queueing state."""

    demand_indices: tuple[int, ...]
    class_caps: dict[str, dict[TrafficClass, float]]
    note: str = ADMISSION_NOTE


def build_qos_admission_plan(
    twin: DigitalTwin,
    design: QosDesign | None = None,
) -> QosAdmissionPlan:
    """Bundle admission order and share caps for evaluator use.

    Only links with at least one modeled cap are included. With no design the
    plan carries an empty cap map, preserving legacy default-off behavior.
    """
    resolved = _resolved_design(twin, design)
    class_caps: dict[str, dict[TrafficClass, float]] = {}
    if resolved is not None:
        for link in twin.topology.links:
            caps = class_caps_for_link(resolved, link.id)
            if caps:
                class_caps[link.id] = caps
    return QosAdmissionPlan(
        demand_indices=qos_admission_order(twin, resolved),
        class_caps=class_caps,
        note=ADMISSION_NOTE,
    )


__all__ = [
    "ADMISSION_NOTE",
    "STARVED_REASON",
    "QosAdmissionPlan",
    "build_qos_admission_plan",
    "class_caps_for_link",
    "demand_traffic_class",
    "per_class_cap_mbps",
    "qos_admission_order",
    "starved_reason_for",
]
