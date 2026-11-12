"""Known-answer tests for CIDR calculations."""

from __future__ import annotations

import pytest

from network.addressing import calculate_subnet, coerce_network
from network.addressing.cidr import calculate_subnet as calculate_subnet_direct


def test_ipv4_slash_24() -> None:
    info = calculate_subnet("192.168.1.0/24", name="office")

    assert info.name == "office"
    assert info.version == 4
    assert info.prefix_length == 24
    assert str(info.network) == "192.168.1.0/24"
    assert info.netmask == "255.255.255.0"
    assert info.wildcard_mask == "0.0.0.255"
    assert info.network_address == "192.168.1.0"
    assert info.broadcast_address == "192.168.1.255"
    assert info.first_usable == "192.168.1.1"
    assert info.last_usable == "192.168.1.254"
    assert info.usable_host_count == 254
    assert info.total_addresses == 256
    assert info.special_case == ""


def test_ipv4_slash_26() -> None:
    info = calculate_subnet_direct("192.168.1.64/26")

    assert info.network_address == "192.168.1.64"
    assert info.broadcast_address == "192.168.1.127"
    assert info.first_usable == "192.168.1.65"
    assert info.last_usable == "192.168.1.126"
    assert info.usable_host_count == 62
    assert info.total_addresses == 64


def test_ipv4_slash_30() -> None:
    info = calculate_subnet("10.0.0.0/30")

    assert info.network_address == "10.0.0.0"
    assert info.broadcast_address == "10.0.0.3"
    assert info.first_usable == "10.0.0.1"
    assert info.last_usable == "10.0.0.2"
    assert info.usable_host_count == 2
    assert info.total_addresses == 4


def test_ipv4_slash_31_is_point_to_point() -> None:
    info = calculate_subnet("10.0.0.0/31")

    assert info.special_case == "ipv4_point_to_point"
    assert info.broadcast_address is None
    assert info.first_usable == "10.0.0.0"
    assert info.last_usable == "10.0.0.1"
    assert info.usable_host_count == 2
    assert info.total_addresses == 2


def test_ipv4_slash_32_is_host_route() -> None:
    info = calculate_subnet("10.0.0.5/32")

    assert info.special_case == "ipv4_host_route"
    assert info.network_address == "10.0.0.5"
    assert info.broadcast_address is None
    assert info.first_usable == "10.0.0.5"
    assert info.last_usable == "10.0.0.5"
    assert info.usable_host_count == 1
    assert info.total_addresses == 1


def test_host_bits_are_normalized() -> None:
    info = calculate_subnet("10.0.0.5/24")

    assert str(info.network) == "10.0.0.0/24"
    assert info.network_address == "10.0.0.0"


def test_class_a_block_split_boundaries() -> None:
    parent = coerce_network("10.0.0.0/8")
    blocks = list(parent.subnets(new_prefix=12))

    assert len(blocks) == 16
    assert str(blocks[0]) == "10.0.0.0/12"
    assert str(blocks[-1]) == "10.240.0.0/12"
    last = calculate_subnet(blocks[-1])
    assert last.total_addresses == 2**20
    assert last.first_usable == "10.240.0.1"
    assert last.last_usable == "10.255.255.254"


def test_ipv6_slash_64() -> None:
    info = calculate_subnet("2001:db8::/64")

    assert info.version == 6
    assert info.prefix_length == 64
    assert info.netmask is None
    assert info.wildcard_mask is None
    assert info.broadcast_address is None
    assert info.network_address == "2001:db8::"
    assert info.last_address == "2001:db8::ffff:ffff:ffff:ffff"
    assert info.first_usable == "2001:db8::1"
    assert info.last_usable == "2001:db8::ffff:ffff:ffff:ffff"
    assert info.total_addresses == 2**64
    assert info.usable_host_count == 2**64 - 1
    assert info.special_case == ""


def test_ipv6_slash_127_is_point_to_point() -> None:
    info = calculate_subnet("2001:db8::/127")

    assert info.special_case == "ipv6_point_to_point"
    assert info.first_usable == "2001:db8::"
    assert info.last_usable == "2001:db8::1"
    assert info.usable_host_count == 2
    assert info.total_addresses == 2


def test_ipv6_slash_128_is_host_route() -> None:
    info = calculate_subnet("2001:db8::5/128")

    assert info.special_case == "ipv6_host_route"
    assert info.first_usable == "2001:db8::5"
    assert info.last_usable == "2001:db8::5"
    assert info.usable_host_count == 1
    assert info.total_addresses == 1


def test_invalid_network_raises() -> None:
    with pytest.raises(ValueError):
        calculate_subnet("not-an-ip/24")
