"""L2 tests for the modeled NAT/PAT sizing rules.

Expected numbers are computed by hand in comments; no simulation runs.
"""

from __future__ import annotations

import pytest

from config.limits import MAX_NAT_RULES
from core.exceptions import LimitsExceededError
from network.addressing import (
    DEFAULT_USABLE_PORTS_PER_ADDRESS,
    NatPlan,
    NatRule,
    NatType,
    analyze_nat_plan,
    derived_host_count,
)


def _codes(analysis: object) -> set[str]:
    return {finding.code for finding in analysis.findings}  # type: ignore[attr-defined]


def _rule(
    rule_id: str,
    nat_type: str,
    *,
    inside: list[str] | None = None,
    outside: list[str] | None = None,
    hosts: int | None = None,
    sessions: int = 1,
    ports: int = DEFAULT_USABLE_PORTS_PER_ADDRESS,
) -> NatRule:
    return NatRule(
        id=rule_id,
        name=f"rule-{rule_id}",
        nat_type=NatType(nat_type),
        inside_zone=f"zone-{rule_id}",
        inside_subnets=tuple(inside or ["10.0.0.0/24"]),
        outside_pools=tuple(outside or ["203.0.113.0/28"]),
        inside_hosts=hosts,
        sessions_per_host=sessions,
        usable_ports_per_address=ports,
    )


def test_default_port_budget_is_hand_computed() -> None:
    # Hand: usable TCP/UDP source ports 1024..65535 inclusive =
    # 65535 - 1024 + 1 = 64512.
    assert DEFAULT_USABLE_PORTS_PER_ADDRESS == 64512


def test_static_pool_sizing_is_exact() -> None:
    analysis = analyze_nat_plan(
        NatPlan(
            rules=[
                _rule(
                    "s1",
                    "static",
                    inside=["10.0.10.0/24"],
                    outside=["203.0.113.0/28"],
                    hosts=10,
                )
            ]
        )
    )
    sizing = analysis.sizings[0]
    # Hand: /28 = 2**(32-28) = 16 outside addresses; one-to-one needs 10.
    assert (sizing.inside_hosts, sizing.pool_addresses) == (10, 16)
    assert sizing.required_addresses == 10
    assert sizing.required_sessions == 0
    assert analysis.findings == ()


def test_static_and_dynamic_pool_shortfalls_are_findings() -> None:
    analysis = analyze_nat_plan(
        NatPlan(
            rules=[
                _rule("s2", "static", outside=["203.0.113.0/30"], hosts=10),
                _rule("d2", "dynamic_pool", outside=["198.51.100.0/28"], hosts=20),
            ]
        )
    )
    # Hand: /30 = 4 addresses, shortfall 10 - 4 = 6.
    # Hand: /28 = 16 addresses, shortfall 20 - 16 = 4.
    small = next(
        finding
        for finding in analysis.findings
        if finding.code == "nat_pool_too_small" and finding.affected_entities == ["s2"]
    )
    assert "Shortfall: 6" in small.explanation
    dynamic = next(
        finding
        for finding in analysis.findings
        if finding.code == "nat_pool_too_small" and finding.affected_entities == ["d2"]
    )
    assert "Shortfall: 4" in dynamic.explanation
    assert all(item.required_sessions == 0 for item in analysis.sizings)


def test_derived_host_count_uses_documented_ipv4_rules() -> None:
    rule = _rule("derived", "dynamic_pool", inside=["10.0.0.0/26"], hosts=None)
    # Hand: /26 = 64 addresses; 64 - 2 (network, broadcast) = 62 hosts.
    assert derived_host_count(rule) == 62
    # Hand: RFC 3021 /31 = 2 usable addresses; /32 = 1 host.
    assert derived_host_count(_rule("p2p", "static", inside=["10.0.0.0/31"])) == 2
    assert derived_host_count(_rule("host", "static", inside=["10.0.0.0/32"])) == 1
    # IPv6 inside subnets are never enumerated and add no derived hosts.
    assert derived_host_count(_rule("v6", "static", inside=["fd00::/64"])) == 0

    analysis = analyze_nat_plan(
        NatPlan(rules=[_rule("d3", "dynamic_pool", inside=["10.0.0.0/26"],
                            outside=["198.51.100.0/27"])])
    )
    # Hand: 62 hosts need 62 addresses; /27 = 32, shortfall 30.
    assert "Shortfall: 30" in analysis.findings[0].explanation


