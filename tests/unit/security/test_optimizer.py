"""S3: deterministic, inert policy optimizer tests."""

from __future__ import annotations

import pytest

from core.exceptions import SchemaError
from security import (
    POLICY_OPTIMIZER_NOTE,
    SECURITY_DISCLAIMER,
    FlowRequest,
    OptimizationKind,
    OptimizationPlan,
    PolicyAction,
    Protocol,
    RuleChange,
    SecurityAnalysis,
    SecurityModel,
    accept_optimization_proposals,
    analyze_design,
    apply_rule_changes,
    build_optimization_plan,
    prove_equivalence,
    set_security_model,
)
from tests.unit.digital_twin.helpers import make_twin

from .helpers import make_rule, make_service, make_zone
from .test_reachability import _chain_twin, _four_zone_model


def _model(*rules, default: PolicyAction = PolicyAction.deny) -> SecurityModel:
    return SecurityModel(
        zones=(
            make_zone("z-ext", zone_type="untrusted_external", vlan_id=10),
            make_zone("z-user", vlan_id=20),
            make_zone("z-server", zone_type="server", criticality=4, vlan_id=30),
        ),
        services=(
            make_service("http", port_start=80, port_end=80),
            make_service("https", port_start=443, port_end=443),
        ),
        rules=rules,
        default_action=default,
    )


def _plan(model: SecurityModel, *, twin=None, flows=()) -> OptimizationPlan:
    return build_optimization_plan(twin or make_twin(demands=()), model, flows=flows)


def _by_kind(plan: OptimizationPlan, kind: OptimizationKind):
    return tuple(item for item in plan.proposals if item.kind is kind)


def test_merge_adjacent_duplicates_is_behavior_preserving() -> None:
    model = _model(
        make_rule("r1", order=0, src_zone="z-ext", dst_zone="z-server"),
        make_rule("r2", order=1, src_zone="z-ext", dst_zone="z-server"),
    )

    plan = _plan(model)
    proposals = _by_kind(plan, OptimizationKind.merge_duplicates)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.behavior_preserving is True
    assert proposal.proof.equivalent is True
    assert proposal.proof.cases_checked > 0
    assert proposal.proof.differing_cases == ()
    assert proposal.affected_rule_ids == ("r1", "r2")
    assert proposal.disclaimer == SECURITY_DISCLAIMER
    assert plan.note == POLICY_OPTIMIZER_NOTE
    assert plan.disclaimer == SECURITY_DISCLAIMER


def test_remove_shadowed_and_redundant_rules() -> None:
    model = _model(
        make_rule("any-allow", order=0, src_zone="z-ext", dst_zone="z-server", any_service=True, services=()),
        make_rule("http-allow", order=1, src_zone="z-ext", dst_zone="z-server"),
        make_rule("http-allow-2", order=2, src_zone="z-ext", dst_zone="z-user"),
        make_rule("any-allow-user", order=3, src_zone="z-ext", dst_zone="z-user", any_service=True, services=()),
    )

    plan = _plan(model)
    shadowed = _by_kind(plan, OptimizationKind.remove_shadowed)
    redundant = _by_kind(plan, OptimizationKind.remove_redundant)

    assert {item.affected_rule_ids[1] for item in shadowed} == {"http-allow"}
    assert all(item.behavior_preserving for item in shadowed)
    assert {item.affected_rule_ids[0] for item in redundant} == {"http-allow-2"}
    assert all(item.behavior_preserving for item in redundant)


def test_reorder_specifics_before_any_is_proven() -> None:
    model = _model(
        make_rule("any-allow", order=0, src_zone="z-ext", dst_zone="z-server", any_service=True, services=()),
        make_rule("http-allow", order=1, src_zone="z-ext", dst_zone="z-server"),
    )

    proposals = _by_kind(_plan(model), OptimizationKind.reorder_specifics)

    assert len(proposals) == 1
    assert proposals[0].behavior_preserving is True
    candidate = apply_rule_changes(model, proposals[0].changes)
    assert {rule.id: rule.order for rule in candidate.rules} == {
        "any-allow": 1,
        "http-allow": 0,
    }


def test_tighten_any_is_flagged_as_behavior_changing() -> None:
    twin = _chain_twin()
    model = _four_zone_model().model_copy(
        update={
            "rules": (
                make_rule(
                    "any-allow",
                    order=0,
                    src_zone="z-ext",
                    dst_zone="z-guest",
                    any_service=True,
                    services=(),
                ),
            )
        }
    )
    flows = (
        FlowRequest(
            id="f1",
            source_device_id="d-ext",
            destination_device_id="d-guest",
            protocol=Protocol.tcp,
            port=80,
        ),
    )

    proposals = _by_kind(_plan(model, twin=twin, flows=flows), OptimizationKind.tighten_any)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.behavior_preserving is False
    assert proposal.proof.differing_cases
    assert "any service" in proposal.explanation
    assert "naming only: http" in proposal.explanation
    assert proposal.changes[0].new_rule is not None
    assert proposal.changes[0].new_rule.services == ("http",)


