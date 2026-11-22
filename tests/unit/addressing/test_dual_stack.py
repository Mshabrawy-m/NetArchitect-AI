"""L1 tests for modeled IPv6 dual-stack planning rules.

All expected values are computed by hand in the comments; no value is copied
from a running implementation.
"""

from __future__ import annotations

import ipaddress

import pytest

from config.limits import MAX_V6_PREFIXES
from core.exceptions import LimitsExceededError
from core.schemas.addressing import AddressingPlan, Subnet, VlanPlan
from network.addressing import (
    DualStackRequest,
    Ipv6Scope,
    available_prefixes,
    classify_ipv6_scope,
    dual_stack_rows,
    plan_dual_stack,
    prefix_at,
    requests_from_plan,
    validate_dual_stack,
)


def _request(
    name: str,
    vlan_id: int | None = None,
    *,
    v6: str | None = None,
    v4: str | None = None,
) -> DualStackRequest:
    return DualStackRequest(
        name=name,
        vlan_id=vlan_id,
        ipv6_network=v6,
        ipv4_network=v4,
    )


def _codes(findings: object) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


def test_48_block_boundaries_hold_65536_prefixes() -> None:
    # Hand: 2**(64 - 48) = 2**16 = 65,536 /64 prefixes in a /48.
    assert available_prefixes("2001:db8::/48") == 65536
    # Hand: a /64 itself holds 2**(64 - 64) = 1 prefix; a /65 holds none.
    assert available_prefixes("2001:db8::/64") == 1
    assert available_prefixes("2001:db8::/65") == 0
    assert available_prefixes("10.0.0.0/8") == 0

    # Hand: index 0 is the block start; each /64 advances by 2**(128-64)
    # = 2**64 addresses, i.e. one increment of the fourth hextet.
    assert prefix_at("2001:db8::/48", 0) == ipaddress.ip_network("2001:db8::/64")
    assert prefix_at("2001:db8::/48", 1) == ipaddress.ip_network(
        "2001:db8:0:1::/64"
    )
    # Hand: a /48 fixes three hextets (2001:0db8:0000); each /64 adds one more
    # fixed hextet. The last index is 65535 = 0xFFFF, so the fourth hextet is
    # ffff: 2001:db8:0:ffff::/64.
    assert prefix_at("2001:db8::/48", 65535) == ipaddress.ip_network(
        "2001:db8:0:ffff::/64"
    )
    # Hand: there is no 65,536th prefix (indices are 0..65,535).
    with pytest.raises(ValueError, match="outside"):
        prefix_at("2001:db8::/48", 65536)


def test_auto_allocation_order_is_deterministic() -> None:
    # Submitted in reverse order; sorted order is by vlan_id, then name.
    requests = [
        _request("vlan-20", 20, v4="10.0.20.0/24"),
        _request("vlan-10", 10, v4="10.0.10.0/24"),
    ]
    plan = plan_dual_stack("2001:db8::/48", requests)

    assert [item.name for item in plan.assignments] == ["vlan-10", "vlan-20"]
    # Hand: first /64 of 2001:db8::/48 is 2001:db8::/64, second is
    # 2001:db8:0:1::/64 (one 2**64-address step).
    assert [item.ipv6_network for item in plan.assignments] == [
        "2001:db8::/64",
        "2001:db8:0:1::/64",
    ]
    assert [item.vlan_id for item in plan.assignments] == [10, 20]
    assert all(item.origin == "auto" for item in plan.assignments)
    assert dual_stack_rows(plan)[0]["ipv4_network"] == "10.0.10.0/24"


def test_exhaustion_is_reported_not_silently_truncated() -> None:
    # Hand: a /64 holds 2**(64-64) = 1 /64. Two VLANs therefore leave one
    # unallocated and utilization is 1/1 = 100.00 percent (prefix-based).
    plan = plan_dual_stack(
        "2001:db8::/64",
        [_request("first", 10), _request("second", 20)],
    )
    findings = validate_dual_stack("2001:db8::/64", plan)

    assert plan.prefixes_available == 1
    assert plan.prefixes_used == 1
    assert plan.unallocated == ("second",)
    assert plan.utilization_percent == 100.0
    assertion = next(item for item in findings if item.code == "ipv6_block_exhausted")
    assert assertion.affected_entities == ["second"]
    assert "1 used of 1 available" in assertion.explanation
    # Utilization counts prefixes, not the 2**64 addresses inside each /64.


def test_overlap_and_outside_block_are_typed_findings() -> None:
    # Both explicit prefixes are /64 but identical, so they overlap exactly.
    plan = plan_dual_stack(
        "2001:db8::/48",
        [
            _request("a", 10, v6="2001:db8::/64"),
            _request("b", 20, v6="2001:db8::/64"),
            # Hand: 2001:db9::/64 is a different /32, so it is outside 2001:db8::/48.
            _request("c", 30, v6="2001:db9::/64"),
        ],
    )
    findings = validate_dual_stack("2001:db8::/48", plan)
    codes = _codes(findings)

    assert "ipv6_prefix_overlap" in codes
    assert "ipv6_prefix_outside_block" in codes
    overlap = next(item for item in findings if item.code == "ipv6_prefix_overlap")
    assert overlap.affected_entities == ["a", "b"]


