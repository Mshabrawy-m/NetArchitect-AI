"""Fixed catalog and crafted design-weakness case tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.schemas.validation import Severity
from security import (
    RULE_CATALOG,
    SECURITY_DISCLAIMER,
    CatalogRule,
    FindingCategory,
    SecurityPosture,
    analyze_design,
    catalog_rule,
    evaluate_design_rules,
)

from .design_helpers import case_design, hardened_design

_EXPECTED_IDS = tuple(f"SEC-DW-{index:03d}" for index in range(1, 10))
_EXPECTED_SEVERITIES = (
    Severity.error,
    Severity.warning,
    Severity.error,
    Severity.error,
    Severity.critical,
    Severity.warning,
    Severity.warning,
    Severity.warning,
    Severity.error,
)


def test_catalog_is_fixed_ordered_labeled_and_bounded() -> None:
    assert tuple(rule.id for rule in RULE_CATALOG) == _EXPECTED_IDS
    assert tuple(rule.base_severity for rule in RULE_CATALOG) == _EXPECTED_SEVERITIES
    assert all(rule.disclaimer == SECURITY_DISCLAIMER for rule in RULE_CATALOG)
    assert all(rule.trigger and rule.remediation for rule in RULE_CATALOG)
    assert catalog_rule("SEC-DW-005").title == (
        "Guest or IoT zone reaches internal zones"
    )

    bad_rule = catalog_rule("SEC-DW-001").model_copy(
        update={"disclaimer": "Different disclaimer"}
    )
    with pytest.raises(ValidationError, match="exact disclaimer"):
        CatalogRule.model_validate(bad_rule.model_dump())


@pytest.mark.parametrize("rule", RULE_CATALOG, ids=lambda rule: rule.id)
def test_each_catalog_rule_is_triggered_by_one_crafted_design(rule) -> None:
    twin, model = case_design(rule.id)

    findings = evaluate_design_rules(twin, model)

    matching = [finding for finding in findings if finding.code == rule.id]
    assert matching, f"{rule.id} did not trigger; got {[item.code for item in findings]}"
    finding = matching[0]
    assert finding.category is FindingCategory.design
    assert finding.severity is rule.base_severity
    assert finding.explanation
    assert finding.remediation == rule.remediation
    assert finding.disclaimer == SECURITY_DISCLAIMER
    validation_finding = finding.to_validation_finding()
    assert validation_finding.code == rule.id
    assert validation_finding.severity is rule.base_severity
    assert list(validation_finding.affected_entities) == list(
        finding.affected_entities
    )


def test_hardened_design_has_no_design_or_policy_findings() -> None:
    twin, model = hardened_design()

    assert evaluate_design_rules(twin, model) == ()
    analysis = analyze_design(twin, model=model)

    assert analysis.findings == ()
    assert analysis.flow_checks == ()
    assert analysis.risk.score == 0
    assert analysis.risk.level.value == "low"
    assert analysis.summary.posture is SecurityPosture.hardened
    assert analysis.summary.highest_severity is None
    assert analysis.proposals.rules == ()
    assert all(
        item.disclaimer == SECURITY_DISCLAIMER
        for item in (
            analysis,
            analysis.risk,
            analysis.summary,
            analysis.proposals,
            analysis.template,
        )
    )
