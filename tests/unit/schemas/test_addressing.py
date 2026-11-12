"""Unit tests for ``core.schemas.addressing``."""

import ipaddress

import pytest
from pydantic import ValidationError

from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet, VlanPlan


def _subnet(name: str, network: str, vlan_id: int | None = None) -> Subnet:
    return Subnet(name=name, network=network, vlan_id=vlan_id)


def _vlan_plan(vlan_id: int, subnets: list[Subnet]) -> VlanPlan:
    return VlanPlan(vlan_id=vlan_id, name="vlan", subnets=subnets)


# --- Subnet -----------------------------------------------------------------


def test_subnet_valid_v4() -> None:
    sub = _subnet("v4", "10.0.0.0/24")
    assert isinstance(sub.network, ipaddress.IPv4Network)
    assert sub.vlan_id is None


def test_subnet_valid_v6() -> None:
    sub = _subnet("v6", "2001:db8::/32")
    assert isinstance(sub.network, ipaddress.IPv6Network)


def test_subnet_host_bits_normalized() -> None:
    sub = _subnet("v4", "10.0.0.5/24")
    assert sub.network == ipaddress.ip_network("10.0.0.0/24")


def test_subnet_vlan_id_boundary_valid() -> None:
    assert _subnet("a", "10.0.0.0/24", vlan_id=1).vlan_id == 1
    assert _subnet("b", "10.0.1.0/24", vlan_id=4094).vlan_id == 4094


def test_subnet_vlan_id_zero_invalid() -> None:
    with pytest.raises(ValidationError):
        _subnet("a", "10.0.0.0/24", vlan_id=0)


def test_subnet_vlan_id_over_range_invalid() -> None:
    with pytest.raises(ValidationError):
        _subnet("a", "10.0.0.0/24", vlan_id=4095)


def test_subnet_json_round_trip_v4() -> None:
    sub = _subnet("v4", "10.0.0.0/24", vlan_id=10)
    assert Subnet.model_validate_json(sub.model_dump_json()) == sub


def test_subnet_json_round_trip_v6() -> None:
    sub = _subnet("v6", "2001:db8::/32", vlan_id=10)
    assert Subnet.model_validate_json(sub.model_dump_json()) == sub


# --- VlanPlan ----------------------------------------------------------------


def test_vlan_plan_valid_v4() -> None:
    plan = _vlan_plan(10, [_subnet("a", "10.0.0.0/24"), _subnet("b", "10.0.1.0/24")])
    assert plan.vlan_id == 10


def test_vlan_plan_valid_v6() -> None:
    plan = _vlan_plan(20, [_subnet("a", "2001:db8::/32"), _subnet("b", "2001:db9::/32")])
    assert plan.vlan_id == 20


def test_vlan_plan_overlap_v4_invalid() -> None:
    with pytest.raises(ValidationError):
        _vlan_plan(
            10,
            [_subnet("a", "10.0.0.0/24"), _subnet("b", "10.0.0.128/25")],
        )


def test_vlan_plan_overlap_v6_invalid() -> None:
    with pytest.raises(ValidationError):
        _vlan_plan(
            20,
            [_subnet("a", "2001:db8::/32"), _subnet("b", "2001:db8:8000::/33")],
        )


def test_vlan_plan_non_overlapping_v4_accepted() -> None:
    _vlan_plan(10, [_subnet("a", "10.0.0.0/24"), _subnet("b", "10.0.1.0/24")])


def test_vlan_plan_non_overlapping_v6_accepted() -> None:
    _vlan_plan(20, [_subnet("a", "2001:db8::/32"), _subnet("b", "2001:db9::/32")])


def test_vlan_plan_duplicate_subnet_name_invalid() -> None:
    with pytest.raises(ValidationError):
        _vlan_plan(
            10,
            [_subnet("dup", "10.0.0.0/24"), _subnet("dup", "10.0.1.0/24")],
        )


def test_vlan_plan_json_round_trip_v4() -> None:
    plan = _vlan_plan(10, [_subnet("a", "10.0.0.0/24")])
    assert VlanPlan.model_validate_json(plan.model_dump_json()) == plan


def test_vlan_plan_json_round_trip_v6() -> None:
    plan = _vlan_plan(20, [_subnet("a", "2001:db8::/32")])
    assert VlanPlan.model_validate_json(plan.model_dump_json()) == plan


# --- DhcpScope ---------------------------------------------------------------


def test_dhcp_scope_valid() -> None:
    scope = DhcpScope(
        name="scope",
        network="10.0.0.0/24",
        gateway="10.0.0.1",
        start_address="10.0.0.10",
        end_address="10.0.0.100",
    )
    assert scope.lease_minutes == 1440


def test_dhcp_scope_start_after_end_invalid() -> None:
    with pytest.raises(ValidationError):
        DhcpScope(
            name="scope",
            network="10.0.0.0/24",
            start_address="10.0.0.100",
            end_address="10.0.0.10",
        )


def test_dhcp_scope_start_outside_network_invalid() -> None:
    with pytest.raises(ValidationError):
        DhcpScope(
            name="scope",
            network="10.0.0.0/24",
            start_address="192.168.1.1",
            end_address="10.0.0.50",
        )


def test_dhcp_scope_end_outside_network_invalid() -> None:
    with pytest.raises(ValidationError):
        DhcpScope(
            name="scope",
            network="10.0.0.0/24",
            start_address="10.0.0.10",
            end_address="172.16.0.5",
        )


def test_dhcp_scope_json_round_trip_v4() -> None:
    scope = DhcpScope(
        name="scope",
        network="10.0.0.0/24",
        gateway="10.0.0.1",
        start_address="10.0.0.10",
        end_address="10.0.0.100",
        excluded_ranges=[("10.0.0.50", "10.0.0.55")],
    )
    restored = DhcpScope.model_validate_json(scope.model_dump_json())
    assert restored == scope


def test_dhcp_scope_json_round_trip_v6() -> None:
    scope = DhcpScope(name="scope", network="2001:db8::/64")
    assert DhcpScope.model_validate_json(scope.model_dump_json()) == scope


# --- AddressingPlan ----------------------------------------------------------


def test_addressing_plan_valid() -> None:
    plan = AddressingPlan(
        vlan_plans=[_vlan_plan(10, [_subnet("a", "10.0.0.0/24")])],
        subnets=[_subnet("b", "10.0.1.0/24")],
    )
    assert len(plan.subnets) == 1


def test_addressing_plan_cross_vlan_overlap_invalid() -> None:
    with pytest.raises(ValidationError):
        AddressingPlan(
            vlan_plans=[
                _vlan_plan(10, [_subnet("a", "10.0.0.0/24")]),
                _vlan_plan(20, [_subnet("b", "10.0.0.128/25")]),
            ],
        )


def test_addressing_plan_duplicate_name_across_vlan_invalid() -> None:
    with pytest.raises(ValidationError):
        AddressingPlan(
            vlan_plans=[
                _vlan_plan(10, [_subnet("dup", "10.0.0.0/24")]),
                _vlan_plan(20, [_subnet("dup", "10.0.1.0/24")]),
            ],
        )


def test_addressing_plan_json_round_trip() -> None:
    plan = AddressingPlan(
        vlan_plans=[_vlan_plan(10, [_subnet("a", "10.0.0.0/24")])],
        subnets=[_subnet("b", "10.0.1.0/24")],
    )
    restored = AddressingPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