def test_64_rule_violation_is_reported_for_plan_and_assignment() -> None:
    plan = plan_dual_stack(
        "2001:db8::/48",
        [_request("a", 10, v6="2001:db8:0:1::/65")],
        prefix_length=56,
    )
    findings = validate_dual_stack("2001:db8::/48", plan)
    codes = _codes(findings)

    assert "ipv6_prefix_length_rule" in codes
    assert "ipv6_prefix_length_violation" in codes
    # Hand: at the requested /56 the block holds 2**(56-48) = 256 prefixes,
    # so one explicit assignment is 1/256 = 0.39 percent (prefix-based).
    assert plan.prefixes_available == 256
    assert plan.utilization_percent == 0.39


def test_scope_classification_documented_and_reported() -> None:
    # Documented classes: fe80::/10 link-local, fc00::/7 (incl. fd00::/8) ULA,
    # 2000::/3 GUA, everything else special.
    assert classify_ipv6_scope("fe80::/10") is Ipv6Scope.link_local
    assert classify_ipv6_scope("fd00:1234:5678::/48") is Ipv6Scope.unique_local
    assert classify_ipv6_scope("fd12::/16") is Ipv6Scope.unique_local
    assert classify_ipv6_scope("2001:db8::/48") is Ipv6Scope.global_unicast
    assert classify_ipv6_scope("ff00::/8") is Ipv6Scope.special

    ula = plan_dual_stack("fd00:1234:5678::/48", [_request("users", 10)])
    ula_findings = validate_dual_stack("fd00:1234:5678::/48", ula)
    assert ula.assignments[0].scope is Ipv6Scope.unique_local
    assert "ipv6_scope_unique_local" in _codes(ula_findings)
    assert not any(item.severity == "error" for item in ula_findings)

    link_local = plan_dual_stack("fe80::/10", [_request("users", 10)])
    link_findings = validate_dual_stack("fe80::/10", link_local)
    assert "ipv6_scope_link_local" in _codes(link_findings)

    gua = plan_dual_stack("2001:db8::/48", [_request("users", 10)])
    gua_findings = validate_dual_stack("2001:db8::/48", gua)
    assert not any(code.startswith("ipv6_scope") for code in _codes(gua_findings))


def test_missing_v6_and_v4_v6_mismatch_against_addressing_plan() -> None:
    addressing = AddressingPlan(
        vlan_plans=[
            VlanPlan(
                vlan_id=10,
                name="Users",
                subnets=[Subnet(name="users-v4", network="10.0.10.0/24")],
            ),
            VlanPlan(
                vlan_id=20,
                name="Servers",
                subnets=[Subnet(name="servers-v4", network="10.0.20.0/24")],
            ),
        ]
    )
    requests = [
        _request("users-v4", 99, v4="10.0.10.0/24"),
    ]
    plan = plan_dual_stack("2001:db8::/48", requests)
    findings = validate_dual_stack("2001:db8::/48", plan, addressing=addressing)
    codes = _codes(findings)

    assert "ipv6_missing_for_vlan" in codes
    assert "ipv4_ipv6_plan_mismatch" in codes
    missing = next(item for item in findings if item.code == "ipv6_missing_for_vlan")
    assert missing.affected_entities == ["servers-v4"]
    mismatch = next(
        item for item in findings if item.code == "ipv4_ipv6_plan_mismatch"
    )
    assert mismatch.affected_entities == ["users-v4"]


def test_requests_from_plan_treats_existing_v6_subnet_as_explicit() -> None:
    addressing = AddressingPlan(
        subnets=[Subnet(name="v6-only", network="fd00:1::/64")],
        vlan_plans=[
            VlanPlan(
                vlan_id=10,
                name="Users",
                subnets=[Subnet(name="users-v4", network="10.0.10.0/24")],
            )
        ],
    )
    requests = requests_from_plan(addressing)
    plan = plan_dual_stack("fd00::/48", requests)

    assert requests[0].ipv6_network == ipaddress.ip_network("fd00:1::/64")
    assert requests[0].ipv4_network is None
    v6_only = next(item for item in plan.assignments if item.name == "v6-only")
    assert v6_only.origin == "explicit"
    assert v6_only.ipv6_network == "fd00:1::/64"


def test_utilization_counts_prefixes_not_hosts() -> None:
    # Hand: /62 -> 2**(64-62) = 4 /64s. One assignment is 1/4 = 25.00 percent.
    # Counting hosts would give 2**64 addresses; this model never does that.
    plan = plan_dual_stack("2001:db8::/62", [_request("users", 10)])
    assert plan.prefixes_available == 4
    assert plan.prefixes_used == 1
    assert plan.utilization_percent == 25.0


def test_prefix_count_limit_is_enforced() -> None:
    requests = [
        _request(f"vlan-{index}", index + 1) for index in range(MAX_V6_PREFIXES + 1)
    ]
    with pytest.raises(LimitsExceededError, match="limit is"):
        plan_dual_stack("2001:db8::/48", requests)


def test_non_ipv6_block_is_rejected_by_planner_and_findings() -> None:
    with pytest.raises(ValueError, match="IPv6"):
        plan_dual_stack("10.0.0.0/8", [_request("users", 10)])

    plan = plan_dual_stack("2001:db8::/48", [_request("users", 10)])
    invalid = plan.model_copy(update={"block": "10.0.0.0/8"})
    findings = validate_dual_stack("10.0.0.0/8", invalid)
    assert "ipv6_block_not_ipv6" in _codes(findings)
