"""Proposed policy changes and explicit acceptance into a NEW twin.

Proposals are always inert. They are applied only through
:func:`accept_proposed_rules` with an explicit list of rule ids chosen by the
user, and even then the baseline twin is left untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.exceptions import SchemaError

from .models import (
    FirewallRule,
    PolicyAction,
    ProposalSet,
    ProposedRule,
    SecurityFinding,
)
from .operations import add_rule, ensure_security_model, get_security_model

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin


def build_proposals(findings: tuple[SecurityFinding, ...]) -> ProposalSet:
    """Build deterministic deny-rule proposals from actionable findings."""
    rules: list[ProposedRule] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        if not finding.proposal_src_zone or not finding.proposal_dst_zone:
            continue
        key = (finding.code, finding.proposal_src_zone, finding.proposal_dst_zone)
        if key in seen:
            continue
        seen.add(key)
        rules.append(
            ProposedRule(
                id=(
                    f"proposal-{finding.code.lower()}-"
                    f"{finding.proposal_src_zone}-{finding.proposal_dst_zone}"
                )[:64],
                src_zone=finding.proposal_src_zone,
                dst_zone=finding.proposal_dst_zone,
                any_service=True,
                action=PolicyAction.deny,
                reason=finding.explanation,
                based_on_finding=finding.code,
            )
        )
    return ProposalSet(rules=tuple(rules))


def accept_proposed_rules(
    twin: DigitalTwin,
    proposals: ProposalSet,
    accepted_rule_ids: tuple[str, ...] | list[str],
) -> tuple[DigitalTwin, tuple[str, ...]]:
    """Apply only accepted proposals to a NEW twin and return applied ids.

    The accepted ids are validated before any edit. Rules are added in proposal
    order with sequential orders after the current last rule, so the result is
    independent of the caller's id order.
    """
    requested = set(accepted_rule_ids)
    available = {rule.id for rule in proposals.rules}
    unknown = sorted(requested - available)
    if unknown:
        raise SchemaError(f"Unknown proposed rule ids: {', '.join(unknown)}")

    current = ensure_security_model(twin)
    if not requested:
        return current, ()

    model = get_security_model(current)
    next_order = max((rule.order for rule in model.rules), default=-1) + 1
    applied: list[str] = []
    for proposal in proposals.rules:
        if proposal.id not in requested:
            continue
        rule = FirewallRule(
            id=proposal.id,
            order=next_order,
            src_zone=proposal.src_zone,
            dst_zone=proposal.dst_zone,
            services=proposal.services,
            any_service=proposal.any_service,
            action=proposal.action,
            note=proposal.reason[:500],
        )
        current = add_rule(current, rule)
        applied.append(rule.id)
        next_order += 1
    return current, tuple(applied)


__all__ = ["accept_proposed_rules", "build_proposals"]
