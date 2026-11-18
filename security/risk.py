"""Visible, deterministic modeled-risk arithmetic and overall posture."""

from __future__ import annotations

from core.schemas.validation import Severity

from .models import (
    PolicyAction,
    RiskAssessment,
    RiskLevel,
    RiskTerm,
    SecurityFinding,
    SecurityModel,
    SecurityPosture,
    SecuritySummary,
)

SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.info: 0,
    Severity.warning: 1,
    Severity.error: 4,
    Severity.critical: 8,
}
DEFAULT_ALLOW_BONUS = 2
_SEVERITY_RANK = {
    Severity.info: 0,
    Severity.warning: 1,
    Severity.error: 2,
    Severity.critical: 3,
}


def _level_for_score(score: int) -> RiskLevel:
    if score >= 8:
        return RiskLevel.high
    if score >= 4:
        return RiskLevel.elevated
    if score >= 1:
        return RiskLevel.moderate
    return RiskLevel.low


def assess_risk(
    findings: tuple[SecurityFinding, ...], default_action: PolicyAction
) -> RiskAssessment:
    """Compute a modeled score from fixed severity weights and default action.

    The returned ``formula`` and ``terms`` show every contribution so a reader
    can reproduce the number by hand. This is a design-model score, not CVSS and
    not a probability of compromise.
    """
    terms: list[RiskTerm] = []
    parts: list[str] = []
    for severity in (Severity.info, Severity.warning, Severity.error, Severity.critical):
        matching = [finding for finding in findings if finding.severity is severity]
        if not matching:
            continue
        weight = SEVERITY_WEIGHTS[severity]
        value = len(matching) * weight
        terms.append(
            RiskTerm(
                label=f"severity.{severity.value}",
                value=value,
                basis=f"{len(matching)} finding(s): " + ", ".join(
                    finding.code for finding in matching
                ),
            )
        )
        parts.append(f"{severity.value}:{len(matching)}x{weight}={value}")

    bonus = DEFAULT_ALLOW_BONUS if default_action is PolicyAction.allow else 0
    terms.append(
        RiskTerm(
            label="default_action_bonus",
            value=bonus,
            basis=f"model.default_action={default_action.value}",
        )
    )
    parts.append(f"default_action_bonus:{bonus}={bonus}")

    score = sum(term.value for term in terms)
    level = _level_for_score(score)
    formula = " + ".join(parts) + f" = {score} -> {level.value}"
    return RiskAssessment(score=score, level=level, formula=formula, terms=tuple(terms))


def build_summary(
    model: SecurityModel,
    findings: tuple[SecurityFinding, ...],
    risk: RiskAssessment,
) -> SecuritySummary:
    """Aggregate counts and derive the overall modeled posture."""
    counts: dict[str, int] = {}
    for finding in findings:
        key = finding.severity.value
        counts[key] = counts.get(key, 0) + 1
    highest = max(
        (finding.severity for finding in findings),
        key=lambda severity: _SEVERITY_RANK[severity],
        default=None,
    )

    if risk.level is RiskLevel.high or highest is Severity.critical:
        posture = SecurityPosture.high_risk
    elif findings or risk.level is not RiskLevel.low:
        posture = SecurityPosture.needs_review
    else:
        posture = SecurityPosture.hardened

    return SecuritySummary(
        zone_count=len(model.zones),
        service_count=len(model.services),
        rule_count=len(model.rules),
        default_action=model.default_action,
        finding_counts=counts,
        highest_severity=highest,
        posture=posture,
    )


__all__ = [
    "DEFAULT_ALLOW_BONUS",
    "SEVERITY_WEIGHTS",
    "assess_risk",
    "build_summary",
]
