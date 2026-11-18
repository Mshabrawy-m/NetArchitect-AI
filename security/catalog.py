"""Fixed design-weakness catalog and deterministic trigger evaluation.

The catalog is a modeling aid, not an audit standard. Its rules and base
severities are fixed in code so results are reproducible and cannot be changed
by an LLM or by UI state.
"""

from __future__ import annotations

import ipaddress
from itertools import combinations
from typing import TYPE_CHECKING

from core.schemas.network import DeviceType
from core.schemas.validation import Severity
from network.routing import shortest_path

from .models import (
    CatalogRule,
    PolicyAction,
    Protocol,
    SecurityFinding,
    SecurityModel,
)
from .policy import device_zone_map, evaluate_policy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

OVERSIZED_SUBNET_RATIO = 4

RULE_CATALOG: tuple[CatalogRule, ...] = (
    CatalogRule(
        id="SEC-DW-001",
        title="Flat network",
        trigger="The model has at most one zone while the topology has multiple devices.",
        base_severity=Severity.error,
        remediation="Define distinct trust zones and assign VLANs or devices to them.",
    ),
    CatalogRule(
        id="SEC-DW-002",
        title="No management zone",
        trigger="No zone has type management.",
        base_severity=Severity.warning,
        remediation="Add a management zone and restrict access to it with explicit deny rules.",
    ),
    CatalogRule(
        id="SEC-DW-003",
        title="Public-facing server not in DMZ",
        trigger=(
            "A public/web/www server is assigned to a zone whose type is not DMZ, "
            "or is unassigned."
        ),
        base_severity=Severity.error,
        remediation="Place public-facing servers in the DMZ and restrict internal access.",
    ),
    CatalogRule(
        id="SEC-DW-004",
        title="User zone reaches management/server without rule",
        trigger=(
            "A user zone has no enabled deny rule to a modeled management or server zone."
        ),
        base_severity=Severity.error,
        remediation="Add explicit deny rules from user zones to management and server zones.",
    ),
    CatalogRule(
        id="SEC-DW-005",
        title="Guest or IoT zone reaches internal zones",
        trigger=(
            "First-match policy allows guest or IoT traffic to an internal zone."
        ),
        base_severity=Severity.critical,
        remediation="Add explicit deny rules from guest and IoT zones to internal zones.",
    ),
    CatalogRule(
        id="SEC-DW-006",
        title="Single security boundary device / SPOF",
        trigger=(
            "Exactly one modeled boundary device exists and removing it disconnects "
            "devices in two different zones."
        ),
        base_severity=Severity.warning,
        remediation="Model redundant boundary devices or diverse paths between zones.",
    ),
    CatalogRule(
        id="SEC-DW-007",
        title="Oversized subnet relative to hosts",
        trigger=(
            f"A zone's modeled subnet offers more than {OVERSIZED_SUBNET_RATIO}x its "
            "declared expected host count."
        ),
        base_severity=Severity.warning,
        remediation="Right-size the subnet or correct the expected host assumption.",
    ),
    CatalogRule(
        id="SEC-DW-008",
        title="Devices with no zone",
        trigger="A topology device is not assigned to any modeled zone.",
        base_severity=Severity.warning,
        remediation="Assign every modeled device to a zone or document why it is excluded.",
    ),
    CatalogRule(
        id="SEC-DW-009",
        title="Missing inter-department segmentation for criticality >= 4",
        trigger=(
            "Two or more zones have criticality >= 4 and an enabled deny rule is "
            "missing for one ordered pair."
        ),
        base_severity=Severity.error,
        remediation="Add explicit deny rules between all pairs of high-criticality zones.",
    ),
)

_CATALOG_BY_ID = {rule.id: rule for rule in RULE_CATALOG}


def catalog_rule(rule_id: str) -> CatalogRule:
    """Return one fixed catalog entry by stable id."""
    return _CATALOG_BY_ID[rule_id]


def _finding(
    rule_id: str,
    *,
    affected: tuple[str, ...],
    explanation: str,
    evidence: tuple[str, ...] = (),
    proposal_src_zone: str = "",
    proposal_dst_zone: str = "",
) -> SecurityFinding:
    rule = catalog_rule(rule_id)
    return SecurityFinding(
        code=rule.id,
        category="design",
        severity=rule.base_severity,
        affected_entities=affected,
        explanation=explanation,
        remediation=rule.remediation,
        evidence=evidence,
        proposal_src_zone=proposal_src_zone,
        proposal_dst_zone=proposal_dst_zone,
    )