def test_explicit_default_deny_is_flagged() -> None:
    model = _model(default=PolicyAction.allow)

    proposals = _by_kind(_plan(model), OptimizationKind.explicit_default_deny)

    assert len(proposals) == 1
    assert proposals[0].behavior_preserving is False
    assert any("default_action" in item for item in proposals[0].proof.differing_cases)
    assert proposals[0].changes == (
        RuleChange(op="set_default", new_default_action=PolicyAction.deny),
    )


def test_decision_table_matches_evaluate_policy() -> None:
    from security import build_decision_table, evaluate_policy

    model = _model(
        make_rule("any-allow", order=0, src_zone="z-ext", dst_zone="z-server", any_service=True, services=()),
        make_rule("https-deny", order=1, src_zone="z-ext", dst_zone="z-server", services=("https",),
                  action=PolicyAction.deny),
    )
    pairs = {("z-ext", "z-server")}
    table = build_decision_table(model, pairs)

    for protocol in (Protocol.tcp, Protocol.udp, Protocol.icmp, Protocol.any):
        for port in (0, 80, 443, 65_535):
            expected = evaluate_policy(model, "z-ext", "z-server", protocol, port).action
            assert table[("z-ext", "z-server", protocol, port)] is expected


def test_proof_detects_non_equivalence() -> None:
    baseline = _model(default=PolicyAction.deny)
    changed = apply_rule_changes(
        baseline, (RuleChange(op="set_default", new_default_action=PolicyAction.allow),)
    )

    proof = prove_equivalence(baseline, changed)

    assert proof.equivalent is False
    assert proof.cases_checked >= 1
    assert "default_action" in proof.differing_cases[-1]
    assert "decision table" in proof.method.lower()


def test_apply_creates_new_twin_and_logs_c4_decision() -> None:
    twin = set_security_model(
        _chain_twin(),
        _model(
            make_rule("r1", order=0, src_zone="z-ext", dst_zone="z-server"),
            make_rule("r2", order=1, src_zone="z-ext", dst_zone="z-server"),
        ),
    )
    model = twin.security
    plan = _plan(model, twin=twin)
    proposal = _by_kind(plan, OptimizationKind.merge_duplicates)[0]
    decisions = []

    updated, applied = accept_optimization_proposals(
        twin,
        plan,
        (proposal.id,),
        fingerprint=lambda item: f"fp-{len(item.topology.devices)}",
        on_decision=decisions.append,
    )

    assert applied == (proposal.id,)
    assert updated is not twin
    assert len(updated.security.rules) == 1
    assert len(twin.security.rules) == 2  # baseline untouched
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.kind == "optimization_candidate_selected"
    assert decision.page == "Security Analysis"
    assert decision.source_fingerprint == "fp-4"
    assert decision.result_fingerprint == "fp-4"
    assert dict(decision.details)["behavior_preserving"] == "True"


def test_apply_rejects_unknown_ids_and_truncates_subject() -> None:
    twin, model = _chain_twin(), _model()
    plan = _plan(model, twin=twin)

    with pytest.raises(SchemaError, match="Unknown optimization proposal ids"):
        accept_optimization_proposals(twin, plan, ("missing",))

    updated, applied = accept_optimization_proposals(twin, plan, ())
    assert applied == ()
    assert updated is not twin


def test_engine_integration_and_legacy_json() -> None:
    twin = _chain_twin()
    model = _model(
        make_rule("r1", order=0, src_zone="z-ext", dst_zone="z-server"),
        make_rule("r2", order=1, src_zone="z-ext", dst_zone="z-server"),
    )

    analysis = analyze_design(twin, model=model)

    assert isinstance(analysis.optimizer, OptimizationPlan)
    assert _by_kind(analysis.optimizer, OptimizationKind.merge_duplicates)
    payload = analysis.model_dump()
    payload.pop("optimizer")
    legacy = SecurityAnalysis.model_validate(payload)
    assert legacy.optimizer is None


def test_plan_is_bounded() -> None:
    from config.limits import MAX_OPTIMIZATION_PROPOSALS

    model = _model(
        *tuple(
            make_rule(
                f"r-{index}",
                order=index,
                src_zone="z-ext",
                dst_zone="z-server",
            )
            for index in range(20)
        )
    )

    plan = _plan(model)

    assert len(plan.proposals) <= MAX_OPTIMIZATION_PROPOSALS
