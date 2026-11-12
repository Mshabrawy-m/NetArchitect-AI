"""Unit tests for ``core.schemas.validation``."""

import pytest
from pydantic import ValidationError

from core.schemas.validation import Finding, Severity, ValidationReport


@pytest.mark.parametrize("severity", list(Severity))
def test_finding_each_severity_valid(severity: Severity) -> None:
    finding = Finding(severity=severity, code="X001", explanation="oops")
    assert finding.severity is severity


def test_finding_invalid_severity_invalid() -> None:
    with pytest.raises(ValidationError):
        Finding(severity="catastrophe", code="X001", explanation="oops")


def test_finding_defaults() -> None:
    finding = Finding(severity=Severity.warning, code="X001", explanation="oops")
    assert finding.affected_entities == []
    assert finding.remediation == ""


def test_finding_json_round_trip() -> None:
    finding = Finding(
        severity=Severity.error,
        code="X001",
        affected_entities=["r1", "l1"],
        explanation="link over capacity",
        remediation="upgrade link",
    )
    assert Finding.model_validate_json(finding.model_dump_json()) == finding


def test_validation_report_valid() -> None:
    report = ValidationReport(
        findings=[Finding(severity=Severity.warning, code="X001", explanation="oops")],
        is_valid=False,
        summary="1 warning",
    )
    assert report.is_valid is False
    assert len(report.findings) == 1


def test_validation_report_defaults() -> None:
    report = ValidationReport()
    assert report.findings == []
    assert report.is_valid is True


def test_validation_report_json_round_trip() -> None:
    report = ValidationReport(
        findings=[
            Finding(severity=Severity.critical, code="C001", explanation="bad"),
            Finding(severity=Severity.info, code="I001", explanation="fyi"),
        ],
        is_valid=False,
        summary="mixed",
    )
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report
