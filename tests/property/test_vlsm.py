"""Bounded allocation invariants for deterministic VLSM planning."""

from __future__ import annotations

from ipaddress import ip_network
from itertools import combinations

from hypothesis import given
from hypothesis import strategies as st

from core.exceptions import InsufficientAddressSpaceError
from network.addressing.vlsm import VlsmRequirement, allocate_vlsm
from tests.property.config import BOUNDED


@st.composite
def _parents(draw):
    version = draw(st.sampled_from((4, 6)))
    if version == 4:
        second = draw(st.integers(0, 255))
        third = draw(st.integers(0, 255))
        prefix = draw(st.integers(16, 24))
        return ip_network(f"10.{second}.{third}.0/{prefix}", strict=False)
    high = draw(st.integers(0, 0xFFFF))
    low = draw(st.integers(0, 0xFFFF))
    prefix = draw(st.integers(48, 56))
    return ip_network(f"2001:db8:{high:x}:{low:x}::/{prefix}", strict=False)


@st.composite
def _requirements(draw):
    hosts = draw(st.lists(st.integers(0, 80), max_size=8))
    return tuple(
        VlsmRequirement(name=f"req-{index}", required_hosts=value)
        for index, value in enumerate(hosts)
    )


@BOUNDED
@given(parent=_parents(), requirements=_requirements())
def test_vlsm_allocations_are_bounded_non_overlapping_and_deterministic(
    parent, requirements
) -> None:
    try:
        result = allocate_vlsm(str(parent), requirements)
    except InsufficientAddressSpaceError:
        return

    parent_network = ip_network(str(result.parent))
    expected_order = sorted(
        range(len(requirements)),
        key=lambda index: (-requirements[index].required_hosts, index),
    )
    assert [item.request_index for item in result.allocations] == expected_order
    assert [item.name for item in result.allocations] == [
        requirements[index].name for index in expected_order
    ]

    networks = []
    for allocation in result.allocations:
        network = ip_network(str(allocation.network))
        networks.append(network)
        assert network.subnet_of(parent_network)
        expected_hosts = requirements[allocation.request_index].required_hosts
        assert allocation.required_hosts == expected_hosts
        max_prefix = 32 if network.version == 4 else 128
        max_vlsm_prefix = 30 if network.version == 4 else 126
        assert network.prefixlen <= max_vlsm_prefix
        assert allocation.host_capacity >= allocation.required_hosts
        assert allocation.total_addresses == 1 << (max_prefix - network.prefixlen)
        assert allocation.reserved_addresses == result.reserved_addresses
        assert int(network.network_address) <= int(allocation.gateway) <= int(
            allocation.first_host
        )
        assert int(allocation.first_host) <= int(allocation.last_host)
        if network.version == 4:
            assert int(allocation.last_host) == int(network.broadcast_address) - 1
        else:
            assert int(allocation.last_host) == int(network.broadcast_address)

    for first, second in combinations(networks, 2):
        assert not first.overlaps(second)

    assert result.allocated_addresses == sum(
        allocation.total_addresses for allocation in result.allocations
    )
    assert result.remaining_addresses == (
        parent_network.num_addresses - result.allocated_addresses
    )
