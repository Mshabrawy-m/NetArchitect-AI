"""S3: deterministic, inert policy optimization with an equivalence proof.

Every proposal is computed from the modeled policy alone. The optimizer never
rewrites the current twin: proposals are inert records and are applied only by
:func:`accept_optimization_proposals`, which builds a NEW twin after an explicit
selection and optionally reports one C4 decision through an injected callback.
No language model, device access, or network I/O is involved.

Equivalence proof. Policy evaluation is first-match over ordered rules, and a
rule's service match is a union of inclusive port intervals for a fixed
protocol. The decision is therefore constant between interval breakpoints. The
proof enumerates a finite, complete probe domain per affected zone pair: every
modeled transport category plus ``any``, and ports 0, 65535, and both ends of
every named tcp/udp service range. One further check covers the global default.
Two policies are equivalent only when every probe yields the same action.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.limits import MAX_OPTIMIZATION_PROPOSALS
from core.exceptions import SchemaError

from .models import (
    POLICY_OPTIMIZER_NOTE,
    DecisionProof,
    FirewallRule,
    OptimizationKind,
    OptimizationPlan,
    OptimizationProposal,
    PolicyAction,
    Protocol,
    RuleChange,
    SecurityModel,
)
from .operations import set_security_model
from .segmentation import needed_pairs

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

    from .models import FlowRequest

_PROBE_PROTOCOLS = (Protocol.tcp, Protocol.udp, Protocol.icmp, Protocol.any)
_PROOF_METHOD = (
    "Complete finite decision table: affected zone pairs x {tcp,udp,icmp,any} "
    "x {0, 65535, each named tcp/udp service port_start and port_end}, plus the "
    "global default action. Actions are constant between these breakpoints."
)


def _probe_ports(model: SecurityModel) -> tuple[int, ...]:
    ports = {0, 65535}
    for service in model.services:
        if service.protocol in {Protocol.tcp, Protocol.udp}:
            ports.add(service.port_start)
            ports.add(service.port_end)
    return tuple(sorted(ports))


def _affected_pairs(*models: SecurityModel) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for model in models:
        for rule in model.rules:
            if rule.src_zone != rule.dst_zone:
                pairs.add((rule.src_zone, rule.dst_zone))
    return pairs


def build_decision_table(
    model: SecurityModel,
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str, Protocol, int], PolicyAction]:
    """Return the modeled first-match action for every finite probe in ``pairs``."""
    ports = _probe_ports(model)
    table: dict[tuple[str, str, Protocol, int], PolicyAction] = {
        (source, destination, protocol, port): model.default_action
        for source, destination in pairs
        for protocol in _PROBE_PROTOCOLS
        for port in ports
    }
    services = {service.name: service for service in model.services}
    rules = tuple(rule for rule in model.ordered_rules if rule.enabled)
    for key in sorted(table):
        source, destination, protocol, port = key
        for rule in rules:
            if rule.src_zone != source or rule.dst_zone != destination:
                continue
            if rule.any_service or any(
                (service := services.get(name)) is not None
                and service.matches(protocol, port)
                for name in rule.services
            ):
                table[key] = rule.action
                break
    return table


def prove_equivalence(baseline: SecurityModel, candidate: SecurityModel) -> DecisionProof:
    """Compare two policies over the full finite decision table."""
    pairs = _affected_pairs(baseline, candidate)
    old_table = build_decision_table(baseline, pairs)
    new_table = build_decision_table(candidate, pairs)
    differing: list[str] = []
    for key in sorted(old_table):
        if old_table[key] != new_table[key]:
            source, destination, protocol, port = key
            differing.append(
                f"{source}->{destination} {protocol.value}:{port} "
                f"{old_table[key].value}!={new_table[key].value}"
            )
            if len(differing) >= 8:
                break
    default_differs = baseline.default_action != candidate.default_action
    cases_checked = len(old_table) + (1 if default_differs else 0)
    if default_differs:
        differing.append(
            f"default_action {baseline.default_action.value}!"
            f"={candidate.default_action.value}"
        )
    return DecisionProof(
        cases_checked=cases_checked,
        differing_cases=tuple(differing[:8]),
        equivalent=not differing,
        method=_PROOF_METHOD,
    )


def apply_rule_changes(model: SecurityModel, changes: tuple[RuleChange, ...]) -> SecurityModel:
    """Apply inert rule changes to a new model without mutating the input."""
    rules = list(model.rules)
    default_action = model.default_action
    for change in changes:
        if change.op == "remove":
            rules = [rule for rule in rules if rule.id != change.target_rule_id]
        elif change.op == "replace" and change.new_rule is not None:
            rules = [
                change.new_rule if rule.id == change.target_rule_id else rule
                for rule in rules
            ]
        elif change.op == "set_default" and change.new_default_action is not None:
            default_action = change.new_default_action
    orders = [rule.order for rule in rules]
    if len(orders) != len(set(orders)):
        raise SchemaError("Optimizer changes would create duplicate rule orders")
    return SecurityModel(
        zones=model.zones,
        services=model.services,
        rules=tuple(rules),
        default_action=default_action,
        assumptions=model.assumptions,
    )


def _service_signature(rule: FirewallRule) -> frozenset[str] | None:
    """Return a comparable service signature; ``None`` means any service."""
    return None if rule.any_service else frozenset(rule.services)


def _covers(earlier: FirewallRule, later: FirewallRule) -> bool:
    """Return whether ``earlier`` matches every service that ``later`` matches."""
    earlier_services = _service_signature(earlier)
    if earlier_services is None:
        return True
    later_services = _service_signature(later)
    return later_services is not None and later_services <= earlier_services


def _make_proposal(
    kind: OptimizationKind,
    identifier: str,
    title: str,
    explanation: str,
    changes: tuple[RuleChange, ...],
    affected: tuple[str, ...],
    baseline: SecurityModel,
) -> OptimizationProposal:
    candidate = apply_rule_changes(baseline, changes)
    proof = prove_equivalence(baseline, candidate)
    return OptimizationProposal(
        id=identifier[:64],
        kind=kind,
        title=title,
        explanation=explanation,
        affected_rule_ids=affected,
        behavior_preserving=proof.equivalent,
        proof=proof,
        changes=changes,
    )


def build_optimization_plan(
    twin: DigitalTwin,
    model: SecurityModel,
    *,
    flows: tuple[FlowRequest, ...] | list[FlowRequest] = (),
) -> OptimizationPlan:
    """Build all deterministic inert proposals for one modeled policy."""
    ordered = tuple(rule for rule in model.ordered_rules if rule.enabled)
    proposals: list[OptimizationProposal] = []
    seen_merge: set[str] = set()
    seen_remove: set[str] = set()

    for index in range(len(ordered) - 1):
        first, second = ordered[index], ordered[index + 1]
        if (
            first.src_zone == second.src_zone
            and first.dst_zone == second.dst_zone
            and first.action == second.action
            and _service_signature(first) == _service_signature(second)
        ):
            proposals.append(
                _make_proposal(
                    OptimizationKind.merge_duplicates,
                    f"merge-{first.id}-{second.id}",
                    "Merge adjacent duplicate rule",
                    (
                        f"Rules {first.id!r} and {second.id!r} are adjacent and "
                        "identical for zones, services, and action."
                    ),
                    (RuleChange(op="remove", target_rule_id=second.id),),
                    (first.id, second.id),
                    model,
                )
            )
            seen_merge.add(second.id)

    for index, rule in enumerate(ordered):
        if rule.id in seen_merge:
            continue
        for earlier in ordered[:index]:
            if (
                earlier.src_zone == rule.src_zone
                and earlier.dst_zone == rule.dst_zone
                and earlier.action == rule.action
                and _covers(earlier, rule)
            ):
                proposals.append(
                    _make_proposal(
                        OptimizationKind.remove_shadowed,
                        f"shadow-{rule.id}",
                        "Remove shadowed rule",
                        (
                            f"Rule {rule.id!r} is fully covered by earlier rule "
                            f"{earlier.id!r} with the same action."
                        ),
                        (RuleChange(op="remove", target_rule_id=rule.id),),
                        (earlier.id, rule.id),
                        model,
                    )
                )
                seen_remove.add(rule.id)
                break

    for index, rule in enumerate(ordered):
        if rule.id in seen_merge or rule.id in seen_remove:
            continue
        for later in ordered[index + 1 :]:
            if (
                later.src_zone == rule.src_zone
                and later.dst_zone == rule.dst_zone
                and later.action == rule.action
                and _covers(later, rule)
            ):
                proposals.append(
                    _make_proposal(
                        OptimizationKind.remove_redundant,
                        f"redundant-{rule.id}",
                        "Remove redundant rule",
                        (
                            f"Rule {rule.id!r} is fully covered by later rule "
                            f"{later.id!r} with the same action."
                        ),
                        (RuleChange(op="remove", target_rule_id=rule.id),),
                        (rule.id, later.id),
                        model,
                    )
                )
                break

    grouped: dict[tuple[str, str], list[FirewallRule]] = {}
    for rule in ordered:
        grouped.setdefault((rule.src_zone, rule.dst_zone), []).append(rule)
    for (source, destination), pair_rules in grouped.items():
        for index, broad in enumerate(pair_rules):
            if not broad.any_service:
                continue
            specific = next(
                (
                    item
                    for item in pair_rules[index + 1 :]
                    if not item.any_service and item.action == broad.action
                ),
                None,
            )
            if specific is None:
                continue
            proposals.append(
                _make_proposal(
                    OptimizationKind.reorder_specifics,
                    f"reorder-{broad.id}-{specific.id}",
                    "List specific rule before any-service rule",
                    (
                        f"For {source}->{destination}, rule {specific.id!r} is "
                        f"narrower than {broad.id!r} and shares its action."
                    ),
                    (
                        RuleChange(
                            op="replace",
                            target_rule_id=broad.id,
                            new_rule=broad.model_copy(update={"order": specific.order}),
                        ),
                        RuleChange(
                            op="replace",
                            target_rule_id=specific.id,
                            new_rule=specific.model_copy(update={"order": broad.order}),
                        ),
                    ),
                    (broad.id, specific.id),
                    model,
                )
            )

    needs = needed_pairs(twin, model, flows)
    for rule in ordered:
        if not rule.any_service or rule.action is not PolicyAction.allow:
            continue
        names = tuple(sorted(needs.get((rule.src_zone, rule.dst_zone), set())))
        if not names:
            names = tuple(sorted(service.name for service in model.services))
        if not names:
            continue
        proposals.append(
            _make_proposal(
                OptimizationKind.tighten_any,
                f"tighten-{rule.id}",
                "Tighten any-service allow to named services",
                (
                    f"Rule {rule.id!r} currently allows any service; the modeled "
                    "needs support naming only: " + ", ".join(names) + "."
                ),
                (
                    RuleChange(
                        op="replace",
                        target_rule_id=rule.id,
                        new_rule=rule.model_copy(
                            update={"any_service": False, "services": names}
                        ),
                    ),
                ),
                (rule.id,),
                model,
            )
        )

    if model.default_action is PolicyAction.allow:
        proposals.append(
            _make_proposal(
                OptimizationKind.explicit_default_deny,
                "explicit-default-deny",
                "Set explicit default deny",
                "The modeled policy currently falls back to allow for unmatched pairs.",
                (RuleChange(op="set_default", new_default_action=PolicyAction.deny),),
                ("default_action",),
                model,
            )
        )

    all_probes = _affected_pairs(model)
    return OptimizationPlan(
        model=model,
        baseline_default_action=model.default_action,
        cases_checked=len(all_probes) * len(_PROBE_PROTOCOLS) * len(_probe_ports(model)),
        proposals=tuple(proposals[:MAX_OPTIMIZATION_PROPOSALS]),
    )


@dataclass(frozen=True)
class OptimizationDecision:
    """Typed C4 decision draft emitted after an explicit optimizer apply."""

    kind: str
    subject_id: str
    title: str
    page: str
    source_fingerprint: str
    result_fingerprint: str
    details: tuple[tuple[str, str], ...]


def accept_optimization_proposals(
    twin: DigitalTwin,
    plan: OptimizationPlan,
    selected_ids: tuple[str, ...] | list[str],
    *,
    fingerprint: Callable[[DigitalTwin], str] | None = None,
    on_decision: Callable[[OptimizationDecision], None] | None = None,
) -> tuple[DigitalTwin, tuple[str, ...]]:
    """Apply selected inert proposals to a NEW twin and report one C4 decision."""
    requested = set(selected_ids)
    available = {proposal.id for proposal in plan.proposals}
    unknown = sorted(requested - available)
    if unknown:
        raise SchemaError(f"Unknown optimization proposal ids: {', '.join(unknown)}")

    selected = tuple(
        proposal for proposal in plan.proposals if proposal.id in requested
    )
    model = plan.model
    for proposal in selected:
        model = apply_rule_changes(model, proposal.changes)
    proof = prove_equivalence(plan.model, model)
    updated = set_security_model(twin, model)

    if on_decision is not None:
        on_decision(
            OptimizationDecision(
                kind="optimization_candidate_selected",
                subject_id=", ".join(proposal.id for proposal in selected)[:200],
                title=f"Accepted {len(selected)} modeled policy optimization(s)",
                page="Security Analysis",
                source_fingerprint=fingerprint(twin) if fingerprint else "",
                result_fingerprint=fingerprint(updated) if fingerprint else "",
                details=(
                    ("proposals", str(len(selected))),
                    ("behavior_preserving", str(proof.equivalent)),
                    ("cases_checked", str(proof.cases_checked)),
                ),
            )
        )
    return updated, tuple(proposal.id for proposal in selected)


__all__ = [
    "POLICY_OPTIMIZER_NOTE",
    "OptimizationDecision",
    "accept_optimization_proposals",
    "apply_rule_changes",
    "build_decision_table",
    "build_optimization_plan",
    "prove_equivalence",
]