def test_pat_capacity_formula_and_assumptions_are_shown() -> None:
    ok = analyze_nat_plan(
        NatPlan(
            rules=[
                _rule(
                    "p1",
                    "pat_overload",
                    outside=["198.51.100.0/31"],
                    hosts=500,
                )
            ]
        )
    )
    # Hand: /31 = 2 outside addresses; 2 x 64512 = 129024 sessions; 500 < capacity.
    assert ok.sizings[0].session_capacity == 129024
    assert ok.sizings[0].required_sessions == 500
    assert ok.findings == ()

    overflow = analyze_nat_plan(
        NatPlan(
            rules=[
                _rule(
                    "p2",
                    "pat_overload",
                    outside=["198.51.100.7/32"],
                    hosts=3,
                    sessions=30_000,
                )
            ]
        )
    )
    # Hand: /32 = 1 address; 1 x 64512 = 64512 sessions.
    # Need 3 x 30,000 = 90,000; overload 90,000 - 64,512 = 25,488.
    sizing = overflow.sizings[0]
    assert (sizing.required_sessions, sizing.session_capacity) == (90_000, 64_512)
    finding = next(
        finding
        for finding in overflow.findings
        if finding.code == "nat_pat_port_capacity_exceeded"
    )
    assert "3 hosts x 30000 sessions/host" in finding.explanation
    assert "1 x 64512 = 64512" in finding.explanation
    assert "25488" in finding.explanation
    assert "ports 1024..65535" in finding.explanation


def test_overlapping_translations_are_detected_in_both_directions() -> None:
    analysis = analyze_nat_plan(
        NatPlan(
            rules=[
                _rule("a", "static", inside=["10.0.0.0/24"],
                      outside=["203.0.113.0/28"], hosts=2),
                _rule("b", "static", inside=["10.0.0.0/24"],
                      outside=["203.0.113.0/28"], hosts=2),
            ]
        )
    )
    overlaps = [
        finding
        for finding in analysis.findings
        if finding.code == "nat_overlapping_translations"
    ]
    assert len(overlaps) == 2
    assert any("Inside prefix" in finding.explanation for finding in overlaps)
    assert any("Outside pool" in finding.explanation for finding in overlaps)


def test_private_space_outside_is_reported() -> None:
    analysis = analyze_nat_plan(
        NatPlan(
            rules=[
                _rule(
                    "leak",
                    "pat_overload",
                    outside=[
                        "10.0.0.0/24",
                        "172.16.0.0/12",
                        "192.168.0.0/16",
                        "fd00::/48",
                    ],
                )
            ]
        )
    )
    leaks = [
        finding
        for finding in analysis.findings
        if finding.code == "nat_private_space_outside"
    ]
    # Hand: three RFC 1918 IPv4 ranges plus ULA fc00::/7 (fd00::/48 is inside it).
    assert len(leaks) == 4
    assert {finding.affected_entities[1] for finding in leaks} == {
        "10.0.0.0/24",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fd00::/48",
    }


def test_incomplete_rules_are_flagged() -> None:
    incomplete = NatRule(
        id="empty",
        name="empty",
        nat_type=NatType.dynamic_pool,
        inside_zone="zone",
    )
    analysis = analyze_nat_plan(NatPlan(rules=[incomplete]))
    assert _codes(analysis) == {"nat_no_inside_subnets", "nat_empty_pool"}


def test_unknown_type_is_flagged_without_simulation() -> None:
    rule = _rule("bad", "static")
    corrupted = rule.model_copy(update={"nat_type": "not-a-type"})
    analysis = analyze_nat_plan(NatPlan(rules=[corrupted]))
    assert "nat_unknown_type" in _codes(analysis)
    assert all("simulat" in note.lower() for note in analysis.assumptions[:1])


def test_rule_limit_is_enforced() -> None:
    rules = [_rule(f"r{index}", "static", hosts=1) for index in range(MAX_NAT_RULES + 1)]
    with pytest.raises(LimitsExceededError, match="limit is"):
        analyze_nat_plan(NatPlan(rules=rules))
