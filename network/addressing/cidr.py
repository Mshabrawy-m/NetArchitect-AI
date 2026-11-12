"""Deterministic CIDR and subnet calculations.

All arithmetic is delegated to Python's standard-library :mod:`ipaddress`
module. No host enumeration is performed: counts and boundary addresses are
computed from prefix lengths, so an IPv6 ``/64`` costs the same as an IPv4
``/24``.

Special prefixes are handled explicitly and documented on
:class:`SubnetInfo`:

* IPv4 ``/31``: RFC 3021 point-to-point link, both addresses usable, no
  broadcast address.
* IPv4 ``/32``: single-host route, one usable address.
* IPv6 ``/127``: RFC 6164 point-to-point link, both addresses usable, no
  broadcast concept.
* IPv6 ``/128``: single-host route, one usable address.
* Other IPv6 prefixes: the first address is treated as the subnet-router
  anycast address (RFC 4291), so ``usable = total - 1``.
"""

from __future__ import annotations

import ipaddress

from pydantic import BaseModel, Field

from core.schemas.addressing import NetworkType

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def coerce_network(value: str | IPNetwork) -> IPNetwork:
    """Return an ``ipaddress`` network, accepting host bits in strings.

    ``strict=False`` is used so a host prefix such as ``10.0.0.5/24``
    normalises to ``10.0.0.0/24``. This mirrors the schema coercion rules.
    """
    return ipaddress.ip_network(str(value), strict=False)


def coerce_address(value: str | IPAddress) -> IPAddress:
    """Return an ``ipaddress`` address from a string or address object."""
    return ipaddress.ip_address(str(value))


class SubnetInfo(BaseModel):
    """Computed properties of one IPv4 or IPv6 subnet.

    ``total_addresses`` counts every address in the prefix. ``usable_host_count``
    follows the special-case rules above. For ordinary IPv4 prefixes the
    network and broadcast addresses are excluded; for ordinary IPv6 prefixes
    the subnet-router anycast address is excluded.
    """

    name: str = Field(default="", description="Optional human-readable name.")
    network: NetworkType = Field(description="The normalized network prefix.")
    version: int = Field(description="IP version (4 or 6).")
    prefix_length: int = Field(description="CIDR prefix length.")
    netmask: str | None = Field(
        default=None,
        description="Dotted netmask for IPv4, ``None`` for IPv6.",
    )
    wildcard_mask: str | None = Field(
        default=None,
        description="Inverse mask for IPv4, ``None`` for IPv6.",
    )
    network_address: str = Field(description="First address in the prefix.")
    last_address: str = Field(description="Last address in the prefix.")
    broadcast_address: str | None = Field(
        default=None,
        description="IPv4 broadcast address; ``None`` for IPv6 and /31, /32.",
    )
    first_usable: str | None = Field(
        default=None,
        description="First address usable by a host, if any.",
    )
    last_usable: str | None = Field(
        default=None,
        description="Last address usable by a host, if any.",
    )
    usable_host_count: int = Field(
        ge=0,
        description="Number of addresses usable by hosts under the rules above.",
    )
    total_addresses: int = Field(ge=1, description="Total addresses in the prefix.")
    special_case: str = Field(
        default="",
        description="Name of a special prefix rule, or an empty string.",
    )


def calculate_subnet(
    network: str | IPNetwork,
    *,
    name: str = "",
) -> SubnetInfo:
    """Return computed properties for ``network``.

    Host bits in a string are normalized (``10.0.0.5/24`` becomes
    ``10.0.0.0/24``). Invalid prefixes raise :class:`ValueError` from
    :mod:`ipaddress` and become a Pydantic validation error only when a value
    is stored in a model.
    """
    parsed = coerce_network(network)
    total = parsed.num_addresses
    first = parsed.network_address
    last = parsed.broadcast_address
    prefix = parsed.prefixlen
    special_case = ""
    broadcast: str | None = None
    first_usable: str | None
    last_usable: str | None
    usable: int

    if parsed.version == 4:
        netmask: str | None = str(parsed.netmask)
        wildcard: str | None = str(parsed.hostmask)
        if prefix == 32:
            special_case = "ipv4_host_route"
            first_usable = str(first)
            last_usable = str(last)
            usable = 1
        elif prefix == 31:
            special_case = "ipv4_point_to_point"
            first_usable = str(first)
            last_usable = str(last)
            usable = 2
        else:
            broadcast = str(last)
            first_usable = str(first + 1)
            last_usable = str(last - 1)
            usable = total - 2
    else:
        netmask = None
        wildcard = None
        if prefix == 128:
            special_case = "ipv6_host_route"
            first_usable = str(first)
            last_usable = str(last)
            usable = 1
        elif prefix == 127:
            special_case = "ipv6_point_to_point"
            first_usable = str(first)
            last_usable = str(last)
            usable = 2
        else:
            first_usable = str(first + 1)
            last_usable = str(last)
            usable = total - 1

    return SubnetInfo(
        name=name,
        network=parsed,
        version=parsed.version,
        prefix_length=prefix,
        netmask=netmask,
        wildcard_mask=wildcard,
        network_address=str(first),
        last_address=str(last),
        broadcast_address=broadcast,
        first_usable=first_usable,
        last_usable=last_usable,
        usable_host_count=usable,
        total_addresses=total,
        special_case=special_case,
    )
