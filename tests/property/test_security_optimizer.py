"""Bounded Hypothesis invariants for the S3 deterministic policy optimizer.

The property cross-checks the optimizer's finite decision table against the
independent first-match implementation in ``security.evaluate_policy``. It uses
only generated model data: no socket, process, filesystem, or network access.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from security import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
    apply_rule_changes,
    build_decision_table,
    build_optimization_plan,
    evaluate_policy,
    prove_equivalence,
)
from tests.property.config import BOUNDED
from tests.unit.digital_twin.helpers import make_twin

_PROTOCOLS = (Protocol.tcp, Protocol.udp, Protocol.icmp, Protocol.any)
_ZONE_PAIRS = (("z-a", "z-b"), ("z-b", "z-a"))


@st.composite
def _models(draw):
    zones = (
        Zone(id="z-a", name="A", type=ZoneType.user, criticality=3, member_vlan_ids=(10,)),
        Zone(id="z-b", name="B", type=ZoneType.server, criticality=4, member_vlan_ids=(20,)),
    )
    services = tuple(
        Service(
            name=f"svc-{index}",
            protocol=Protocol.tcp,
            port_start=start,
            port_end=start + draw(st.integers(0, 3)),
        )
        for index, start in enumerate(draw(st.lists(st.integers(0, 20), max_size=2)))
    )
    names = tuple(service.name for service in services)
    rule_count = draw(st.integers(0, 4))
    rules = []
    for index in range(rule_count):
        source, destination = draw(st.sampled_from(_ZONE_PAIRS))
        any_service = draw(st.booleans()) if names else True
        rules.append(
            FirewallRule(
                id=f"r-{index}",
                order=index,
                src_zone=source,
                dst_zone=destination,
                services=() if any_service else (draw(st.sampled_from(names)),),
                any_service=any_service,
                action=draw(st.sampled_from(tuple(PolicyAction))),
                enabled=draw(st.booleans()),
            )
        )
    return SecurityModel(
        zones=zones,
        services=services,
        rules=tuple(rules),
        default_action=draw(st.sampled_from(tuple(PolicyAction))),
    )


def _independent_equivalent(baseline: SecurityModel, candidate: SecurityModel) -> bool:
    """Recompute equivalence through ``evaluate_policy``, not the table builder."""
    if baseline.default_action != candidate.default_action:
        return False
    pairs = set()
    for model in (baseline, candidate):
        for rule in model.rules:
            if rule.src_zone != rule.dst_zone:
                pairs.add((rule.src_zone, rule.dst_zone))
    ports = {0, 65_535}
    for model in (baseline, candidate):
        for service in model.services:
            ports.update((service.port_start, service.port_end))
    for source, destination in pairs:
        for protocol in _PROTOCOLS:
            for port in sorted(ports):
                if evaluate_policy(baseline, source, destination, protocol, port).action != (
                    evaluate_policy(candidate, source, destination, protocol, port).action
                ):
                    return False
    return True


@BOUNDED
@given(model=_models())
def test_decision_table_agrees_with_first_match_policy(model: SecurityModel) -> None:
    pairs = {("z-a", "z-b"), ("z-b", "z-a")}
    table = build_decision_table(model, pairs)
    ports = {0, 65_535}
    for service in model.services:
        ports.update((service.port_start, service.port_end))

    for (source, destination, protocol, port), action in table.items():
        expected = evaluate_policy(model, source, destination, protocol, port).action
        assert action is expected


@BOUNDED
@given(model=_models())
def test_every_proposals_flag_matches_independent_proof(model: SecurityModel) -> None:
    plan = build_optimization_plan(make_twin(demands=()), model)

    for proposal in plan.proposals:
        candidate = apply_rule_changes(model, proposal.changes)
        assert proposal.behavior_preserving == _independent_equivalent(model, candidate)
        assert proposal.proof.equivalent == proposal.behavior_preserving
        assert prove_equivalence(model, candidate) == proposal.proof
