"""IP addressing domain models.

Defines reusable ``NetworkType`` and ``AddressType`` aliases (used here and
imported by :mod:`core.schemas.routing`) plus the subnet, VLAN, and DHCP
scope models. Overlap and uniqueness invariants are enforced at the model
level so that an invalid plan can never be constructed.
"""

import ipaddress
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, model_validator


def _coerce_network(value: object) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Coerce a string or network-like value to an IP network.

    Host bits are accepted (``strict=False``) so a host prefix such as
    ``10.0.0.5/24`` normalises to ``10.0.0.0/24``.
    """
    return ipaddress.ip_network(str(value), strict=False)


def _coerce_address(value: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Coerce a string or address-like value to an IP address."""
    return ipaddress.ip_address(str(value))


# A network prefix for either IPv4 or IPv6. Accepts strings and normalises host bits.
NetworkType = Annotated[
    ipaddress.IPv4Network | ipaddress.IPv6Network,
    BeforeValidator(_coerce_network),
]

# A single IP address for either IPv4 or IPv6, accepting string input.
AddressType = Annotated[
    ipaddress.IPv4Address | ipaddress.IPv6Address,
    BeforeValidator(_coerce_address),
]


class Subnet(BaseModel):
    """An IP subnet, optionally tagged with a VLAN id and a description."""

    name: str = Field(description="Human-readable subnet name.")
    network: NetworkType = Field(description="IP network prefix (IPv4 or IPv6).")
    vlan_id: int | None = Field(
        default=None,
        description="Optional VLAN id (1-4094) this subnet belongs to.",
        ge=1,
        le=4094,
    )
    description: str = Field(
        default="",
        description="Free-form description of the subnet's purpose.",
    )


class VlanPlan(BaseModel):
    """A VLAN plan: a VLAN id plus the subnets assigned to it.

    Subnets within a plan must not overlap and must have unique names.
    """

    vlan_id: int = Field(
        description="VLAN id (1-4094) this plan defines.",
        ge=1,
        le=4094,
    )
    name: str = Field(description="Human-readable VLAN name.")
    subnets: list[Subnet] = Field(
        default_factory=list,
        description="Subnets assigned to this VLAN.",
    )
    purpose: str = Field(
        default="",
        description="Free-form purpose for the VLAN.",
    )

    @model_validator(mode="after")
    def _reject_overlaps_and_duplicate_names(self) -> "VlanPlan":
        """Reject overlapping subnets and duplicate subnet names within the plan."""
        subnets = self.subnets
        names: set[str] = set()
        for index, subnet_a in enumerate(subnets):
            if subnet_a.name in names:
                raise ValueError(
                    f"Duplicate subnet name in VLAN plan: {subnet_a.name!r}"
                )
            names.add(subnet_a.name)
            for subnet_b in subnets[index + 1:]:
                if subnet_a.network.overlaps(subnet_b.network):
                    raise ValueError(
                        f"Overlapping subnets in VLAN plan: "
                        f"{subnet_a.network} and {subnet_b.network}"
                    )
        return self


class DhcpScope(BaseModel):
    """A DHCP scope: an address pool with optional gateway and excluded ranges.

    When both ``start_address`` and ``end_address`` are present they must
    form a valid inclusive range (``start <= end``) and both must lie within
    ``network``.
    """

    name: str = Field(description="Human-readable DHCP scope name.")
    network: NetworkType = Field(description="IP network the scope draws addresses from.")
    gateway: AddressType | None = Field(
        default=None,
        description="Optional default gateway for the scope.",
    )
    start_address: AddressType | None = Field(
        default=None,
        description="Optional first address handed out by the scope.",
    )
    end_address: AddressType | None = Field(
        default=None,
        description="Optional last address handed out by the scope.",
    )
    lease_minutes: int = Field(
        default=1440,
        description="Lease duration in minutes (must be > 0).",
        gt=0,
    )
    excluded_ranges: list[tuple[AddressType, AddressType]] = Field(
        default_factory=list,
        description="Address ranges excluded from allocation.",
    )

    @model_validator(mode="after")
    def _validate_address_range(self) -> "DhcpScope":
        """Ensure start/end lie within the network and start <= end."""
        start = self.start_address
        end = self.end_address
        if start is not None and end is not None:
            if start not in self.network:
                raise ValueError(
                    f"DhcpScope start_address {start} is not within network {self.network}"
                )
            if end not in self.network:
                raise ValueError(
                    f"DhcpScope end_address {end} is not within network {self.network}"
                )
            if start > end:
                raise ValueError(
                    f"DhcpScope start_address {start} must be <= end_address {end}"
                )
        return self


class AddressingPlan(BaseModel):
    """A complete addressing plan: VLAN plans plus standalone subnets.

    Every subnet (across all VLAN plans and the standalone list) is flattened
    and checked: no two may overlap, and names must be unique across the plan.
    """

    vlan_plans: list[VlanPlan] = Field(
        default_factory=list,
        description="VLAN plans composing the addressing plan.",
    )
    subnets: list[Subnet] = Field(
        default_factory=list,
        description="Standalone subnets not assigned to a VLAN.",
    )

    @model_validator(mode="after")
    def _reject_overlaps_and_duplicate_names(self) -> "AddressingPlan":
        """Reject pairwise overlap and duplicate names across the whole plan."""
        all_subnets = list(self.subnets)
        for plan in self.vlan_plans:
            all_subnets.extend(plan.subnets)

        names: set[str] = set()
        for index, subnet_a in enumerate(all_subnets):
            if subnet_a.name in names:
                raise ValueError(
                    f"Duplicate subnet name in addressing plan: {subnet_a.name!r}"
                )
            names.add(subnet_a.name)
            for subnet_b in all_subnets[index + 1:]:
                if subnet_a.network.overlaps(subnet_b.network):
                    raise ValueError(
                        f"Overlapping subnets in addressing plan: "
                        f"{subnet_a.network} and {subnet_b.network}"
                    )
        return self
