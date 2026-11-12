"""DHCP scope planning tests."""

from __future__ import annotations

import pytest

from core.schemas.addressing import DhcpScope, Subnet
from core.schemas.validation import Severity
from network.vlan import (
    dhcp_scope_rows,
    plan_dhcp_scope,
    plan_dhcp_scopes,
    validate_dhcp_scope,
)


def test_default_scope_reserves_network_gateway_and_broadcast() -> None:
    scope = plan_dhcp_scope(Subnet(name="office", network="192.168.1.0/24"))

    assert scope.name == "office DHCP"
    assert str(scope.gateway) == "192.168.1.1"
    assert str(scope.start_address) == "192.168.1.2"
    assert str(scope.end_address) == "192.168.1.254"
    assert scope.lease_minutes == 1440
    assert [(str(start), str(end)) for start, end in scope.excluded_ranges] == [
        ("192.168.1.0", "192.168.1.1"),
        ("192.168.1.255", "192.168.1.255"),
    ]
    assert validate_dhcp_scope(scope) == []


def test_custom_gateway_changes_first_free_pool() -> None:
    scope = plan_dhcp_scope("192.168.1.0/24", gateway="192.168.1.254")

    assert str(scope.gateway) == "192.168.1.254"
    assert str(scope.start_address) == "192.168.1.1"
    assert str(scope.end_address) == "192.168.1.253"


def test_slash_30_pool_has_one_address() -> None:
    scope = plan_dhcp_scope("10.0.0.0/30")

    assert str(scope.gateway) == "10.0.0.1"
    assert str(scope.start_address) == "10.0.0.2"
    assert str(scope.end_address) == "10.0.0.2"


def test_slash_31_pool_uses_the_second_address() -> None:
    scope = plan_dhcp_scope("10.0.0.0/31")

    assert str(scope.gateway) == "10.0.0.0"
    assert str(scope.start_address) == "10.0.0.1"
    assert str(scope.end_address) == "10.0.0.1"


def test_slash_32_has_no_scope() -> None:
    with pytest.raises(ValueError, match="No DHCP pool is available"):
        plan_dhcp_scope("10.0.0.5/32")


def test_ipv6_scope_is_arithmetic_only() -> None:
    scope = plan_dhcp_scope("2001:db8::/64")

    assert str(scope.gateway) == "2001:db8::1"
    assert str(scope.start_address) == "2001:db8::2"
    assert str(scope.end_address) == "2001:db8::ffff:ffff:ffff:ffff"
    row = dhcp_scope_rows([scope])[0]
    assert row["pool_size"] == 2**64 - 2


def test_explicit_pool_is_accepted() -> None:
    scope = plan_dhcp_scope(
        "10.0.0.0/24",
        pool_start="10.0.0.10",
        pool_end="10.0.0.100",
    )

    assert str(scope.start_address) == "10.0.0.10"
    assert str(scope.end_address) == "10.0.0.100"


def test_pool_cannot_include_gateway() -> None:
    with pytest.raises(ValueError, match="reserved range"):
        plan_dhcp_scope(
            "10.0.0.0/24",
            pool_start="10.0.0.1",
            pool_end="10.0.0.100",
        )


def test_pool_cannot_include_custom_exclusion() -> None:
    with pytest.raises(ValueError, match="reserved range"):
        plan_dhcp_scope(
            "10.0.0.0/24",
            excluded_ranges=[("10.0.0.50", "10.0.0.60")],
            pool_start="10.0.0.10",
            pool_end="10.0.0.70",
        )


def test_pool_must_be_inside_subnet() -> None:
    with pytest.raises(ValueError, match="not inside"):
        plan_dhcp_scope(
            "10.0.0.0/24",
            pool_start="10.0.1.10",
            pool_end="10.0.1.20",
        )


def test_pool_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="after"):
        plan_dhcp_scope(
            "10.0.0.0/24",
            pool_start="10.0.0.100",
            pool_end="10.0.0.10",
        )


def test_pool_needs_both_boundaries() -> None:
    with pytest.raises(ValueError, match="both pool_start and pool_end"):
        plan_dhcp_scope("10.0.0.0/24", pool_start="10.0.0.10")


def test_exclusion_must_be_inside_subnet() -> None:
    with pytest.raises(ValueError, match="not inside"):
        plan_dhcp_scope(
            "10.0.0.0/24",
            excluded_ranges=[("10.0.1.10", "10.0.1.20")],
        )


def test_exclusion_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="after"):
        plan_dhcp_scope(
            "10.0.0.0/24",
            excluded_ranges=[("10.0.0.100", "10.0.0.10")],
        )


def test_gateway_must_be_usable() -> None:
    with pytest.raises(ValueError, match="not a usable address"):
        plan_dhcp_scope("10.0.0.0/24", gateway="10.0.0.255")


def test_lease_must_be_positive() -> None:
    with pytest.raises(ValueError, match="lease_minutes must be positive"):
        plan_dhcp_scope("10.0.0.0/24", lease_minutes=0)


def test_validate_scope_reports_gateway_in_pool() -> None:
    scope = DhcpScope(
        name="bad",
        network="10.0.0.0/24",
        gateway="10.0.0.1",
        start_address="10.0.0.1",
        end_address="10.0.0.100",
        excluded_ranges=[],
    )

    findings = validate_dhcp_scope(scope)
    codes = {finding.code for finding in findings}
    assert "dhcp_gateway_in_pool" in codes
    assert any(finding.severity is Severity.error for finding in findings)


def test_validate_scope_reports_pool_hitting_exclusion() -> None:
    scope = DhcpScope(
        name="bad",
        network="10.0.0.0/24",
        gateway="10.0.0.1",
        start_address="10.0.0.2",
        end_address="10.0.0.100",
        excluded_ranges=[("10.0.0.50", "10.0.0.60")],
    )

    findings = validate_dhcp_scope(scope)
    assert any(finding.code == "dhcp_pool_hits_excluded" for finding in findings)


def test_plan_scopes_for_multiple_subnets() -> None:
    scopes = plan_dhcp_scopes(
        [
            Subnet(name="a", network="10.0.0.0/24"),
            Subnet(name="b", network="10.0.1.0/24"),
        ],
        lease_minutes=60,
    )

    assert [scope.name for scope in scopes] == ["a DHCP", "b DHCP"]
    assert [scope.lease_minutes for scope in scopes] == [60, 60]
    assert [str(scope.start_address) for scope in scopes] == [
        "10.0.0.2",
        "10.0.1.2",
    ]
