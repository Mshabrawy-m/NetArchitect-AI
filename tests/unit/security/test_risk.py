"""Visible risk arithmetic and posture tests."""

from __future__ import annotations

import pytest

from core.schemas.validation import Severity
from security import (
    FindingCategory,
    PolicyAction,
    RiskLevel,
    SecurityFinding,
    SecurityPosture,
    assess_risk,
    build_summary,
)

from .design_helpers import hardened_design


def _finding(code: str, severity: Severity) -> SecurityFinding:
    return SecurityFinding(
        code=code,
        category=FindingCategory.policy,
        severity=severity,
        explanation=f"Modeled finding {code}.",
        remediation="Review the modeled design.",
    )


def test_risk_arithmetic_is_hand_checkable() -> None:
    findings = (
        _finding("W1", Severity.warning),
        _finding("W2", Severity.warning),
        _finding("E1", Severity.error),
        _finding("C1", Severity.critical),
    )

    risk = assess_risk(findings, PolicyAction.allow)

    assert [(term.label, term.value) for term in risk.terms] == [
        ("severity.warning", 2),
        ("severity.error", 4),
        ("severity.critical", 8),
        ("default_action_bonus", 2),
    ]
    assert risk.score == 16
    assert risk.level is RiskLevel.high
    assert risk.formula == (
        "warning:2x1=2 + error:1x4=4 + critical:1x8=8 + "
        "default_action_bonus:2=2 = 16 -> high"
    )
    assert "W1" in risk.terms[0].basis and "W2" in risk.terms[0].basis


@pytest.mark.parametrize(
    ("count", "expected"),
    (
        (0, RiskLevel.low),
        (1, RiskLevel.moderate),
        (3, RiskLevel.moderate),
        (4, RiskLevel.elevated),
        (7, RiskLevel.elevated),
        (8, RiskLevel.high),
    ),
)
def test_risk_thresholds(count: int, expected: RiskLevel) -> None:
    findings = tuple(
        _finding(f"W{index}", Severity.warning) for index in range(count)
    )

    risk = assess_risk(findings, PolicyAction.deny)

    assert risk.score == count
    assert risk.level is expected


def test_posture_uses_findings_and_risk_level() -> None:
    _, model = hardened_design()
    clean_risk = assess_risk((), PolicyAction.deny)
    clean_summary = build_summary(model, (), clean_risk)

    assert clean_summary.posture is SecurityPosture.hardened
    assert clean_summary.finding_counts == {}
    assert clean_summary.zone_count == len(model.zones)
    assert clean_summary.service_count == len(model.services)
    assert clean_summary.rule_count == len(model.rules)

    warning = (_finding("W1", Severity.warning),)
    needs_review = build_summary(model, warning, assess_risk(warning, PolicyAction.deny))
    assert needs_review.posture is SecurityPosture.needs_review
    assert needs_review.finding_counts == {"warning": 1}
    assert needs_review.highest_severity is Severity.warning

    allow_only = build_summary(model, (), assess_risk((), PolicyAction.allow))
    assert allow_only.posture is SecurityPosture.needs_review

    critical = (_finding("C1", Severity.critical),)
    high_risk = build_summary(model, critical, assess_risk(critical, PolicyAction.deny))
    assert high_risk.posture is SecurityPosture.high_risk
    assert high_risk.highest_severity is Severity.critical