def _flat_network(twin: DigitalTwin, model: SecurityModel) -> tuple[SecurityFinding, ...]:
    if len(model.zones) <= 1 and len(twin.topology.devices) > 1:
        return (
            _finding(
                "SEC-DW-001",
                affected=tuple(zone.id for zone in model.zones) or ("topology",),
                explanation=(
                    f"The model has {len(model.zones)} zone(s) for "
                    f"{len(twin.topology.devices)} devices, so no meaningful trust "
                    "boundary is modeled."
                ),
            ),
        )
    return ()


def _no_management_zone(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    from .models import ZoneType

    if not any(zone.type is ZoneType.management for zone in model.zones):
        return (
            _finding(
                "SEC-DW-002",
                affected=("security-model",),
                explanation="No management zone is modeled for the design.",
            ),
        )
    return ()


def _public_server_outside_dmz(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    from .models import ZoneType

    public_tokens = ("public", "web", "www", "internet")
    zones = {zone.id: zone for zone in model.zones}
    mapping = device_zone_map(model)
    findings: list[SecurityFinding] = []
    for device in twin.topology.devices:
        zone = zones.get(mapping.get(device.id, ""))
        text = f"{device.id} {zone.name if zone else ''}".lower()
        looks_public = any(token in text for token in public_tokens)
        if not looks_public:
            continue
        if zone is not None and zone.type is ZoneType.dmz:
            continue
        findings.append(
            _finding(
                "SEC-DW-003",
                affected=(device.id,),
                explanation=(
                    f"Public-facing server {device.id!r} is in "
                    f"{zone.name if zone else 'no zone'} instead of the DMZ."
                ),
                evidence=(f"device_type={device.type.value}",),
            )
        )
    return tuple(findings)


def _user_to_restricted_without_rule(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    from .models import ZoneType

    targets = {ZoneType.management, ZoneType.server}
    user_zones = [zone for zone in model.zones if zone.type is ZoneType.user]
    target_zones = [zone for zone in model.zones if zone.type in targets]
    findings: list[SecurityFinding] = []
    for source in user_zones:
        for target in target_zones:
            has_deny = any(
                rule.enabled
                and rule.src_zone == source.id
                and rule.dst_zone == target.id
                and rule.action is PolicyAction.deny
                for rule in model.rules
            )
            if has_deny:
                continue
            findings.append(
                _finding(
                    "SEC-DW-004",
                    affected=(source.id, target.id),
                    explanation=(
                        f"User zone {source.id!r} has no explicit deny rule to "
                        f"{target.id!r}."
                    ),
                    evidence=("explicit_deny_rule_present=false",),
                    proposal_src_zone=source.id,
                    proposal_dst_zone=target.id,
                )
            )
    return tuple(findings)


def _guest_iot_to_internal(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    from .models import ZoneType

    sources = {
        ZoneType.guest,
        ZoneType.iot,
    }
    internal = {
        ZoneType.dmz,
        ZoneType.server,
        ZoneType.user,
        ZoneType.management,
        ZoneType.other,
    }
    findings: list[SecurityFinding] = []
    for source in (zone for zone in model.zones if zone.type in sources):
        for target in (zone for zone in model.zones if zone.type in internal):
            decision = evaluate_policy(
                model, source.id, target.id, Protocol.any, 0
            )
            if decision.action is not PolicyAction.allow:
                continue
            findings.append(
                _finding(
                    "SEC-DW-005",
                    affected=(source.id, target.id),
                    explanation=(
                        f"Policy permits {source.type.value} zone {source.id!r} to "
                        f"reach internal zone {target.id!r}: {decision.reason}"
                    ),
                    evidence=(f"matched_rule={decision.matched_rule_id or 'default'}",),
                    proposal_src_zone=source.id,
                    proposal_dst_zone=target.id,
                )
            )
    return tuple(findings)


def _single_boundary_spof(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    boundaries = [
        device
        for device in twin.topology.devices
        if device.type is DeviceType.firewall
        or device.role.value in {"border", "wan"}
    ]
    if len(boundaries) != 1 or len(model.zones) < 2:
        return ()
    boundary = boundaries[0]
    zone_candidates: list[tuple[str, str]] = []
    for zone in model.zones:
        alternatives = [
            device_id for device_id in zone.member_device_ids if device_id != boundary.id
        ]
        if alternatives:
            zone_candidates.append((zone.id, alternatives[0]))
    if len(zone_candidates) < 2:
        return ()
    disconnected: tuple[str, str] | None = None
    for (zone_a, device_a), (zone_b, device_b) in combinations(zone_candidates, 2):
        path = shortest_path(
            twin.topology,
            device_a,
            device_b,
            failed_devices=(boundary.id,),
        )
        if not path.reachable:
            disconnected = (zone_a, zone_b)
            break
    if disconnected is None:
        return ()
    return (
        _finding(
            "SEC-DW-006",
            affected=(boundary.id, *disconnected),
            explanation=(
                f"Boundary device {boundary.id!r} is the only modeled boundary; its "
                f"failure disconnects {disconnected[0]!r} from {disconnected[1]!r}."
            ),
            evidence=("failed_devices=(boundary)",),
        ),
    )


def _oversized_subnets(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    vlan_subnets: dict[int, list[str]] = {}
    if twin.addressing is not None:
        for plan in twin.addressing.vlan_plans:
            vlan_subnets.setdefault(plan.vlan_id, []).extend(
                str(subnet.network) for subnet in plan.subnets
            )
    findings: list[SecurityFinding] = []
    for zone in model.zones:
        if zone.expected_hosts is None:
            continue
        oversized: list[str] = []
        for vlan_id in zone.member_vlan_ids:
            for network in vlan_subnets.get(vlan_id, ()):
                parsed = ipaddress.ip_network(network, strict=False)
                usable = max(0, int(parsed.num_addresses) - 2)
                expected = zone.expected_hosts
                if expected == 0 or usable > OVERSIZED_SUBNET_RATIO * expected:
                    oversized.append(f"{network}:usable={usable},expected={expected}")
        if oversized:
            findings.append(
                _finding(
                    "SEC-DW-007",
                    affected=(zone.id,),
                    explanation=(
                        f"Zone {zone.id!r} declares {zone.expected_hosts} host(s) but "
                        f"its modeled subnets exceed the {OVERSIZED_SUBNET_RATIO}x bound."
                    ),
                    evidence=tuple(sorted(oversized)),
                )
            )
    return tuple(findings)


def _devices_without_zone(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    assigned = set(device_zone_map(model))
    unassigned = sorted(
        device.id for device in twin.topology.devices if device.id not in assigned
    )
    if not unassigned:
        return ()
    return (
        _finding(
            "SEC-DW-008",
            affected=tuple(unassigned),
            explanation=(
                f"{len(unassigned)} topology device(s) have no modeled zone: "
                f"{', '.join(unassigned)}."
            ),
        ),
    )


def _high_criticality_segmentation(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    high = [zone for zone in model.zones if zone.criticality >= 4]
    if len(high) < 2:
        return ()
    findings: list[SecurityFinding] = []
    for source in high:
        for target in high:
            if source.id == target.id:
                continue
            has_deny = any(
                rule.enabled
                and rule.src_zone == source.id
                and rule.dst_zone == target.id
                and rule.action is PolicyAction.deny
                for rule in model.rules
            )
            if has_deny:
                continue
            findings.append(
                _finding(
                    "SEC-DW-009",
                    affected=(source.id, target.id),
                    explanation=(
                        f"No explicit deny rule separates high-criticality zones "
                        f"{source.id!r} and {target.id!r}."
                    ),
                    evidence=(
                        f"source_criticality={source.criticality}",
                        f"target_criticality={target.criticality}",
                    ),
                    proposal_src_zone=source.id,
                    proposal_dst_zone=target.id,
                )
            )
    return tuple(findings)


def evaluate_design_rules(
    twin: DigitalTwin, model: SecurityModel
) -> tuple[SecurityFinding, ...]:
    """Evaluate every fixed catalog rule in stable catalog order."""
    checks = (
        _flat_network,
        _no_management_zone,
        _public_server_outside_dmz,
        _user_to_restricted_without_rule,
        _guest_iot_to_internal,
        _single_boundary_spof,
        _oversized_subnets,
        _devices_without_zone,
        _high_criticality_segmentation,
    )
    findings: list[SecurityFinding] = []
    for check in checks:
        findings.extend(check(twin, model))
    return tuple(findings)


__all__ = [
    "OVERSIZED_SUBNET_RATIO",
    "RULE_CATALOG",
    "catalog_rule",
    "evaluate_design_rules",
]
