"""S4: inert, demand-scoped zero-trust microsegmentation suggestions.

The only facts used here are the modeled zones, named services, modeled flows,
and demands in the twin. For each high-criticality zone (designer-set
criticality >= 4), the module suggests adding narrow *allow* rules whose zone
pair and named services are a strict subset of demand-implied needs, plus
explicit *deny* rules from lower-trust zones that have no modeled need toward
that zone. If the baseline default is allow, an explicit default deny is also
requested.

Nothing is applied automatically. Each proposal records the before/after
segmentation score and bounded blast-radius summary computed from the same
deterministic S1/S2 engines, and selection applies all chosen suggestions to a
NEW twin through :func:`security.set_security_model`. Rules are inert design
records: no device command, configuration, or network traffic is produced.

This is a design-level suggestion aligned with common practice. It is not a
compliance certification, vulnerability scan, penetration test, or attack-path
model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.limits import (
    MAX_FIREWALL_RULES,
    MAX_MICROSEGMENTATION_PROPOSALS,
    MAX_MICROSEGMENTATION_RULES,
)
from core.exceptions import SchemaError

from .models import (
    MICROSEGMENTATION_NOTE,
    FirewallRule,
    MicrosegmentationPlan,
    MicrosegmentationProposal,
    PolicyAction,
    RuleAddition,
    SecurityModel,
    ZoneType,
)
from .operations import set_security_model
from .reachability import build_blast_radii, build_reachability_matrix
from .segmentation import needed_pairs, score_segmentation

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

    from .models import FlowRequest

_HIGH_CRITICALITY = 4
_LOWER_TRUST = frozenset(
    {ZoneType.untrusted_external, ZoneType.guest, ZoneType.iot}
)


def _candidate_model(
    model: SecurityModel,
    additions: tuple[RuleAddition, ...],
    default_deny: bool,
) -> SecurityModel:
    """Return a new model with inert additions placed before existing rules.

    New rules receive the first ``len(additions)`` order values. Existing rules
    keep their relative order and content, shifted up by that count. This is a
    mechanical renumbering in a new model, not an edit of the baseline twin.
    """
    existing_ids = {rule.id for rule in model.rules}
    new_rules: list[FirewallRule] = []
    used_ids: set[str] = set(existing_ids)
    for index, addition in enumerate(additions):
        rule = addition.rule
        candidate_id = rule.id
        suffix = 2
        while candidate_id in used_ids:
            candidate_id = f"{rule.id}-{suffix}"[:64]
            suffix += 1
        used_ids.add(candidate_id)
        new_rules.append(rule.model_copy(update={"id": candidate_id, "order": index}))
    shifted = tuple(
        rule.model_copy(update={"order": rule.order + len(new_rules)})
        for rule in model.rules
    )
    return SecurityModel(
        zones=model.zones,
        services=model.services,
        rules=tuple(new_rules) + shifted,
        default_action=PolicyAction.deny if default_deny else model.default_action,
        assumptions=model.assumptions,
    )


def _metrics(
    twin: DigitalTwin,
    model: SecurityModel,
    flows: tuple[FlowRequest, ...],
) -> tuple[int, int, int]:
    """Return ``(score, reachable_pair_count, max_criticality_reached)``."""
    matrix = build_reachability_matrix(twin, model)
    radii = build_blast_radii(model, matrix)
    score = score_segmentation(twin, model, flows=flows, matrix=matrix, blast_radii=radii)
    reachable = sum(
        1 for cell in matrix.cells if cell.reachable and cell.source_zone != cell.destination_zone
    )
    max_criticality = max((item.max_criticality_reached for item in radii), default=0)
    return score.score, reachable, max_criticality


def build_microsegmentation_plan(
    twin: DigitalTwin,
    model: SecurityModel,
    *,
    flows: tuple[FlowRequest, ...] | list[FlowRequest] = (),
) -> MicrosegmentationPlan:
    """Build inert per-zone microsegmentation suggestions for high-criticality zones."""
    modeled_flows = tuple(flows)
    needs = needed_pairs(twin, model, modeled_flows)
    baseline_score, baseline_reachable, baseline_criticality = _metrics(
        twin, model, modeled_flows
    )
    default_deny = model.default_action is PolicyAction.allow
    capacity = max(0, MAX_FIREWALL_RULES - len(model.rules))
    rule_cap = min(MAX_MICROSEGMENTATION_RULES, capacity)

    high_zones = sorted(
        (zone for zone in model.zones if zone.criticality >= _HIGH_CRITICALITY),
        key=lambda zone: (-zone.criticality, zone.id),
    )[:MAX_MICROSEGMENTATION_PROPOSALS]

    proposals: list[MicrosegmentationProposal] = []
    zone_types = {zone.id: zone.type for zone in model.zones}
    for zone in high_zones:
        additions: list[RuleAddition] = []
        allow_pairs: list[str] = []
        for (source, destination), services in sorted(needs.items()):
            if source == destination or zone.id not in {source, destination}:
                continue
            names = tuple(sorted(services))
            if not names:
                continue
            additions.append(
                RuleAddition(
                    rule=FirewallRule(
                        id=f"micro-allow-{source}-{destination}"[:64],
                        order=0,
                        src_zone=source,
                        dst_zone=destination,
                        services=names,
                        any_service=False,
                        action=PolicyAction.allow,
                        note="Demand-implied need; design-time microsegmentation rule.",
                    ),
                    reason=(
                        f"Modeled need from {source!r} to {destination!r} names only "
                        + ", ".join(names)
                        + "."
                    ),
                )
            )
            allow_pairs.append(f"{source}->{destination}:{','.join(names)}")
            if len(additions) >= rule_cap:
                break
        if len(additions) < rule_cap:
            for source, zone_type in sorted(zone_types.items()):
                if zone_type not in _LOWER_TRUST or source == zone.id:
                    continue
                if (source, zone.id) in needs:
                    continue
                additions.append(
                    RuleAddition(
                        rule=FirewallRule(
                            id=f"micro-deny-{source}-{zone.id}"[:64],
                            order=0,
                            src_zone=source,
                            dst_zone=zone.id,
                            any_service=True,
                            action=PolicyAction.deny,
                            note="No modeled need; design-time microsegmentation rule.",
                        ),
                        reason=(
                            f"No modeled need from lower-trust zone {source!r} to "
                            f"criticality-{zone.criticality} zone {zone.id!r}."
                        ),
                    )
                )
                if len(additions) >= rule_cap:
                    break
        if not additions:
            continue

        candidate = _candidate_model(model, tuple(additions), default_deny)
        after_score, after_reachable, after_criticality = _metrics(
            twin, candidate, modeled_flows
        )
        proposals.append(
            MicrosegmentationProposal(
                id=f"micro-{zone.id}"[:64],
                zone_id=zone.id,
                title=f"Microsegment {zone.id}",
                explanation=(
                    f"Zone {zone.id!r} has designer-set criticality "
                    f"{zone.criticality}. The inert additions allow only "
                    "demand-implied pairs and explicitly deny lower-trust pairs "
                    "with no modeled need. This is a modeled design-level "
                    "suggestion aligned with common practice, not a compliance "
                    "claim or a device configuration."
                ),
                new_rules=tuple(additions),
                allow_pairs=tuple(allow_pairs),
                default_deny_requested=default_deny,
                before_score=baseline_score,
                after_score=after_score,
                before_reachable_count=baseline_reachable,
                after_reachable_count=after_reachable,
                before_max_criticality_reached=baseline_criticality,
                after_max_criticality_reached=after_criticality,
            )
        )

    return MicrosegmentationPlan(
        model=model,
        flows_modeled=len(modeled_flows),
        proposals=tuple(proposals),
    )


@dataclass(frozen=True)
class MicrosegmentationDecision:
    """Typed C4 decision draft emitted after explicit microsegmentation apply."""

    kind: str
    subject_id: str
    title: str
    page: str
    source_fingerprint: str
    result_fingerprint: str
    details: tuple[tuple[str, str], ...]


def accept_microsegmentation_proposals(
    twin: DigitalTwin,
    plan: MicrosegmentationPlan,
    selected_ids: tuple[str, ...] | list[str],
    *,
    fingerprint: Callable[[DigitalTwin], str] | None = None,
    on_decision: Callable[[MicrosegmentationDecision], None] | None = None,
) -> tuple[DigitalTwin, tuple[str, ...]]:
    """Apply selected inert suggestions to a NEW twin only."""
    requested = set(selected_ids)
    available = {proposal.id for proposal in plan.proposals}
    unknown = sorted(requested - available)
    if unknown:
        raise SchemaError(f"Unknown microsegmentation proposal ids: {', '.join(unknown)}")

    selected = tuple(
        proposal for proposal in plan.proposals if proposal.id in requested
    )
    additions: dict[str, RuleAddition] = {}
    for proposal in selected:
        for addition in proposal.new_rules:
            additions.setdefault(addition.rule.id, addition)

    default_deny = any(item.default_deny_requested for item in selected)
    candidate = _candidate_model(plan.model, tuple(additions.values()), default_deny)
    updated = set_security_model(twin, candidate)

    if on_decision is not None:
        on_decision(
            MicrosegmentationDecision(
                kind="security_proposal_accepted",
                subject_id=", ".join(proposal.id for proposal in selected)[:200],
                title=f"Accepted {len(selected)} microsegmentation suggestion(s)",
                page="Security Analysis",
                source_fingerprint=fingerprint(twin) if fingerprint else "",
                result_fingerprint=fingerprint(updated) if fingerprint else "",
                details=(
                    ("proposals", str(len(selected))),
                    ("added_rules", str(len(additions))),
                    ("default_deny", str(default_deny).lower()),
                ),
            )
        )
    return updated, tuple(proposal.id for proposal in selected)


__all__ = [
    "MICROSEGMENTATION_NOTE",
    "MicrosegmentationDecision",
    "accept_microsegmentation_proposals",
    "build_microsegmentation_plan",
]
