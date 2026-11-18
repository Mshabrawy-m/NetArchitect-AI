"""Design-health category tests for supplied security findings."""

from __future__ import annotations

from security import analyze_design
from services.validation import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    ValidationCategory,
    build_design_health,
    categorize_security_finding,
)
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.security.design_helpers import case_design


def test_security_is_a_basic_design_health_category() -> None:
    assert ValidationCategory.security in CATEGORY_ORDER
    assert CATEGORY_LABELS[ValidationCategory.security] == "Design-time security"

    twin, model = case_design("SEC-DW-004")
    findings = tuple(
        finding.to_validation_finding()
        for finding in analyze_design(twin, model=model).findings
    )

    basic = build_design_health(twin, security_findings=findings)
    expensive = build_design_health(
        twin, include_expensive=True, security_findings=findings
    )

    for health in (basic, expensive):
        security = health.findings_for(ValidationCategory.security)
        assert security
        assert {finding.code for finding in health.findings} >= {
            finding.code for finding in findings
        }
        assert health.is_valid is False
    assert basic.include_expensive is False
    assert expensive.include_expensive is True


def test_security_findings_are_absent_when_not_supplied() -> None:
    health = build_design_health(make_twin())

    assert health.findings_for(ValidationCategory.security) == ()
    assert ValidationCategory.security in health.by_category


def test_security_finding_categorization_prefixes() -> None:
    twin, model = case_design("SEC-DW-004")
    finding = next(
        item.to_validation_finding()
        for item in analyze_design(twin, model=model).findings
    )

    assert categorize_security_finding(finding) is ValidationCategory.security
