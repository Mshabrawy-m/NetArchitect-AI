"""VLSM allocation tests, including the classic textbook example."""

from __future__ import annotations

import ipaddress

import pytest

from config.limits import MAX_HOSTS_PER_SUBNET, MAX_SUBNETS
from core.exceptions import InsufficientAddressSpaceError, LimitsExceededError
from network.addressing import VlsmRequirement, allocate_vlsm


def _requirements(*pairs: tuple[str, int]) -> list[VlsmRequirement]:
    return [VlsmRequirement(name=name, required_hosts=hosts) for name, hosts in pairs]


def test_classic_vlsm_example_exact_allocations() -> None:
    result = allocate_vlsm(
        "192.168.1.0/24",
        _requirements(
            ("sales", 100),
            ("engineering", 50),
            ("operations", 25),
            ("finance", 10),
            ("guest", 2),
        ),
    )

    assert [str(item.network) for item in result.allocations] == [
        "192.168.1.0/25",
        "192.168.1.128/26",
        "192.168.1.192/27",
        "192.168.1.224/28",
        "192.168.1.240/29",
    ]
    assert [str(item.gateway) for item in result.allocations] == [
        "192.168.1.1",
        "192.168.1.129",
        "192.168.1.193",
        "192.168.1.225",
        "192.168.1.241",
    ]
    assert [str(item.first_host) for item in result.allocations] == [
        "192.168.1.2",
        "192.168.1.130",
        "192.168.1.194",
        "192.168.1.226",
        "192.168.1.242",
    ]
    assert [str(item.last_host) for item in result.allocations] == [
        "192.168.1.126",
        "192.168.1.190",
        "192.168.1.222",
        "192.168.1.238",
        "192.168.1.246",
    ]
    assert [item.host_capacity for item in result.allocations] == [125, 61, 29, 13, 5]
    assert result.reserved_addresses == 3
    assert result.allocated_addresses == 248
    assert result.remaining_addresses == 8


def test_requirements_are_sorted_largest_first_and_indexed() -> None:
    result = allocate_vlsm(
        "10.0.0.0/24",
        _requirements(("small", 2), ("large", 100), ("medium", 25)),
    )

    assert [item.name for item in result.allocations] == ["large", "medium", "small"]
    assert [item.request_index for item in result.allocations] == [1, 2, 0]
    assert [str(item.network) for item in result.allocations] == [
        "10.0.0.0/25",
        "10.0.0.128/27",
        "10.0.0.160/29",
    ]


def test_deterministic_repeat() -> None:
    requirements = _requirements(("a", 40), ("b", 20), ("c", 5))
    assert allocate_vlsm("172.16.0.0/16", requirements) == allocate_vlsm(
        "172.16.0.0/16", requirements
    )


def test_custom_reserved_count_changes_prefix() -> None:
    with_default = allocate_vlsm("192.168.1.0/24", _requirements(("hosts", 2)))
    with_two = allocate_vlsm(
        "192.168.1.0/24",
        _requirements(("hosts", 2)),
        reserved_addresses=2,
    )

    assert str(with_default.allocations[0].network) == "192.168.1.0/29"
    assert with_default.allocations[0].host_capacity == 5
    assert str(with_two.allocations[0].network) == "192.168.1.0/30"
    assert with_two.allocations[0].host_capacity == 2
    assert str(with_two.allocations[0].gateway) == "192.168.1.1"
    assert str(with_two.allocations[0].first_host) == "192.168.1.1"


def test_slash_30_with_reserved_addresses_has_one_host() -> None:
    result = allocate_vlsm("10.0.0.0/24", _requirements(("wan", 1)))

    allocation = result.allocations[0]
    assert str(allocation.network) == "10.0.0.0/30"
    assert str(allocation.gateway) == "10.0.0.1"
    assert str(allocation.first_host) == "10.0.0.2"
    assert str(allocation.last_host) == "10.0.0.2"
    assert allocation.host_capacity == 1


