"""Deterministic DHCP scope planning.

A scope reserves the subnet's infrastructure addresses (network/anycast and
gateway, plus the IPv4 broadcast address), validates any caller-supplied
static exclusions, and derives the first free contiguous pool when explicit
pool boundaries are omitted. Pools must fit inside the subnet's usable range
and may not include a reserved or excluded address.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from core.schemas.addressing import DhcpScope, Subnet
from core.schemas.validation import Finding, Severity
from network.addressing.cidr import (
    IPAddress,
    IPNetwork,
    calculate_subnet,
    coerce_address,
    coerce_network,
)

AddressLike = str | IPAddress
RangeLike = tuple[AddressLike, AddressLike]
DEFAULT_LEASE_MINUTES = 1440


class DhcpScopeRow(BaseModel):
    """One UI-agnostic DHCP scope row."""

    name: str
    network: str
    gateway: str
    pool_start: str
    pool_end: str
    pool_size: int
    excluded_ranges: str
    lease_minutes: int


def _same_version(first: IPAddress, second: IPAddress) -> bool:
    return first.version == second.version


def _merge_ranges(
    ranges: Sequence[tuple[IPAddress, IPAddress]],
) -> list[tuple[IPAddress, IPAddress]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: (item[0].version, int(item[0])))
    merged: list[tuple[IPAddress, IPAddress]] = []
    for start, end in ordered:
        if not merged:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        if not _same_version(previous_start, start):
            merged.append((start, end))
            continue
        if int(start) <= int(previous_end) + 1:
            if int(end) > int(previous_end):
                merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged


def _range_overlaps(
    first_start: IPAddress,
    first_end: IPAddress,
    second_start: IPAddress,
    second_end: IPAddress,
) -> bool:
    if not _same_version(first_start, second_start):
        return False
    return int(first_start) <= int(second_end) and int(second_start) <= int(first_end)


def _address_in_range(
    address: IPAddress,
    start: IPAddress,
    end: IPAddress,
) -> bool:
    return (
        _same_version(address, start)
        and int(start) <= int(address) <= int(end)
    )


def validate_dhcp_scope(scope: DhcpScope) -> list[Finding]:
    """Return findings for a scope's pool, gateway, and exclusions."""
    findings: list[Finding] = []
    network = scope.network
    start = scope.start_address
    end = scope.end_address

    if (start is None) != (end is None):
        findings.append(
            Finding(
                severity=Severity.error,
                code="dhcp_pool_incomplete",
                affected_entities=[scope.name],
                explanation="A DHCP pool needs both a start and an end address.",
                remediation="Provide both pool boundaries, or neither to derive one.",
            )
        )

    if start is not None and end is not None:
        if not _same_version(start, end):
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_pool_version_mismatch",
                    affected_entities=[scope.name],
                    explanation=f"Pool endpoints mix IP versions: {start} and {end}.",
                    remediation="Use addresses from the scope's IP version.",
                )
            )
        elif start > end:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_pool_inverted",
                    affected_entities=[scope.name],
                    explanation=f"Pool start {start} is after pool end {end}.",
                    remediation="Set the start address at or before the end address.",
                )
            )
        for bound in (start, end):
            if bound.version != network.version or bound not in network:
                findings.append(
                    Finding(
                        severity=Severity.error,
                        code="dhcp_pool_outside_subnet",
                        affected_entities=[scope.name],
                        explanation=f"Pool address {bound} is not inside {network}.",
                        remediation="Choose pool boundaries from the scope subnet.",
                    )
                )

        for excluded_start, excluded_end in scope.excluded_ranges:
            if _range_overlaps(start, end, excluded_start, excluded_end):
                findings.append(
                    Finding(
                        severity=Severity.error,
                        code="dhcp_pool_hits_excluded",
                        affected_entities=[scope.name],
                        explanation=(
                            f"Pool {start}-{end} includes the excluded range "
                            f"{excluded_start}-{excluded_end}."
                        ),
                        remediation=(
                            "Move the pool boundaries, or remove the exclusion if "
                            "the address is no longer reserved."
                        ),
                    )
                )

    if scope.gateway is not None:
        gateway = scope.gateway
        if gateway.version != network.version or gateway not in network:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_gateway_outside_subnet",
                    affected_entities=[scope.name],
                    explanation=f"Gateway {gateway} is not inside {network}.",
                    remediation="Use a gateway address from the scope subnet.",
                )
            )
        elif start is not None and end is not None and _address_in_range(
            gateway, start, end
        ):
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_gateway_in_pool",
                    affected_entities=[scope.name],
                    explanation=f"Gateway {gateway} is inside the DHCP pool.",
                    remediation="Exclude the gateway address from the pool.",
                )
            )

    for excluded_start, excluded_end in scope.excluded_ranges:
        if excluded_start.version != network.version:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_exclusion_version_mismatch",
                    affected_entities=[scope.name],
                    explanation=(
                        f"Exclusion {excluded_start}-{excluded_end} uses a different "
                        "IP version from the scope."
                    ),
                    remediation="Use exclusions from the scope's IP version.",
                )
            )
            continue
        if excluded_start not in network or excluded_end not in network:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_exclusion_outside_subnet",
                    affected_entities=[scope.name],
                    explanation=(
                        f"Excluded range {excluded_start}-{excluded_end} is not "
                        f"inside {network}."
                    ),
                    remediation="Restrict exclusions to the scope subnet.",
                )
            )
        if excluded_start > excluded_end:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="dhcp_exclusion_inverted",
                    affected_entities=[scope.name],
                    explanation=(
                        f"Excluded range start {excluded_start} is after "
                        f"{excluded_end}."
                    ),
                    remediation="Order each excluded range start before its end.",
                )
            )

    return findings


