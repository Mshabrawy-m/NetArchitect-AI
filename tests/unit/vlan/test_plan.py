"""VLAN plan tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.exceptions import (
    DuplicateIdError,
    InvalidVlanIdError,
    OverlappingSubnetError,
)
from core.schemas.addressing import Subnet
from network.vlan import (
    RESERVED_VLAN_IDS,
    VlanRequest,
    plan_vlans,
    vlan_rows,
)


def _request(department: str, network: str, **kwargs: object) -> VlanRequest:
    return VlanRequest(
        department=department,
        subnet=Subnet(name=f"{department}-subnet", network=network),
        **kwargs,
    )


def test_auto_vlan_ids_start_at_ten() -> None:
    result = plan_vlans(
        [
            _request("finance", "10.0.0.0/24"),
            _request("engineering", "10.0.1.0/24"),
        ]
    )

    assert [item.vlan_id for item in result.assignments] == [10, 11]
    assert [item.vlan_name for item in result.assignments] == [
        "finance VLAN",
        "engineering VLAN",
    ]
    assert [item.subnet_name for item in result.assignments] == [
        "finance-subnet",
        "engineering-subnet",
    ]
    assert result.reserved_vlan_ids == sorted(RESERVED_VLAN_IDS)


def test_explicit_and_automatic_ids_coexist() -> None:
    result = plan_vlans(
        [
            _request("finance", "10.0.0.0/24", vlan_id=200),
            _request("engineering", "10.0.1.0/24"),
        ]
    )

    assert [item.vlan_id for item in result.assignments] == [200, 10]


def test_start_id_skips_reserved_range() -> None:
    result = plan_vlans(
        [
            _request("a", "10.0.0.0/24"),
            _request("b", "10.0.1.0/24"),
            _request("c", "10.0.2.0/24"),
        ],
        start_vlan_id=1003,
    )

    assert [item.vlan_id for item in result.assignments] == [1006, 1007, 1008]


def test_duplicate_department_is_rejected() -> None:
    with pytest.raises(DuplicateIdError, match="Duplicate department"):
        plan_vlans(
            [
                _request("finance", "10.0.0.0/24"),
                _request("finance", "10.0.1.0/24"),
            ]
        )


def test_duplicate_subnet_name_is_rejected() -> None:
    with pytest.raises(DuplicateIdError, match="Duplicate subnet name"):
        plan_vlans(
            [
                _request("finance", "10.0.0.0/24"),
                VlanRequest(
                    department="engineering",
                    subnet=Subnet(name="finance-subnet", network="10.0.1.0/24"),
                ),
            ]
        )


def test_duplicate_explicit_vlan_id_is_rejected() -> None:
    with pytest.raises(DuplicateIdError, match="assigned more than once"):
        plan_vlans(
            [
                _request("finance", "10.0.0.0/24", vlan_id=200),
                _request("engineering", "10.0.1.0/24", vlan_id=200),
            ]
        )


@pytest.mark.parametrize("vlan_id", [0, 4095, 1, 1002, 1003, 1004, 1005])
def test_invalid_or_reserved_explicit_vlan_ids_are_rejected(vlan_id: int) -> None:
    with pytest.raises(ValidationError):
        _request("finance", "10.0.0.0/24", vlan_id=vlan_id)


def test_overlapping_subnets_are_rejected() -> None:
    with pytest.raises(OverlappingSubnetError, match="overlaps"):
        plan_vlans(
            [
                _request("finance", "10.0.0.0/24"),
                _request("engineering", "10.0.0.128/25"),
            ]
        )


def test_invalid_start_id_is_rejected() -> None:
    with pytest.raises(InvalidVlanIdError, match="start_vlan_id"):
        plan_vlans([_request("finance", "10.0.0.0/24")], start_vlan_id=5000)


def test_plan_is_deterministic() -> None:
    requests = [_request("finance", "10.0.0.0/24")]
    assert plan_vlans(requests) == plan_vlans(requests)


def test_vlan_rows_include_subnet_details() -> None:
    result = plan_vlans([_request("finance", "10.0.0.0/24")])
    rows = vlan_rows(result)

    assert rows == [
        {
            "department": "finance",
            "vlan_id": 10,
            "vlan_name": "finance VLAN",
            "subnet_name": "finance-subnet",
            "network": "10.0.0.0/24",
            "prefix_length": 24,
            "usable_hosts": 254,
            "purpose": "finance",
        }
    ]
