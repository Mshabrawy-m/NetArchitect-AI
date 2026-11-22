"""Deterministic design findings for the modeled QoS admission plan.

This module turns already-computed QoS inputs and an evaluator state into stable
findings. It is a review layer only: it does not simulate queues, drops,
schedulers, or device hardware, and it never mutates the twin or the state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.schemas.validation import Finding, Severity
from digital_twin.models import DigitalTwin

from .admission import STARVED_REASON
from .models import QosDesign

if TYPE_CHECKING:  # pragma: no cover - typing only
    from simulation.models import NetworkState

UNKNOWN_CAP_LINK_CODE = "qos_unknown_cap_link"
DEMAND_STARVED_CODE = "qos_demand_starved"


def qos_findings(
    twin: DigitalTwin,
    state: NetworkState | None = None,
    *,
    design: QosDesign | None = None,
) -> tuple[Finding, ...]:
    """Return modeled QoS findings from the twin and optional evaluator state.

    An unknown cap link cannot be applied to the modeled topology, so it is an
    error. A demand carrying the modeled ``STARVED_REASON`` is also an error: the
    deterministic admission model selected another class first. Informational
    notes about the model itself are recorded by the evaluator, not here.
    """
    resolved = design if design is not None else twin.qos_design
    link_ids = {link.id for link in twin.topology.links}
    findings: list[Finding] = []

    if resolved is not None:
        for cap in sorted(
            resolved.class_share_caps,
            key=lambda item: (item.link_id, item.traffic_class.value),
        ):
            if cap.link_id in link_ids:
                continue
            findings.append(
                Finding(
                    severity=Severity.error,
                    code=UNKNOWN_CAP_LINK_CODE,
                    affected_entities=[cap.link_id, cap.traffic_class.value],
                    explanation=(
                        f"Modeled QoS class cap for {cap.traffic_class.value} refers "
                        f"to unknown link {cap.link_id!r}; no topology link can "
                        "carry that cap."
                    ),
                    remediation=(
                        "Use an existing topology link id or remove the modeled cap."
                    ),
                )
            )

    if state is not None:
        for demand in state.demands:
            if (demand.reason or "") != STARVED_REASON:
                continue
            findings.append(
                Finding(
                    severity=Severity.error,
                    code=DEMAND_STARVED_CODE,
                    affected_entities=[
                        demand.name,
                        demand.source,
                        demand.destination,
                    ],
                    explanation=(
                        f"Demand {demand.name!r} was not admitted because a higher-"
                        "priority modeled QoS class consumed the link capacity "
                        "or reached its modeled share cap."
                    ),
                    remediation=(
                        "Revise the modeled class order, class caps, demand "
                        "classes, or link capacity, then re-run the admission "
                        "review. This is an admission model, not queue behavior."
                    ),
                )
            )

    return tuple(findings)


__all__ = [
    "DEMAND_STARVED_CODE",
    "UNKNOWN_CAP_LINK_CODE",
    "qos_findings",
]
