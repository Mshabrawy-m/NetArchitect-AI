"""Deterministic VLSM (variable-length subnet mask) allocation.

The allocator sorts requirements largest-first, then assigns each one the
smallest prefix that fits the requested hosts plus reserved addresses. Blocks
are carved sequentially from the parent, so allocations never overlap and
always lie inside the parent. Ties keep the caller's input order, which makes
the result deterministic.

Reserved addresses
------------------
``reserved_addresses`` is the number of addresses withheld from host
assignment in every allocated block. It defaults to 3 for IPv4 (network,
broadcast, gateway) and 2 for IPv6 (subnet-router anycast, gateway). The
minimum is 2 for IPv4 and 1 for IPv6; larger values reserve additional
addresses at the start of the block.

The allocator intentionally stops at ``/30`` for IPv4 and ``/126`` for IPv6,
because a host subnet needs at least a network/anycast address, a gateway, and
one assignable address. Point-to-point prefixes (``/31``, ``/32``, ``/127``,
``/128``) are supported by :mod:`network.addressing.cidr` but are not produced
by the VLSM allocator.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from config.limits import MAX_HOSTS_PER_SUBNET, MAX_SUBNETS
from core.exceptions import InsufficientAddressSpaceError, LimitsExceededError
from core.schemas.addressing import AddressType, NetworkType
from network.addressing.cidr import IPNetwork, coerce_network

_MAX_PREFIX = {4: 32, 6: 128}
_MAX_VLSM_PREFIX = {4: 30, 6: 126}
_DEFAULT_RESERVED = {4: 3, 6: 2}
_MIN_RESERVED = {4: 2, 6: 1}


class VlsmRequirement(BaseModel):
    """One named request for a subnet with at least ``required_hosts``."""

    name: str = Field(min_length=1, description="Unique requirement name.")
    required_hosts: int = Field(
        ge=0,
        description="Host addresses requested, excluding reserved addresses.",
    )


class VlsmAllocation(BaseModel):
    """One allocated block, including its reserved and host ranges."""

    name: str
    request_index: int = Field(ge=0, description="Original input order index.")
    required_hosts: int = Field(ge=0)
    network: NetworkType
    prefix_length: int
    netmask: str | None = None
    total_addresses: int = Field(ge=1)
    reserved_addresses: int = Field(ge=0)
    gateway: AddressType | None = None
    first_host: AddressType | None = None
    last_host: AddressType | None = None
    host_capacity: int = Field(ge=0)


class VlsmResult(BaseModel):
    """The complete result of one VLSM allocation."""

    parent: NetworkType
    reserved_addresses: int = Field(ge=0)
    allocations: list[VlsmAllocation] = Field(default_factory=list)
    allocated_addresses: int = Field(default=0, ge=0)
    remaining_addresses: int = Field(default=0, ge=0)


def default_reserved_addresses(version: int) -> int:
    """Return the default reserved-address count for an IP version."""
    if version not in _DEFAULT_RESERVED:
        raise ValueError(f"Unsupported IP version: {version}")
    return _DEFAULT_RESERVED[version]


def _validate_reserved(version: int, reserved_addresses: int) -> None:
    minimum = _MIN_RESERVED[version]
    if reserved_addresses < minimum:
        raise ValueError(
            f"reserved_addresses must be at least {minimum} for IPv{version}, "
            f"got {reserved_addresses}"
        )
    if reserved_addresses > MAX_HOSTS_PER_SUBNET:
        raise LimitsExceededError(
            f"reserved_addresses {reserved_addresses} exceeds the limit of "
            f"{MAX_HOSTS_PER_SUBNET}"
        )


def _needed_prefix(
    parent: IPNetwork,
    required_hosts: int,
    reserved_addresses: int,
) -> int | None:
    """Return the smallest permitted prefix that fits the request."""
    needed = max(required_hosts, 1) + reserved_addresses
    version = parent.version
    for prefix in range(_MAX_VLSM_PREFIX[version], parent.prefixlen - 1, -1):
        if 2 ** (_MAX_PREFIX[version] - prefix) >= needed:
            return prefix
    return None


def _allocation(
    network: IPNetwork,
    *,
    request: VlsmRequirement,
    request_index: int,
    reserved_addresses: int,
) -> VlsmAllocation:
    version = network.version
    offset = reserved_addresses - 1 if version == 4 else reserved_addresses
    first_host = network.network_address + offset
    last_host = network.broadcast_address - (1 if version == 4 else 0)
    gateway = network.network_address + 1
    capacity = network.num_addresses - reserved_addresses
    if capacity < 1 or first_host > last_host:
        raise InsufficientAddressSpaceError(
            f"Subnet {network} has no assignable addresses after reserving "
            f"{reserved_addresses}; requested by {request.name!r}"
        )
    return VlsmAllocation(
        name=request.name,
        request_index=request_index,
        required_hosts=request.required_hosts,
        network=network,
        prefix_length=network.prefixlen,
        netmask=str(network.netmask) if version == 4 else None,
        total_addresses=network.num_addresses,
        reserved_addresses=reserved_addresses,
        gateway=gateway,
        first_host=first_host,
        last_host=last_host,
        host_capacity=capacity,
    )


def allocate_vlsm(
    parent: str | IPNetwork,
    requirements: Sequence[VlsmRequirement],
    *,
    reserved_addresses: int | None = None,
) -> VlsmResult:
    """Allocate every requirement inside ``parent``.

    Requirements are processed largest-first. If any requirement cannot be
    placed, :class:`~core.exceptions.InsufficientAddressSpaceError` is raised
    and its message lists every requirement that could not be allocated. No
    partial result is returned and no request is silently truncated.
    """
    parent_network = coerce_network(parent)
    version = parent_network.version
    reserved = (
        default_reserved_addresses(version)
        if reserved_addresses is None
        else reserved_addresses
    )
    _validate_reserved(version, reserved)

    if len(requirements) > MAX_SUBNETS:
        raise LimitsExceededError(
            f"VLSM plan has {len(requirements)} requirements; the limit is "
            f"{MAX_SUBNETS}"
        )

    names: set[str] = set()
    for requirement in requirements:
        if requirement.name in names:
            raise ValueError(f"Duplicate VLSM requirement name: {requirement.name!r}")
        names.add(requirement.name)
        if requirement.required_hosts + reserved > MAX_HOSTS_PER_SUBNET:
            raise LimitsExceededError(
                f"Requirement {requirement.name!r} requests "
                f"{requirement.required_hosts} hosts plus {reserved} reserved; "
                f"the limit is {MAX_HOSTS_PER_SUBNET} per subnet"
            )

    indexed = list(enumerate(requirements))
    indexed.sort(key=lambda item: (-item[1].required_hosts, item[0]))

    failures: list[str] = []
    prefixes: dict[int, int] = {}
    for index, requirement in indexed:
        prefix = _needed_prefix(parent_network, requirement.required_hosts, reserved)
        if prefix is None:
            failures.append(
                f"{requirement.name!r} needs {requirement.required_hosts} hosts "
                f"(with {reserved} reserved), which does not fit in "
                f"{parent_network} at /{_MAX_VLSM_PREFIX[version]} or larger"
            )
        else:
            prefixes[index] = prefix
    if failures:
        raise InsufficientAddressSpaceError(
            "VLSM allocation failed; could not allocate: " + "; ".join(failures)
        )

    cursor = int(parent_network.network_address)
    parent_end = int(parent_network.broadcast_address)
    allocations: list[VlsmAllocation] = []

    for position, (index, requirement) in enumerate(indexed):
        prefix = prefixes[index]
        size = 2 ** (_MAX_PREFIX[version] - prefix)
        if cursor + size - 1 > parent_end:
            unallocated = [
                f"{pending.name!r} ({pending.required_hosts} hosts)"
                for _, pending in indexed[position:]
            ]
            raise InsufficientAddressSpaceError(
                f"VLSM allocation failed in {parent_network}; "
                f"{size} addresses remain short. Could not allocate: "
                + ", ".join(unallocated)
            )
        start = parent_network.network_address.__class__(cursor)
        network = coerce_network(f"{start}/{prefix}")
        allocations.append(
            _allocation(
                network,
                request=requirement,
                request_index=index,
                reserved_addresses=reserved,
            )
        )
        cursor += size

    allocated = sum(allocation.total_addresses for allocation in allocations)
    return VlsmResult(
        parent=parent_network,
        reserved_addresses=reserved,
        allocations=allocations,
        allocated_addresses=allocated,
        remaining_addresses=parent_network.num_addresses - allocated,
    )
