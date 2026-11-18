"""Stateless policy evaluation and routing-aware flow checks.

Policy evaluation is a pure function of a :class:`SecurityModel`. Flow checks
combine the deterministic routing engine with that policy: a flow can fail
because no route exists or because the first-match policy denies a zone
boundary. No packet is sent and no device is contacted.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from core.exceptions import NetArchitectError
from network.routing import shortest_path

from .models import (
    FlowCheckResult,
    FlowRequest,
    FlowVerdict,
    PolicyAction,
    PolicyDecision,
    Protocol,
    SecurityModel,
    ZoneTransition,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

UNASSIGNED_ZONE = "(unassigned)"


def device_zone_map(model: SecurityModel) -> dict[str, str]:
    """Return the first zone id assigned to each device, in model order."""
    mapping: dict[str, str] = {}
    for zone in model.zones:
        for device_id in zone.member_device_ids:
            mapping.setdefault(device_id, zone.id)
    return mapping


def evaluate_policy(
    model: SecurityModel,
    source_zone: str,
    destination_zone: str,
    protocol: Protocol,
    port: int,
) -> PolicyDecision:
    """Evaluate one flow against enabled rules using first-match semantics.

    Rules are sorted by ``order``. Disabled rules are skipped. The first enabled
    rule whose zones and service match decides the flow; if none matches, the
    model's explicit default action applies.
    """
    if source_zone == destination_zone:
        return PolicyDecision(
            source_zone=source_zone,
            destination_zone=destination_zone,
            protocol=protocol,
            port=port,
            action=PolicyAction.allow,
            reason="Intra-zone traffic is not filtered by the inter-zone policy.",
        )

    for rule in model.ordered_rules:
        if not rule.enabled:
            continue
        if rule.src_zone != source_zone or rule.dst_zone != destination_zone:
            continue
        service_match = rule.any_service or any(
            service.matches(protocol, port)
            for service in (
                next((item for item in model.services if item.name == name), None)
                for name in rule.services
            )
            if service is not None
        )
        if not service_match:
            continue
        return PolicyDecision(
            source_zone=source_zone,
            destination_zone=destination_zone,
            protocol=protocol,
            port=port,
            action=rule.action,
            matched_rule_id=rule.id,
            reason=(
                f"First matching rule {rule.id!r} with action {rule.action.value}."
            ),
        )

    return PolicyDecision(
        source_zone=source_zone,
        destination_zone=destination_zone,
        protocol=protocol,
        port=port,
        action=model.default_action,
        reason=(
            f"No rule matched; explicit default action {model.default_action.value} applies."
        ),
    )


def _transitions(
    model: SecurityModel,
    request: FlowRequest,
    device_path: tuple[str, ...],
) -> tuple[ZoneTransition, ...]:
    mapping = device_zone_map(model)
    transitions: list[ZoneTransition] = []
    for index, (start, end) in enumerate(pairwise(device_path), start=1):
        from_zone = mapping.get(start, UNASSIGNED_ZONE)
        to_zone = mapping.get(end, UNASSIGNED_ZONE)
        if from_zone == to_zone:
            continue
        transitions.append(
            ZoneTransition(
                index=index,
                from_zone=from_zone,
                to_zone=to_zone,
                from_device=start,
                to_device=end,
                decision=evaluate_policy(
                    model, from_zone, to_zone, request.protocol, request.port
                ),
            )
        )
    return tuple(transitions)


def check_flow(
    twin: DigitalTwin,
    model: SecurityModel,
    request: FlowRequest,
) -> FlowCheckResult:
    """Check whether one modeled flow has a route and is policy-permitted."""
    mapping = device_zone_map(model)
    source_zone = mapping.get(request.source_device_id, "")
    destination_zone = mapping.get(request.destination_device_id, "")
    if not source_zone or not destination_zone:
        missing = [
            device_id
            for device_id, zone in (
                (request.source_device_id, source_zone),
                (request.destination_device_id, destination_zone),
            )
            if not zone
        ]
        return FlowCheckResult(
            request=request,
            verdict=FlowVerdict.unassigned_zone,
            route_reachable=False,
            policy_permitted=False,
            source_zone=source_zone,
            destination_zone=destination_zone,
            reason=f"Devices without a modeled zone: {', '.join(missing)}.",
        )

    try:
        path = shortest_path(
            twin.topology, request.source_device_id, request.destination_device_id
        )
    except NetArchitectError as error:
        return FlowCheckResult(
            request=request,
            verdict=FlowVerdict.no_route,
            route_reachable=False,
            policy_permitted=False,
            source_zone=source_zone,
            destination_zone=destination_zone,
            reason=str(error),
        )

    if not path.reachable:
        return FlowCheckResult(
            request=request,
            verdict=FlowVerdict.no_route,
            route_reachable=False,
            policy_permitted=False,
            source_zone=source_zone,
            destination_zone=destination_zone,
            reason=path.reason or "No modeled route between the endpoints.",
        )

    device_path = tuple(path.device_ids)
    transitions = _transitions(model, request, device_path)
    denied = [
        transition
        for transition in transitions
        if transition.decision.action is PolicyAction.deny
    ]
    if denied:
        detail = ", ".join(
            f"{item.from_zone}->{item.to_zone} ({item.decision.reason})"
            for item in denied
        )
        return FlowCheckResult(
            request=request,
            verdict=FlowVerdict.policy_denied,
            route_reachable=True,
            policy_permitted=False,
            source_zone=source_zone,
            destination_zone=destination_zone,
            device_path=device_path,
            zone_transitions=transitions,
            reason=f"Policy denied at: {detail}.",
        )

    return FlowCheckResult(
        request=request,
        verdict=FlowVerdict.allowed,
        route_reachable=True,
        policy_permitted=True,
        source_zone=source_zone,
        destination_zone=destination_zone,
        device_path=device_path,
        zone_transitions=transitions,
        reason=(
            f"Route found with {path.hop_count} hop(s); "
            f"{len(transitions)} zone boundary check(s) passed."
        ),
    )


__all__ = ["UNASSIGNED_ZONE", "check_flow", "device_zone_map", "evaluate_policy"]
