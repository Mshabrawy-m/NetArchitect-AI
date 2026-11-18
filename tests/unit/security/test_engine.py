"""Policy-finding tests for the deterministic analysis engine."""

from __future__ import annotations

from core.schemas.validation import Severity
from security import (
    FindingCategory,
    PolicyAction,
    analyze_design,
)

from .design_helpers import hardened_design
from .helpers import make_rule


def _codes(analysis) -> set[str]:
    return {finding.code for finding in analysis.findings}


def _finding(analysis, code):
    return next(finding for finding in analysis.findings if finding.code == code)


def test_default_allow_policy_finding_is_explicit() -> None:
    twin, model = hardened_design()
    model = model.model_copy(update={"default_action": PolicyAction.allow})

    analysis = analyze_design(twin, model=model)
    finding = _finding(analysis, "POLICY-DEFAULT-ALLOW")

    assert finding.category is FindingCategory.policy
    assert finding.severity is Severity.error
    assert finding.affected_entities == ("default_action",)
    assert finding.evidence == ("model.default_action=allow",)
    assert analysis.risk.terms[-1].label == "default_action_bonus"
    assert analysis.risk.terms[-1].value == 2


def test_any_service_allow_policy_finding_is_explicit() -> None:
    twin, model = hardened_design()
    allow_any = make_rule(
        "allow-any-user-dmz",
        order=12,
        src_zone="z-user",
        dst_zone="z-dmz",
        services=(),
        any_service=True,
        action=PolicyAction.allow,
    )
    model = model.model_copy(update={"rules": model.rules + (allow_any,)})

    analysis = analyze_design(twin, model=model)
    finding = _finding(analysis, "POLICY-ANY-ALLOW")

    assert finding.affected_entities == ("allow-any-user-dmz",)
    assert finding.severity is Severity.error
    assert "any service" in finding.explanation


def test_shadowed_rule_policy_finding_is_explicit() -> None:
    twin, model = hardened_design()
    first = make_rule(
        "allow-http-first",
        order=12,
        src_zone="z-user",
        dst_zone="z-dmz",
        services=("http",),
        action=PolicyAction.allow,
    )
    second = make_rule(
        "allow-http-second",
        order=13,
        src_zone="z-user",
        dst_zone="z-dmz",
        services=("http",),
        action=PolicyAction.allow,
    )
    model = model.model_copy(update={"rules": model.rules + (first, second)})

    analysis = analyze_design(twin, model=model)
    finding = _finding(analysis, "POLICY-SHADOWED")

    assert finding.affected_entities == ("allow-http-second",)
    assert finding.severity is Severity.warning
    assert finding.evidence == ("earlier_rule=allow-http-first",)


def test_disabled_allow_rule_does_not_create_policy_finding() -> None:
    twin, model = hardened_design()
    disabled = make_rule(
        "disabled-any-allow",
        order=12,
        src_zone="z-user",
        dst_zone="z-dmz",
        services=(),
        any_service=True,
        action=PolicyAction.allow,
        enabled=False,
    )
    model = model.model_copy(update={"rules": model.rules + (disabled,)})

    codes = _codes(analyze_design(twin, model=model))

    assert "POLICY-ANY-ALLOW" not in codes
    assert "POLICY-SHADOWED" not in codes


def test_analysis_is_deterministic_for_same_inputs() -> None:
    twin, model = hardened_design()

    first = analyze_design(twin, model=model)
    second = analyze_design(twin, model=model)

    assert first.model_dump_json() == second.model_dump_json()
    assert first.template.text() == second.template.text()