def test_ipv6_allocation_is_arithmetic_only() -> None:
    result = allocate_vlsm(
        "2001:db8::/120",
        _requirements(("users", 10), ("servers", 20)),
        reserved_addresses=2,
    )

    assert [str(item.network) for item in result.allocations] == [
        "2001:db8::/123",
        "2001:db8::20/124",
    ]
    servers, users = result.allocations
    assert servers.total_addresses == 32
    assert servers.host_capacity == 30
    assert str(servers.gateway) == "2001:db8::1"
    assert str(servers.first_host) == "2001:db8::2"
    assert str(servers.last_host) == "2001:db8::1f"
    assert users.total_addresses == 16
    assert users.host_capacity == 14


def test_ipv6_slash_64_request_does_not_enumerate_hosts() -> None:
    result = allocate_vlsm(
        "2001:db8::/64",
        _requirements(("segment", 100)),
        reserved_addresses=2,
    )

    allocation = result.allocations[0]
    assert str(allocation.network) == "2001:db8::/121"
    assert allocation.total_addresses == 128
    assert allocation.host_capacity == 126


def test_insufficient_space_lists_what_could_not_be_allocated() -> None:
    with pytest.raises(InsufficientAddressSpaceError) as error:
        allocate_vlsm(
            "192.168.1.0/24",
            _requirements(("first", 200), ("second", 100), ("third", 50)),
        )

    message = str(error.value)
    assert "Could not allocate" in message
    assert "second" in message
    assert "third" in message


def test_requirement_larger_than_parent_is_rejected() -> None:
    with pytest.raises(InsufficientAddressSpaceError, match="too-big"):
        allocate_vlsm("10.0.0.0/24", _requirements(("too-big", 1000)))


def test_point_to_point_parent_is_rejected() -> None:
    with pytest.raises(InsufficientAddressSpaceError, match="does not fit"):
        allocate_vlsm("10.0.0.0/31", _requirements(("link", 1)))


def test_duplicate_requirement_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate VLSM requirement name"):
        allocate_vlsm(
            "10.0.0.0/24",
            _requirements(("same", 10), ("same", 20)),
        )


def test_too_many_requirements_are_rejected() -> None:
    requirements = [
        VlsmRequirement(name=f"req-{index}", required_hosts=1)
        for index in range(MAX_SUBNETS + 1)
    ]
    with pytest.raises(LimitsExceededError, match=str(MAX_SUBNETS)):
        allocate_vlsm("10.0.0.0/8", requirements)


def test_too_many_hosts_are_rejected() -> None:
    with pytest.raises(LimitsExceededError, match=str(MAX_HOSTS_PER_SUBNET)):
        allocate_vlsm(
            "10.0.0.0/8",
            [
                VlsmRequirement(
                    name="oversized",
                    required_hosts=MAX_HOSTS_PER_SUBNET,
                )
            ],
        )


def test_invalid_reserved_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="reserved_addresses"):
        allocate_vlsm(
            "10.0.0.0/24",
            _requirements(("hosts", 10)),
            reserved_addresses=1,
        )


def test_empty_requirements_return_empty_result() -> None:
    result = allocate_vlsm("10.0.0.0/24", [])

    assert result.allocations == []
    assert result.remaining_addresses == 256


def test_property_allocations_are_inside_parent_and_do_not_overlap() -> None:
    parent = ipaddress.ip_network("10.0.0.0/16")
    result = allocate_vlsm(
        parent,
        _requirements(
            ("a", 1000),
            ("b", 500),
            ("c", 250),
            ("d", 100),
            ("e", 50),
            ("f", 10),
            ("g", 2),
        ),
    )

    networks = [item.network for item in result.allocations]
    assert len(networks) == 7
    for network in networks:
        assert network.subnet_of(parent)
    for index, network_a in enumerate(networks):
        for network_b in networks[index + 1 :]:
            assert not network_a.overlaps(network_b)
    assert result.allocated_addresses == sum(
        item.total_addresses for item in result.allocations
    )
    assert result.allocated_addresses + result.remaining_addresses == parent.num_addresses
