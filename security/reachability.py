"""S1: deterministic, offline zone reachability and bounded blast radius.

This module models *policy reachability* between design zones. It answers the
question "does the modeled inter-zone policy, together with the modeled routed
topology, permit this named service from one zone to another?". It is a
design-time model only: it never probes, scans, or contacts a network, and it
does not describe an attack path, exploit chain, or any offensive step.

The reachability matrix is a full zone x zone x service grid. Each cell records
the policy decision, whether a modeled route exists, and whether routing could
be determined at all (VLAN-only zones have no device to route between, so their
cell is a policy-only result). The blast radius is a bounded transitive closure
of reachable zone pairs: it shows which other zones a lower-trust zone could
reach by design, not how any host would be compromised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.limits import MAX_BLAST_RADIUS_HOPS, MAX_ROUTE_PROBE_DEVICES
from core.exceptions import NetArchitectError
from core.schemas.validation import Severity
from network.routing import shortest_path

from .models import (
    POLICY_REACHABILITY_NOTE,
    BlastRadius,
    FindingCategory,
    PolicyAction,
    Protocol,
    ReachabilityCell,
    ReachabilityMatrix,
    ReachabilityReport,
    SecurityFinding,
    SecurityModel,
    Service,
    ZoneType,
)
from .policy import evaluate_policy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

# Lower-trust zone categories highlighted when their modeled reachability
# closure includes a zone the designer marked as high criticality.
_EXPOSED_TYPES = frozenset(
    {ZoneType.untrusted_external, ZoneType.guest, ZoneType.iot}
)
_HIGH_CRITICALITY = 4


def _representative_port(service: Service) -> int:
    """Return the deterministic port used to evaluate one named service.

    A named service may span a port range, but a firewall rule either names the
    service or uses ``any_service``. The service's lowest modeled port is a
    stable representative; ``icmp`` and ``any`` use port 0 because they do not
    model ports.
    """
    if service.protocol in {Protocol.icmp, Protocol.any}:
        return 0
    return service.port_start


def _route_status(
    twin: DigitalTwin,
    source_devices: tuple[str, ...],
    destination_devices: tuple[str, ...],
    failures: dict[str, tuple[str, ...]],
) -> tuple[bool, bool]:
    """Return ``(route_exists, routing_modeled)`` for one zone pair.

    Routing is *not modeled* when either zone has no member device, so the cell
    remains a documented policy-only result instead of a false "no route".
    When devices exist, a bounded probe looks for any routed path between them,
    honoring modeled device and link failures from the twin.
    """
    if not source_devices or not destination_devices:
        return True, False
    for source in source_devices[:MAX_ROUTE_PROBE_DEVICES]:
        for destination in destination_devices[:MAX_ROUTE_PROBE_DEVICES]:
            if source == destination:
                return True, True
            try:
                path = shortest_path(
                    twin.topology, source, destination, **failures
                )
            except NetArchitectError:
                continue
            if path.reachable:
                return True, True
    return False, True


def build_reachability_matrix(
    twin: DigitalTwin, model: SecurityModel
) -> ReachabilityMatrix:
    """Build the complete zone x zone x service modeled reachability grid."""
    # Deferred import: digital_twin.models imports security.models, so a module
    # level import here would close an import cycle during package startup.
    from digital_twin import failed_entities

    zones = tuple(zone.id for zone in model.zones)
    services = tuple(service.name for service in model.services)
    service_by_name = {service.name: service for service in model.services}
    zone_devices = {zone.id: zone.member_device_ids for zone in model.zones}
    failures = failed_entities(twin).as_kwargs()
    route_cache: dict[tuple[str, str], tuple[bool, bool]] = {}

    cells: list[ReachabilityCell] = []
    for source_zone in zones:
        for destination_zone in zones:
            same_zone = source_zone == destination_zone
            if same_zone:
                route_exists, routing_modeled = True, True
            else:
                pair = (source_zone, destination_zone)
                if pair not in route_cache:
                    route_cache[pair] = _route_status(
                        twin,
                        zone_devices.get(source_zone, ()),
                        zone_devices.get(destination_zone, ()),
                        failures,
                    )
                route_exists, routing_modeled = route_cache[pair]

            for service_name in services:
                if same_zone:
                    policy_permitted = True
                    reason = (
                        "Same zone; inter-zone policy does not filter "
                        "intra-zone traffic."
                    )
                else:
                    service = service_by_name[service_name]
                    decision = evaluate_policy(
                        model,
                        source_zone,
                        destination_zone,
                        service.protocol,
                        _representative_port(service),
                    )
                    policy_permitted = decision.action is PolicyAction.allow
                    reason = decision.reason
                    if not routing_modeled:
                        reason += (
                            " Routing not modeled for one or both zones; "
                            "policy-only result."
                        )
                cells.append(
                    ReachabilityCell(
                        source_zone=source_zone,
                        destination_zone=destination_zone,
                        service=service_name,
                        policy_permitted=policy_permitted,
                        route_exists=route_exists,
                        routing_modeled=routing_modeled,
                        reachable=policy_permitted and route_exists,
                        reason=reason,
                    )
                )

    return ReachabilityMatrix(zones=zones, services=services, cells=tuple(cells))


def _reachable_edges(
    matrix: ReachabilityMatrix,
) -> dict[str, set[str]]:
    """Collapse the matrix to directed zone edges where any service is reachable."""
    edges: dict[str, set[str]] = {zone: set() for zone in matrix.zones}
    for cell in matrix.cells:
        if cell.reachable and cell.source_zone != cell.destination_zone:
            edges[cell.source_zone].add(cell.destination_zone)
    return edges


def _closure(
    origin: str, edges: dict[str, set[str]], hop_limit: int
) -> tuple[tuple[str, ...], int]:
    """Return the bounded transitive closure from ``origin`` and its hop depth."""
    visited: set[str] = set()
    frontier: set[str] = {origin}
    hop_count = 0
    for hop in range(1, hop_limit + 1):
        following: set[str] = set()
        for zone in frontier:
            for target in edges.get(zone, ()):
                if target != origin and target not in visited:
                    following.add(target)
        if not following:
            break
        visited.update(following)
        frontier = following
        hop_count = hop
    return tuple(sorted(visited)), hop_count


def build_blast_radii(
    model: SecurityModel,
    matrix: ReachabilityMatrix,
    *,
    hop_limit: int = MAX_BLAST_RADIUS_HOPS,
) -> tuple[BlastRadius, ...]:
    """Compute one bounded modeled reachability closure per origin zone."""
    edges = _reachable_edges(matrix)
    criticality = {zone.id: zone.criticality for zone in model.zones}
    radii: list[BlastRadius] = []
    for zone in model.zones:
        direct = tuple(sorted(edges.get(zone.id, ())))
        closure, hops = _closure(zone.id, edges, hop_limit)
        highest = max((criticality[item] for item in closure), default=0)
        radii.append(
            BlastRadius(
                origin_zone=zone.id,
                origin_zone_type=zone.type,
                directly_reachable=direct,
                closure_zones=closure,
                max_criticality_reached=highest,
                exposure=zone.type in _EXPOSED_TYPES and highest >= _HIGH_CRITICALITY,
                hop_count=hops,
            )
        )
    return tuple(radii)


def build_exposure_findings(
    model: SecurityModel, radii: tuple[BlastRadius, ...]
) -> tuple[SecurityFinding, ...]:
    """Highlight lower-trust zones whose closure reaches high-criticality zones."""
    criticality = {zone.id: zone.criticality for zone in model.zones}
    findings: list[SecurityFinding] = []
    for radius in radii:
        if not radius.exposure:
            continue
        high_zones = tuple(
            zone for zone in radius.closure_zones if criticality[zone] >= _HIGH_CRITICALITY
        )
        findings.append(
            SecurityFinding(
                code="REACH-EXPOSURE-HIGH-CRITICALITY",
                category=FindingCategory.design,
                severity=Severity.error,
                affected_entities=(radius.origin_zone, *high_zones),
                explanation=(
                    f"Modeled policy reachability from {radius.origin_zone!r} "
                    f"({radius.origin_zone_type.value}) includes zone(s) with a "
                    f"designer-set criticality of {_HIGH_CRITICALITY} or higher: "
                    f"{', '.join(high_zones)}. This is a policy-reachability "
                    "model, not an attack path or exploit chain."
                ),
                remediation=(
                    "Review the modeled inter-zone policy and zone membership so "
                    "that lower-trust zones cannot reach higher-criticality zones "
                    "by design."
                ),
                evidence=(
                    f"origin_type={radius.origin_zone_type.value}",
                    f"max_criticality_reached={radius.max_criticality_reached}",
                    f"closure_hops={radius.hop_count}",
                    POLICY_REACHABILITY_NOTE,
                ),
            )
        )
    return tuple(findings)


def build_reachability_report(
    twin: DigitalTwin,
    model: SecurityModel,
    *,
    hop_limit: int = MAX_BLAST_RADIUS_HOPS,
) -> ReachabilityReport:
    """Return the full S1 reachability and blast-radius report for one design."""
    matrix = build_reachability_matrix(twin, model)
    radii = build_blast_radii(model, matrix, hop_limit=hop_limit)
    findings = build_exposure_findings(model, radii)
    return ReachabilityReport(
        matrix=matrix,
        blast_radii=radii,
        exposure_findings=findings,
        hop_limit=hop_limit,
    )


__all__ = [
    "POLICY_REACHABILITY_NOTE",
    "build_blast_radii",
    "build_exposure_findings",
    "build_reachability_matrix",
    "build_reachability_report",
]
