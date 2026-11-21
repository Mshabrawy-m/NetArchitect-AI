"""Deterministic design-time security analysis entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.schemas.validation import Severity

from .catalog import evaluate_design_rules
from .microsegmentation import build_microsegmentation_plan
from .models import (
    FlowCheckResult,
    FlowRequest,
    PolicyAction,
    SecurityAnalysis,
    SecurityFinding,
    SecurityModel,
)
from .operations import get_security_model
from .optimizer import build_optimization_plan
from .policy import check_flow
from .reachability import build_reachability_report
from .remediation import build_proposals
from .risk import assess_risk, build_summary
from .segmentation import score_segmentation
from .templates import render_template

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin


def _policy_findings(
    model: SecurityModel,
    flow_checks: tuple[FlowCheckResult, ...],
) -> tuple[SecurityFinding, ...]:
    findings: list[SecurityFinding] = []
    if model.default_action is PolicyAction.allow:
        findings.append(
            SecurityFinding(
                code="POLICY-DEFAULT-ALLOW",
                category="policy",
                severity=Severity.error,
                affected_entities=("default_action",),
                explanation="The modeled policy default action is allow.",
                remediation=(
                    "Set the explicit policy default to deny and add narrow allow rules."
                ),
                evidence=("model.default_action=allow",),
            )
        )

    enabled = [rule for rule in model.ordered_rules if rule.enabled]
    for index, rule in enumerate(enabled):
        if rule.any_service and rule.action is PolicyAction.allow:
            findings.append(
                SecurityFinding(
                    code="POLICY-ANY-ALLOW",
                    category="policy",
                    severity=Severity.error,
                    affected_entities=(rule.id,),
                    explanation=(
                        f"Enabled rule {rule.id!r} allows any service from "
                        f"{rule.src_zone!r} to {rule.dst_zone!r}."
                    ),
                    remediation="Replace any-service allow with named services.",
                    evidence=(f"rule.order={rule.order}",),
                )
            )
        for earlier in enabled[:index]:
            if earlier.src_zone != rule.src_zone or earlier.dst_zone != rule.dst_zone:
                continue
            covers = earlier.any_service or set(rule.services) <= set(earlier.services)
            if covers:
                findings.append(
                    SecurityFinding(
                        code="POLICY-SHADOWED",
                        category="policy",
                        severity=Severity.warning,
                        affected_entities=(rule.id,),
                        explanation=(
                            f"Rule {rule.id!r} is shadowed by earlier rule "
                            f"{earlier.id!r} for the same zones."
                        ),
                        remediation=(
                            "Reorder or narrow the earlier rule so both can match."
                        ),
                        evidence=(f"earlier_rule={earlier.id}",),
                    )
                )
                break

    for check in flow_checks:
        if check.verdict.value != "policy_denied":
            continue
        findings.append(
            SecurityFinding(
                code="POLICY-FLOW-DENIED",
                category="policy",
                severity=Severity.warning,
                affected_entities=(check.request.id,),
                explanation=(
                    f"Modeled flow {check.request.id!r} is denied by policy: "
                    f"{check.reason}"
                ),
                remediation=(
                    "Confirm the denial is intentional; otherwise revise the rule order."
                ),
                evidence=tuple(
                    f"{item.from_zone}->{item.to_zone}:"
                    f"{item.decision.matched_rule_id or 'default'}"
                    for item in check.zone_transitions
                ),
            )
        )
    return tuple(findings)


def analyze_design(
    twin: DigitalTwin,
    *,
    model: SecurityModel | None = None,
    flows: tuple[FlowRequest, ...] | list[FlowRequest] = (),
) -> SecurityAnalysis:
    """Return a complete, reproducible design-time security assessment."""
    security_model = model if model is not None else get_security_model(twin)
    flow_checks = tuple(check_flow(twin, security_model, request) for request in flows)
    findings = (
        *evaluate_design_rules(twin, security_model),
        *_policy_findings(security_model, flow_checks),
    )
    risk = assess_risk(findings, security_model.default_action)
    summary = build_summary(security_model, findings, risk)
    proposals = build_proposals(findings)
    template = render_template(security_model, proposals)
    reachability = build_reachability_report(twin, security_model)
    segmentation = score_segmentation(
        twin,
        security_model,
        flows=flows,
        matrix=reachability.matrix,
        blast_radii=reachability.blast_radii,
    )
    optimizer = build_optimization_plan(twin, security_model, flows=flows)
    microsegmentation = build_microsegmentation_plan(twin, security_model, flows=flows)
    return SecurityAnalysis(
        model=security_model,
        findings=findings,
        flow_checks=flow_checks,
        summary=summary,
        risk=risk,
        proposals=proposals,
        template=template,
        reachability=reachability,
        segmentation=segmentation,
        optimizer=optimizer,
        microsegmentation=microsegmentation,
    )


__all__ = ["analyze_design"]
