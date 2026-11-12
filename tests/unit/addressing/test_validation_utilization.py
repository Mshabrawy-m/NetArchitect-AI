"""Overlap, duplicate-address, and utilization tests."""

from __future__ import annotations

import pytest

from core.schemas.addressing import Subnet
from core.schemas.validation import Severity
from network.addressing import (
    AddressAssignment,
    UtilizationEntry,
    build_utilization_report,
    detect_duplicate_ips,
    detect_overlaps,
    validate_addressing,
)


def _subnet(name: str, network: str) -> Subnet:
    return Subnet(name=name, network=network)


def test_overlapping_subnets_are_detected() -> None:
    findings = detect_overlaps(
        [
            _subnet("parent", "10.0.0.0/24"),
            _subnet("child", "10.0.0.128/25"),
        ]
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity is Severity.error
    assert finding.code == "subnet_overlap"
    assert finding.affected_entities == ["parent", "child"]
    assert "overlaps" in finding.explanation
    assert finding.remediation


def test_adjacent_subnets_do_not_overlap() -> None:
    findings = detect_overlaps(
        [
            _subnet("first", "10.0.0.0/25"),
            _subnet("second", "10.0.0.128/25"),
        ]
    )

    assert findings == []


def test_mixed_ip_versions_do_not_crash_overlap_detection() -> None:
    findings = detect_overlaps(
        [
            _subnet("v4", "10.0.0.0/24"),
            _subnet("v6", "2001:db8::/64"),
        ]
    )

    assert findings == []


def test_duplicate_ips_are_reported_per_address() -> None:
    findings = detect_duplicate_ips(
        [
            AddressAssignment(entity="router-1", address="10.0.0.1"),
            AddressAssignment(entity="router-2", address="10.0.0.1"),
            AddressAssignment(entity="server-1", address="10.0.0.10"),
        ]
    )

    assert len(findings) == 1
    assert findings[0].code == "duplicate_ip"
    assert findings[0].affected_entities == ["router-1", "router-2"]
    assert "10.0.0.1" in findings[0].explanation


def test_unique_ips_produce_no_findings() -> None:
    findings = detect_duplicate_ips(
        [
            AddressAssignment(entity="a", address="10.0.0.1"),
            AddressAssignment(entity="b", address="2001:db8::1"),
        ]
    )

    assert findings == []


def test_validation_report_combines_findings() -> None:
    report = validate_addressing(
        [
            _subnet("one", "10.0.0.0/24"),
            _subnet("two", "10.0.0.0/25"),
        ],
        [
            AddressAssignment(entity="a", address="10.0.0.1"),
            AddressAssignment(entity="b", address="10.0.0.1"),
        ],
    )

    assert report.is_valid is False
    assert len(report.findings) == 2
    assert report.summary == "2 addressing finding(s)."


def test_clean_validation_report_is_valid() -> None:
    report = validate_addressing([_subnet("one", "10.0.0.0/24")])

    assert report.is_valid is True
    assert report.findings == []
    assert report.summary == "No addressing findings."


def test_utilization_for_one_subnet() -> None:
    report = build_utilization_report(
        [UtilizationEntry(name="office", network="192.168.1.0/24", used_addresses=100)]
    )

    row = report.subnets[0]
    assert row.total_addresses == 256
    assert row.usable_addresses == 254
    assert row.used_addresses == 100
    assert row.remaining_addresses == 154
    assert row.utilization_percent == pytest.approx(39.37)
    assert report.utilization_percent == pytest.approx(39.37)


def test_utilization_includes_parent_totals() -> None:
    report = build_utilization_report(
        [
            UtilizationEntry(name="a", network="10.0.1.0/24", used_addresses=100),
            UtilizationEntry(name="b", network="10.0.2.0/24", used_addresses=50),
        ],
        parent="10.0.0.0/16",
    )

    assert report.parent_total_addresses == 65536
    assert report.parent_used_addresses == 150
    assert report.parent_remaining_addresses == 65386
    assert report.parent_utilization_percent == pytest.approx(0.23)


def test_utilization_rejects_usage_above_capacity() -> None:
    with pytest.raises(ValueError, match="only 254 are usable"):
        build_utilization_report(
            [
                UtilizationEntry(
                    name="office", network="192.168.1.0/24", used_addresses=255
                )
            ]
        )


def test_utilization_rejects_subnet_outside_parent() -> None:
    with pytest.raises(ValueError, match="not inside parent"):
        build_utilization_report(
            [UtilizationEntry(name="other", network="10.1.0.0/24", used_addresses=1)],
            parent="10.0.0.0/16",
        )


def test_ipv6_utilization_is_computed_without_enumeration() -> None:
    report = build_utilization_report(
        [
            UtilizationEntry(
                name="segment", network="2001:db8::/64", used_addresses=5000
            )
        ],
        parent="2001:db8::/48",
    )

    row = report.subnets[0]
    assert row.total_addresses == 2**64
    assert row.usable_addresses == 2**64 - 1
    assert row.remaining_addresses == 2**64 - 1 - 5000
    assert row.utilization_percent == 0.0
    assert report.parent_total_addresses == 2**80
