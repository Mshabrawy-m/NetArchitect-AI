"""S2: visible, deterministic 0--100 design segmentation score.

The score is a *design modeling* aid derived only from the twin and the modeled
security policy. It is not a measured security rating, not a CVE/CVSS score, and
not an audit result. Every input is shown in :class:`SegmentationScore.inputs`
so a reader can recompute the number by hand.

FORMULA (all subscores are clamped to [0, 1]; weights sum to 1.0)::

    score = round(100 * (
        0.25 * S_default
      + 0.30 * S_least
      + 0.30 * S_trust
      + 0.15 * S_broadcast
    ))

Inputs, in full:

* ``S_default`` -- explicit default posture. ``1.0`` when
  ``model.default_action == deny`` and ``0.0`` when it is ``allow``. A single
  global default is the only default the model represents.

* ``S_least`` -- allowed-vs-needed service precision. Let ``allowed`` be the set
  of reachable ``(source_zone, destination_zone, service)`` triples from the S1
  policy-reachability matrix (policy permitted AND a modeled route, or a
  policy-only cell where routing is not modeled). Let ``needed`` be the set of
  triples supported by a modeled fact: an explicit ``FlowRequest`` whose
  protocol/port matches a named service, or a ``TrafficDemand`` / unmatched flow
  that implies an "any service" need (``*``) for that zone pair. Then
  ``excess = |{a in allowed : a is not covered by needed}|`` and

      S_least = 1 - min(1, excess / max(|needed|, 1))

  If no need is modeled, every allowed pair counts as excess. Need coverage is
  reported separately but does not affect the score, so adding a deny rule can
  never reduce it (the score is monotone non-decreasing as denies are added).

* ``S_trust`` -- lower-to-higher-trust transitive reachability. Fixed trust ranks
  are ``untrusted_external=0, guest=1, iot=2, user=3, other=3, dmz=4, server=5,
  management=6``. For every ordered pair of distinct zones ``(origin, reached)``
  where ``reached`` appears in the S1 bounded closure of ``origin`` and
  ``rank(reached) > rank(origin)``, add ``criticality(reached)/5`` to
  ``W_violation``. The exact criticality weighting is linear in the user-set
  criticality c in {1,2,3,4,5}: c/5 = 0.2, 0.4, 0.6, 0.8, 1.0. The normalizer is
  a policy-independent constant ``W_total = (n-1) * sum(c(z)/5 for all zones z)``
  for n zones (1.0 when n < 2). Then

      S_trust = 1 - min(1, W_violation / W_total)

  The fixed denominator is why denying a path can only improve this term.

* ``S_broadcast`` -- shared broadcast-domain size. For each VLAN id referenced by
  two or more zones, let ``f = (number of zones sharing that VLAN) / n``. Let
  ``max_shared = max(f)`` over such VLANs (0 when none are shared). Then

      S_broadcast = 1 - max_shared

  ``expected_hosts`` is used only by the existing oversized-subnet catalog rule;
  it is deliberately not a numeric term here because it is an optional modeled
  assumption, not a topology fact.

Criticality affects the score ONLY through ``S_trust`` via c/5 as shown above.
The criticality >= 4 exposure highlight from S1 is a separate finding, not a
score term. The score is an integer 0--100; subscore rounding to int happens
only after the weighted sum.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    BlastRadius,
    PolicyAction,
    ReachabilityMatrix,
    SegmentationInput,
    SegmentationScore,
    ZoneType,
)
from .policy import device_zone_map
from .reachability import build_blast_radii, build_reachability_matrix

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

    from .models import FlowRequest, SecurityModel

# Fixed, documented trust ordering. ``other`` deliberately shares rank with
# ``user``: an unclassified zone is not assumed to be a secure enclave.
TRUST_RANKS: dict[ZoneType, int] = {
    ZoneType.untrusted_external: 0,
    ZoneType.guest: 1,
    ZoneType.iot: 2,
    ZoneType.user: 3,
    ZoneType.other: 3,
    ZoneType.dmz: 4,
    ZoneType.server: 5,
    ZoneType.management: 6,
}

DEFAULT_WEIGHT = 0.25
LEAST_PRIVILEGE_WEIGHT = 0.30
TRUST_WEIGHT = 0.30
BROADCAST_WEIGHT = 0.15


def _needed_sets(
    twin: DigitalTwin,
    model: SecurityModel,
    flows: tuple[FlowRequest, ...],
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """Return exact ``(src, dst, service)`` needs and per-pair ``*`` needs."""
    mapping = device_zone_map(model)
    exact: set[tuple[str, str, str]] = set()
    wildcard: set[tuple[str, str, str]] = set()

    def add_pair(source_device: str, destination_device: str, service_name: str) -> None:
        source_zone = mapping.get(source_device)
        destination_zone = mapping.get(destination_device)
        if not source_zone or not destination_zone or source_zone == destination_zone:
            return
        key = (source_zone, destination_zone, service_name)
        if service_name == "*":
            wildcard.add(key)
        else:
            exact.add(key)

    for flow in flows:
        source_zone = mapping.get(flow.source_device_id)
        destination_zone = mapping.get(flow.destination_device_id)
        if not source_zone or not destination_zone or source_zone == destination_zone:
            continue
        matched = next(
            (
                service.name
                for service in model.services
                if service.matches(flow.protocol, flow.port)
            ),
            None,
        )
        if matched is None:
            wildcard.add((source_zone, destination_zone, "*"))
        else:
            exact.add((source_zone, destination_zone, matched))

    for demand in twin.demands:
        add_pair(demand.source, demand.destination, "*")

    return exact, wildcard


def _is_needed(
    triple: tuple[str, str, str],
    exact: set[tuple[str, str, str]],
    wildcard: set[tuple[str, str, str]],
) -> bool:
    source, destination, service = triple
    return (source, destination, service) in exact or (source, destination, "*") in wildcard


def _shared_vlan_fraction(model: SecurityModel) -> float:
    """Return the largest fraction of zones sharing one modeled VLAN id."""
    zone_count = len(model.zones)
    if zone_count < 2:
        return 0.0
    vlan_members: dict[int, set[str]] = {}
    for zone in model.zones:
        for vlan_id in zone.member_vlan_ids:
            vlan_members.setdefault(vlan_id, set()).add(zone.id)
    shared = [members for members in vlan_members.values() if len(members) >= 2]
    if not shared:
        return 0.0
    return max(len(members) for members in shared) / zone_count


def score_segmentation(
    twin: DigitalTwin,
    model: SecurityModel,
    *,
    flows: tuple[FlowRequest, ...] | list[FlowRequest] = (),
    matrix: ReachabilityMatrix | None = None,
    blast_radii: tuple[BlastRadius, ...] | None = None,
) -> SegmentationScore:
    """Return the hand-checkable 0--100 modeled segmentation score."""
    grid = matrix if matrix is not None else build_reachability_matrix(twin, model)
    radii = (
        blast_radii
        if blast_radii is not None
        else build_blast_radii(model, grid)
    )
    triples = tuple(
        (cell.source_zone, cell.destination_zone, cell.service)
        for cell in grid.cells
        if cell.reachable and cell.source_zone != cell.destination_zone
    )
    allowed = set(triples)
    exact_needs, wildcard_needs = _needed_sets(twin, model, tuple(flows))
    needed = exact_needs | wildcard_needs

    excess = {triple for triple in allowed if not _is_needed(triple, exact_needs, wildcard_needs)}
    covered = {triple for triple in allowed if _is_needed(triple, exact_needs, wildcard_needs)}

    s_default = 1.0 if model.default_action is PolicyAction.deny else 0.0
    s_least = 1.0 - min(1.0, len(excess) / max(len(needed), 1))
    need_coverage = 1.0 if not needed else len(covered) / len(needed)

    zones_by_id = {zone.id: zone for zone in model.zones}
    criticality_weight = {zone.id: zone.criticality / 5.0 for zone in model.zones}
    n = len(model.zones)
    total_weight = (n - 1) * sum(criticality_weight.values()) if n >= 2 else 0.0
    violation_weight = 0.0
    for radius in radii:
        origin = zones_by_id.get(radius.origin_zone)
        if origin is None:
            continue
        for reached_id in radius.closure_zones:
            reached = zones_by_id.get(reached_id)
            if reached is None:
                continue
            if TRUST_RANKS[reached.type] > TRUST_RANKS[origin.type]:
                violation_weight += criticality_weight[reached.id]
    s_trust = 1.0 if total_weight <= 0 else 1.0 - min(1.0, violation_weight / total_weight)

    max_shared = _shared_vlan_fraction(model)
    s_broadcast = 1.0 - max_shared

    contributions = (
        (s_default, DEFAULT_WEIGHT, "S_default"),
        (s_least, LEAST_PRIVILEGE_WEIGHT, "S_least"),
        (s_trust, TRUST_WEIGHT, "S_trust"),
        (s_broadcast, BROADCAST_WEIGHT, "S_broadcast"),
    )
    inputs = tuple(
        SegmentationInput(
            name=name,
            subscore=round(value, 6),
            weight=weight,
            contribution=round(value * weight, 6),
            detail=_detail(name, value, weight),
        )
        for value, weight, name in contributions
    )
    weighted = sum(value * weight for value, weight, _ in contributions)
    formula = (
        f"round(100 * ({DEFAULT_WEIGHT}*S_default + {LEAST_PRIVILEGE_WEIGHT}*S_least "
        f"+ {TRUST_WEIGHT}*S_trust + {BROADCAST_WEIGHT}*S_broadcast)); "
        f"allowed={len(allowed)}, needed={len(needed)}, excess={len(excess)}, "
        f"W_violation={round(violation_weight, 6)}, W_total={round(total_weight, 6)}, "
        f"max_shared_vlan={round(max_shared, 6)}"
    )
    return SegmentationScore(
        score=round(100 * weighted),
        formula=formula,
        inputs=inputs,
        allowed_count=len(allowed),
        needed_count=len(needed),
        excess_count=len(excess),
        need_coverage=round(need_coverage, 6),
        violation_weight=round(violation_weight, 6),
        total_weight=round(total_weight, 6),
        max_shared_vlan_fraction=round(max_shared, 6),
        trust_ranks={zone.id: TRUST_RANKS[zone.type] for zone in model.zones},
        zone_count=n,
    )


def _detail(name: str, value: float, weight: float) -> str:
    """Return a short readable derivation for one score input."""
    return f"{name}: subscore={value:.6f} x weight={weight:.2f} = {value * weight:.6f}"


__all__ = [
    "BROADCAST_WEIGHT",
    "DEFAULT_WEIGHT",
    "LEAST_PRIVILEGE_WEIGHT",
    "TRUST_RANKS",
    "TRUST_WEIGHT",
    "SegmentationInput",
    "SegmentationScore",
    "score_segmentation",
]
