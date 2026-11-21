"""S4: inert demand-scoped microsegmentation suggestion tests."""

from __future__ import annotations

import pytest

from config.limits import (
    MAX_FIREWALL_RULES,
    MAX_MICROSEGMENTATION_PROPOSALS,
    MAX_MICROSEGMENTATION_RULES,
)
from core.exceptions import SchemaError
from security import (
    MICROSEGMENTATION_NOTE,
    SECURITY_DISCLAIMER,
    FlowRequest,
    MicrosegmentationPlan,
    PolicyAction,
    Protocol,
    SecurityAnalysis,
    SecurityModel,
    ZoneType,
    accept_microsegmentation_proposals,
    analyze_design,
    build_microsegmentation_plan,
    set_security_model,
)
from tests.unit.digital_twin.helpers import make_twin

from .helpers import make_zone
from .test_reachability import _chain_twin, _four_zone_model

_FLOW = FlowRequest(
    id="guest-to-app",
    source_device_id="d-guest",
    destination_device_id="d-app",
    protocol=Protocol.tcp,
    port=80,
)


def test_plan_is_inert_and_only_targets_high_criticality() -> None:
    twin, model = set_security_model(_chain_twin(), _four_zone_model()), None
    baseline = twin.security.model_dump_json()
    model = twin.security

    plan = build_microsegmentation_plan(twin, model, flows=(_FLOW,))

    assert twin.security.model_dump_json() == baseline
    assert {item.zone_id for item in plan.proposals} == {"z-app", "z-db"}
    assert plan.note == MICROSEGMENTATION_NOTE
    assert plan.disclaimer == SECURITY_DISCLAIMER
    assert plan.flows_modeled == 1
    assert all(item.disclaimer == SECURITY_DISCLAIMER for item in plan.proposals)


def test_allow_rules_are_a_subset_of_demand_implied_needs() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    plan = build_microsegmentation_plan(twin, model, flows=(_FLOW,))
    app = next(item for item in plan.proposals if item.zone_id == "z-app")
    allow_rules = [
        addition.rule
        for addition in app.new_rules
        if addition.rule.action is PolicyAction.allow
    ]

    assert len(allow_rules) == 1
    rule = allow_rules[0]
    assert (rule.src_zone, rule.dst_zone) == ("z-guest", "z-app")
    assert rule.services == ("http",)
    assert rule.any_service is False
    assert app.allow_pairs == ("z-guest->z-app:http",)
    deny_pairs = {
        (addition.rule.src_zone, addition.rule.dst_zone)
        for addition in app.new_rules
        if addition.rule.action is PolicyAction.deny
    }
    assert ("z-ext", "z-app") in deny_pairs
    assert ("z-guest", "z-app") not in deny_pairs


def test_before_after_metrics_are_shown_and_consistent() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    plan = build_microsegmentation_plan(twin, model)
    app = next(item for item in plan.proposals if item.zone_id == "z-app")

    assert 0 <= app.before_score <= 100
    assert 0 <= app.after_score <= 100
    assert app.after_score >= app.before_score
    assert app.after_reachable_count <= app.before_reachable_count
    assert app.after_max_criticality_reached <= app.before_max_criticality_reached
    assert app.before_reachable_count == 3
    assert app.after_reachable_count == 2


def test_explicit_default_deny_is_requested_when_baseline_allows() -> None:
    twin = _chain_twin()
    model = _four_zone_model().model_copy(update={"default_action": PolicyAction.allow})

    plan = build_microsegmentation_plan(twin, model)

    assert plan.proposals
    assert all(item.default_deny_requested for item in plan.proposals)
    assert all(item.after_score >= item.before_score for item in plan.proposals)


def test_accept_creates_new_twin_and_logs_c4_decision() -> None:
    twin = set_security_model(_chain_twin(), _four_zone_model())
    baseline = twin.security.model_dump_json()
    plan = build_microsegmentation_plan(twin, twin.security)
    proposal = next(item for item in plan.proposals if item.zone_id == "z-app")
    decisions = []

    updated, applied = accept_microsegmentation_proposals(
        twin,
        plan,
        (proposal.id,),
        fingerprint=lambda item: f"fp-{len(item.security.rules)}",
        on_decision=decisions.append,
    )

    assert applied == (proposal.id,)
    assert updated is not twin
    assert twin.security.model_dump_json() == baseline
    assert len(updated.security.rules) == len(baseline_rules := twin.security.rules) + len(
        proposal.new_rules
    )
    assert [rule.order for rule in updated.security.rules] == list(
        range(len(updated.security.rules))
    )
    assert tuple(rule.id for rule in updated.security.rules[-len(baseline_rules) :]) == tuple(
        rule.id for rule in baseline_rules
    )
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.kind == "security_proposal_accepted"
    assert decision.page == "Security Analysis"
    assert decision.details[-1] == ("default_deny", "false")
    assert decision.source_fingerprint == "fp-3"
    assert decision.result_fingerprint == f"fp-{len(updated.security.rules)}"


def test_apply_rejects_unknown_ids() -> None:
    twin = set_security_model(_chain_twin(), _four_zone_model())
    plan = build_microsegmentation_plan(twin, twin.security)

    with pytest.raises(SchemaError, match="Unknown microsegmentation proposal ids"):
        accept_microsegmentation_proposals(twin, plan, ("missing",))

    updated, applied = accept_microsegmentation_proposals(twin, plan, ())
    assert applied == ()
    assert updated is not twin


def test_plan_is_bounded_and_empty_without_high_criticality() -> None:
    from config.limits import MAX_ZONES

    twin = make_twin(demands=())
    low_model = SecurityModel(
        zones=tuple(
            make_zone(f"z-{index}", zone_type=ZoneType.user, vlan_id=index + 1, criticality=3)
            for index in range(MAX_ZONES)
        )
    )
    assert build_microsegmentation_plan(twin, low_model).proposals == ()

    high_model = low_model.model_copy(
        update={
            "zones": tuple(
                zone.model_copy(update={"criticality": 5}) for zone in low_model.zones
            )
        }
    )
    plan = build_microsegmentation_plan(twin, high_model)

    assert len(plan.proposals) <= MAX_MICROSEGMENTATION_PROPOSALS
    assert all(
        len(item.new_rules) <= MAX_MICROSEGMENTATION_RULES for item in plan.proposals
    )
    assert all(
        len(item.new_rules) + len(high_model.rules) <= MAX_FIREWALL_RULES
        for item in plan.proposals
    )


def test_engine_integration_and_legacy_json() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    analysis = analyze_design(twin, model=model)

    assert isinstance(analysis.microsegmentation, MicrosegmentationPlan)
    assert analysis.microsegmentation.proposals
    payload = analysis.model_dump()
    payload.pop("microsegmentation")
    legacy = SecurityAnalysis.model_validate(payload)
    assert legacy.microsegmentation is None