def _first_free_range(
    usable_start: IPAddress,
    usable_end: IPAddress,
    excluded: Sequence[tuple[IPAddress, IPAddress]],
) -> tuple[IPAddress, IPAddress] | None:
    cursor = int(usable_start)
    last = int(usable_end)
    for range_start, range_end in excluded:
        if not _same_version(range_start, usable_start):
            continue
        start = max(int(range_start), cursor)
        end = min(int(range_end), last)
        if end < cursor or start > last:
            continue
        if cursor < start:
            return (
                usable_start.__class__(cursor),
                usable_start.__class__(min(start - 1, last)),
            )
        cursor = max(cursor, end + 1)
        if cursor > last:
            return None
    if cursor <= last:
        return (usable_start.__class__(cursor), usable_start.__class__(last))
    return None


def plan_dhcp_scope(
    subnet: Subnet | str | IPNetwork,
    *,
    name: str | None = None,
    gateway: AddressLike | None = None,
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
    excluded_ranges: Sequence[RangeLike] = (),
    pool_start: AddressLike | None = None,
    pool_end: AddressLike | None = None,
) -> DhcpScope:
    """Build and validate a DHCP scope for ``subnet``.

    With no pool boundaries the first contiguous free range after the
    infrastructure addresses is used. Explicit boundaries must lie inside the
    subnet's usable range and must not touch a gateway or any exclusion.
    """
    if isinstance(subnet, Subnet):
        network = coerce_network(subnet.network)
        subnet_name = subnet.name
    else:
        network = coerce_network(subnet)
        subnet_name = str(network)

    if lease_minutes <= 0:
        raise ValueError(f"lease_minutes must be positive, got {lease_minutes}")

    info = calculate_subnet(network)
    if info.usable_host_count == 0 or info.first_usable is None:
        raise ValueError(f"Subnet {network} has no usable host addresses")
    usable_start = coerce_address(info.first_usable)
    usable_end = coerce_address(info.last_usable)

    if gateway is None:
        gateway_address = usable_start
    else:
        gateway_address = coerce_address(gateway)
    if (
        gateway_address.version != network.version
        or gateway_address not in network
        or not (usable_start <= gateway_address <= usable_end)
    ):
        raise ValueError(f"Gateway {gateway_address} is not a usable address in {network}")

    excluded: list[tuple[IPAddress, IPAddress]] = [
        (network.network_address, network.network_address),
        (gateway_address, gateway_address),
    ]
    if network.version == 4 and info.broadcast_address is not None:
        broadcast = coerce_address(info.broadcast_address)
        excluded.append((broadcast, broadcast))

    for range_start, range_end in excluded_ranges:
        start = coerce_address(range_start)
        end = coerce_address(range_end)
        if start.version != network.version or end.version != network.version:
            raise ValueError(
                f"Excluded range {start}-{end} must match IPv{network.version}"
            )
        if start not in network or end not in network:
            raise ValueError(f"Excluded range {start}-{end} is not inside {network}")
        if start > end:
            raise ValueError(f"Excluded range start {start} is after {end}")
        excluded.extend([(start, end)])

    merged = _merge_ranges(excluded)

    if (pool_start is None) != (pool_end is None):
        raise ValueError("Provide both pool_start and pool_end, or neither")

    if pool_start is not None and pool_end is not None:
        pool_first = coerce_address(pool_start)
        pool_last = coerce_address(pool_end)
        if pool_first.version != network.version or pool_last.version != network.version:
            raise ValueError(
                f"Pool {pool_first}-{pool_last} must match IPv{network.version}"
            )
        if pool_first not in network or pool_last not in network:
            raise ValueError(f"Pool {pool_first}-{pool_last} is not inside {network}")
        if pool_first > pool_last:
            raise ValueError(f"Pool start {pool_first} is after {pool_last}")
        if pool_first < usable_start or pool_last > usable_end:
            raise ValueError(
                f"Pool {pool_first}-{pool_last} is outside the usable range "
                f"{usable_start}-{usable_end}"
            )
        for range_start, range_end in merged:
            if _range_overlaps(pool_first, pool_last, range_start, range_end):
                raise ValueError(
                    f"Pool {pool_first}-{pool_last} includes the reserved range "
                    f"{range_start}-{range_end}"
                )
    else:
        pool = _first_free_range(usable_start, usable_end, merged)
        if pool is None:
            raise ValueError(
                f"No DHCP pool is available in {network} after reserving "
                "network, gateway, and excluded addresses"
            )
        pool_first, pool_last = pool

    scope = DhcpScope(
        name=name or f"{subnet_name} DHCP",
        network=network,
        gateway=gateway_address,
        start_address=pool_first,
        end_address=pool_last,
        lease_minutes=lease_minutes,
        excluded_ranges=merged,
    )
    findings = validate_dhcp_scope(scope)
    errors = [finding for finding in findings if finding.severity is Severity.error]
    if errors:
        raise ValueError(errors[0].explanation)
    return scope


def plan_dhcp_scopes(
    subnets: Sequence[Subnet],
    *,
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> list[DhcpScope]:
    """Build a default scope for each subnet in input order."""
    return [
        plan_dhcp_scope(subnet, lease_minutes=lease_minutes) for subnet in subnets
    ]


def dhcp_scope_rows(scopes: Sequence[DhcpScope]) -> list[dict[str, object]]:
    """Return UI-agnostic rows for DHCP scopes."""
    rows: list[dict[str, object]] = []
    for scope in scopes:
        start = scope.start_address
        end = scope.end_address
        pool_size = int(end) - int(start) + 1 if start is not None and end is not None else 0
        excluded = "; ".join(
            f"{range_start}-{range_end}"
            for range_start, range_end in scope.excluded_ranges
        )
        rows.append(
            {
                "name": scope.name,
                "network": str(scope.network),
                "gateway": str(scope.gateway) if scope.gateway is not None else "",
                "pool_start": str(start) if start is not None else "",
                "pool_end": str(end) if end is not None else "",
                "pool_size": pool_size,
                "excluded_ranges": excluded,
                "lease_minutes": scope.lease_minutes,
            }
        )
    return rows
