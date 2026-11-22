"""Deterministic IPv6 dual-stack planning: modeled design rules only.

This module is a *design model*. It carves IPv6 prefixes for a documented
IPv4 addressing plan; it does not configure equipment, run a protocol, or
simulate packets. Every rule below is an explicitly modeled planning rule.

Allocation rules
----------------
* The caller supplies one IPv6 block. Auto-assigned VLAN prefixes are exactly
  ``/64`` and are carved sequentially from the block, so they never overlap.
* Order is independent of caller list order: requests sort by
  ``(vlan_id is None, vlan_id, name, input index)``. Standalone subnets with no
  VLAN id therefore come last.
* An explicit ``ipv6_network`` for a request is kept as-is instead of being
  allocated from the cursor. It still counts toward utilization and is checked
  for size, containment, and overlap.
* IPv6 subnets already present in the addressing plan are treated as explicit
  assignments and are never re-allocated.

Scope classification (documented, from RFC 4291 / RFC 4193 / RFC 4861)
---------------------------------------------------------------------
``link_local`` ``fe80::/10`` is for one link only and is not a valid VLAN user
prefix. ``unique_local`` includes ``fc00::/7`` and the commonly used
``fd00::/8`` subset: private, not globally routable. ``global_unicast`` is
``2000::/3``. Anything else (unspecified, loopback, multicast, documentation,
or IPv4) is ``special``. Classification is reported as a typed finding and
never blocks the arithmetic.

Utilization rule
----------------
Utilization is ``prefixes_used / prefixes_available``, multiplied by 100 and
rounded to two decimals. It is deliberately **not** host utilization: an IPv6
``/64`` is never enumerated (``2**64`` addresses would be meaningless to
count). A block shorter than ``/64`` has zero available prefixes; a block that
has explicit assignments but zero capacity reports 100 percent.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from enum import Enum

from pydantic import BaseModel, Field

from config.limits import MAX_V6_PREFIXES
from core.exceptions import LimitsExceededError
from core.schemas.addressing import AddressingPlan, NetworkType
from core.schemas.validation import Finding, Severity
from network.addressing.cidr import IPNetwork

IPV6_VLAN_PREFIX_LENGTH = 64
_LINK_LOCAL = ipaddress.ip_network("fe80::/10")
_UNIQUE_LOCAL = ipaddress.ip_network("fc00::/7")
_GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")


class Ipv6Scope(str, Enum):
    """Documented address scope of one IPv6 prefix."""

    link_local = "link_local"
    unique_local = "unique_local"
    global_unicast = "global_unicast"
    special = "special"


def classify_ipv6_scope(value: str | IPNetwork) -> Ipv6Scope:
    """Classify a prefix as link-local, ULA, GUA, or special.

    ``fd00::/8`` is inside ULA ``fc00::/7`` and is therefore reported as
    ``unique_local``. IPv4 input is ``special``; :func:`validate_dual_stack`
    reports it as an error rather than silently accepting it.
    """
    network = ipaddress.ip_network(str(value), strict=False)
    if network.version != 6:
        return Ipv6Scope.special
    if network.subnet_of(_LINK_LOCAL):
        return Ipv6Scope.link_local
    if network.subnet_of(_UNIQUE_LOCAL):
        return Ipv6Scope.unique_local
    if network.subnet_of(_GLOBAL_UNICAST):
        return Ipv6Scope.global_unicast
    return Ipv6Scope.special


def available_prefixes(
    block: str | IPNetwork,
    prefix_length: int = IPV6_VLAN_PREFIX_LENGTH,
) -> int:
    """Return how many ``prefix_length`` prefixes fit in ``block``.

    Hand check: a ``/48`` contains ``2**(64-48) = 65536`` ``/64`` prefixes; a
    ``/64`` contains one; a ``/65`` contains zero because it is smaller than
    one ``/64``.
    """
    network = ipaddress.ip_network(str(block), strict=False)
    if network.version != 6 or prefix_length < 1 or prefix_length > 128:
        return 0
    if network.prefixlen > prefix_length:
        return 0
    return 1 << (prefix_length - network.prefixlen)


def prefix_at(
    block: str | IPNetwork,
    index: int,
    prefix_length: int = IPV6_VLAN_PREFIX_LENGTH,
) -> ipaddress.IPv6Network:
    """Return the ``index``-th ``prefix_length`` prefix of ``block``.

    Indices are zero-based. The value is computed from prefix arithmetic; no
    host or intermediate prefix is enumerated.
    """
    if index < 0:
        raise ValueError("Prefix index must be non-negative.")
    network = ipaddress.ip_network(str(block), strict=False)
    if network.version != 6:
        raise ValueError("IPv6 dual-stack block must be an IPv6 network.")
    capacity = available_prefixes(network, prefix_length)
    if index >= capacity:
        raise ValueError(
            f"Prefix index {index} is outside {network}, which holds {capacity} "
            f"/{prefix_length} prefix(es)."
        )
    offset = index * (1 << (128 - prefix_length))
    return ipaddress.ip_network(
        (int(network.network_address) + offset, prefix_length)
    )


class DualStackRequest(BaseModel):
    """One VLAN or standalone subnet that needs an IPv6 prefix."""

    name: str = Field(min_length=1, description="Subnet name from the IPv4 plan.")
    vlan_id: int | None = Field(
        default=None,
        ge=1,
        le=4094,
        description="VLAN id from the IPv4 plan, if the subnet is VLAN-tagged.",
    )
    ipv4_network: NetworkType | None = Field(
        default=None,
        description="IPv4 prefix this request is paired with.",
    )
    ipv6_network: NetworkType | None = Field(
        default=None,
        description="Optional explicit IPv6 prefix; otherwise one is carved.",
    )


class DualStackAssignment(BaseModel):
    """One modeled IPv4/IPv6 prefix pair."""

    name: str
    vlan_id: int | None = None
    index: int = Field(ge=0, description="Position in deterministic allocation order.")
    ipv4_network: str | None = None
    ipv6_network: str
    prefix_length: int
    scope: Ipv6Scope
    origin: str = Field(description="Either 'auto' or 'explicit'.")


class DualStackPlan(BaseModel):
    """The complete deterministic dual-stack design model."""

    block: str
    prefix_length: int
    assignments: tuple[DualStackAssignment, ...] = Field(default_factory=tuple)
    unallocated: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Requests that did not fit; reported, never silently dropped.",
    )
    prefixes_used: int = Field(ge=0)
    prefixes_available: int = Field(ge=0)
    utilization_percent: float = Field(ge=0.0, le=100.0)


def requests_from_plan(addressing: AddressingPlan) -> list[DualStackRequest]:
    """Build dual-stack requests from a core ``AddressingPlan``.

    Standalone subnets come first in the addressing plan, then VLAN plans in
    their stored order. :func:`plan_dual_stack` applies its own deterministic
    sort afterwards.
    """
    requests: list[DualStackRequest] = []
    for subnet in addressing.subnets:
        requests.append(
            DualStackRequest(
                name=subnet.name,
                vlan_id=subnet.vlan_id,
                ipv4_network=subnet.network if subnet.network.version == 4 else None,
                ipv6_network=subnet.network if subnet.network.version == 6 else None,
            )
        )
    for plan in addressing.vlan_plans:
        for subnet in plan.subnets:
            requests.append(
                DualStackRequest(
                    name=subnet.name,
                    vlan_id=subnet.vlan_id if subnet.vlan_id is not None else plan.vlan_id,
                    ipv4_network=subnet.network if subnet.network.version == 4 else None,
                    ipv6_network=subnet.network if subnet.network.version == 6 else None,
                )
            )
    return requests


def plan_dual_stack(
    block: str | IPNetwork,
    requests: Sequence[DualStackRequest],
    *,
    prefix_length: int = IPV6_VLAN_PREFIX_LENGTH,
) -> DualStackPlan:
    """Carve one ``prefix_length`` IPv6 prefix per request.

    The function never enumerates IPv6 hosts. Requests that cannot be placed
    are listed in ``unallocated`` and reported by
    :func:`validate_dual_stack`; no request is silently discarded.
    """
    network = ipaddress.ip_network(str(block), strict=False)
    if network.version != 6:
        raise ValueError("IPv6 dual-stack block must be an IPv6 network.")
    if not 1 <= prefix_length <= 128:
        raise ValueError(f"Invalid IPv6 prefix length: {prefix_length}")
    if len(requests) > MAX_V6_PREFIXES:
        raise LimitsExceededError(
            f"Dual-stack plan has {len(requests)} prefixes; the limit is "
            f"{MAX_V6_PREFIXES}"
        )

    names: set[str] = set()
    for request in requests:
        if request.name in names:
            raise ValueError(f"Duplicate dual-stack request name: {request.name!r}")
        names.add(request.name)

    indexed = list(enumerate(requests))
    indexed.sort(
        key=lambda item: (
            item[1].vlan_id is None,
            item[1].vlan_id or 0,
            item[1].name,
            item[0],
        )
    )

    capacity = available_prefixes(network, prefix_length)
    cursor = 0
    assignments: list[DualStackAssignment] = []
    unallocated: list[str] = []
    for order, (_, request) in enumerate(indexed):
        if request.ipv6_network is not None:
            assigned = str(request.ipv6_network)
            origin = "explicit"
        else:
            if cursor >= capacity:
                unallocated.append(request.name)
                continue
            assigned = str(prefix_at(network, cursor, prefix_length))
            cursor += 1
            origin = "auto"
        assignments.append(
            DualStackAssignment(
                name=request.name,
                vlan_id=request.vlan_id,
                index=order,
                ipv4_network=(
                    str(request.ipv4_network) if request.ipv4_network is not None else None
                ),
                ipv6_network=assigned,
                prefix_length=prefix_length,
                scope=classify_ipv6_scope(assigned),
                origin=origin,
            )
        )

    used = len(assignments)
    utilization = round(100.0 * used / capacity, 2) if capacity else (
        100.0 if used else 0.0
    )
    return DualStackPlan(
        block=str(network),
        prefix_length=prefix_length,
        assignments=tuple(assignments),
        unallocated=tuple(unallocated),
        prefixes_used=used,
        prefixes_available=capacity,
        utilization_percent=utilization,
    )


def _finding(
    severity: Severity,
    code: str,
    explanation: str,
    remediation: str,
    entities: Sequence[str],
) -> Finding:
    return Finding(
        severity=severity,
        code=code,
        affected_entities=list(entities),
        explanation=explanation,
        remediation=remediation,
    )


def validate_dual_stack(
    block: str | IPNetwork,
    plan: DualStackPlan,
    *,
    addressing: AddressingPlan | None = None,
) -> list[Finding]:
    """Return typed design-rule findings for one dual-stack plan."""
    findings: list[Finding] = []
    network = ipaddress.ip_network(str(block), strict=False)
    scope = classify_ipv6_scope(network)

    if network.version != 6:
        findings.append(
            _finding(
                Severity.error,
                "ipv6_block_not_ipv6",
                f"Dual-stack block {network} is IPv{network.version}, not IPv6.",
                "Supply an IPv6 block such as 2001:db8::/48 or fd00::/48.",
                [str(network)],
            )
        )
    elif scope is Ipv6Scope.link_local:
        findings.append(
            _finding(
                Severity.warning,
                "ipv6_scope_link_local",
                (
                    f"Block {network} is link-local (fe80::/10). Modeled design rule: "
                    "link-local prefixes are per-link only, not VLAN user prefixes."
                ),
                "Use a GUA (2000::/3) or ULA (fc00::/7) block instead.",
                [str(network)],
            )
        )
    elif scope is Ipv6Scope.unique_local:
        findings.append(
            _finding(
                Severity.info,
                "ipv6_scope_unique_local",
                (
                    f"Block {network} is ULA (fc00::/7, including fd00::/8): private "
                    "and not globally routable in the modeled design."
                ),
                "Use a GUA block if global reachability is part of the design.",
                [str(network)],
            )
        )
    elif scope is Ipv6Scope.special:
        findings.append(
            _finding(
                Severity.warning,
                "ipv6_scope_special",
                (
                    f"Block {network} is outside link-local, ULA, and GUA ranges. "
                    "Its modeled scope is 'special'."
                ),
                "Choose a documented GUA or ULA block for VLAN user prefixes.",
                [str(network)],
            )
        )

    if plan.prefix_length != IPV6_VLAN_PREFIX_LENGTH:
        findings.append(
            _finding(
                Severity.error,
                "ipv6_prefix_length_rule",
                (
                    f"Plan uses /{plan.prefix_length}; the modeled VLAN rule requires "
                    "/64 prefixes. This is a design rule, not protocol enforcement."
                ),
                "Set prefix_length to 64 for VLAN user subnets.",
                [plan.block],
            )
        )
    if plan.prefixes_available == 0 and network.version == 6:
        findings.append(
            _finding(
                Severity.error,
                "ipv6_block_too_small",
                (
                    f"Block {network} holds 2**({plan.prefix_length} - "
                    f"{network.prefixlen}) = 0 whole /{plan.prefix_length} prefixes."
                ),
                "Supply a block at least as large as the required prefix length.",
                [str(network)],
            )
        )
    if plan.unallocated:
        findings.append(
            _finding(
                Severity.error,
                "ipv6_block_exhausted",
                (
                    f"{len(plan.unallocated)} request(s) do not fit: "
                    f"{plan.prefixes_used} used of {plan.prefixes_available} available "
                    "/64 prefixes."
                    + " Names: " + ", ".join(plan.unallocated) + "."
                ),
                "Use a shorter parent block or reduce the number of VLANs.",
                list(plan.unallocated),
            )
        )

    assigned_networks: list[tuple[str, IPNetwork]] = []
    for assignment in plan.assignments:
        assigned = ipaddress.ip_network(assignment.ipv6_network, strict=False)
        if assigned.version != 6:
            findings.append(
                _finding(
                    Severity.error,
                    "ipv6_assignment_not_ipv6",
                    f"Assignment {assignment.name!r} has non-IPv6 prefix {assigned}.",
                    "Replace it with an IPv6 prefix.",
                    [assignment.name],
                )
            )
            continue
        if assigned.prefixlen != IPV6_VLAN_PREFIX_LENGTH:
            findings.append(
                _finding(
                    Severity.error,
                    "ipv6_prefix_length_violation",
                    (
                        f"Assignment {assignment.name!r} is /{assigned.prefixlen}; "
                        "each VLAN prefix must be /64."
                    ),
                    "Use an explicit /64 or let the planner carve one automatically.",
                    [assignment.name],
                )
            )
        if (
            network.version == 6
            and assigned.prefixlen >= network.prefixlen
            and not assigned.subnet_of(network)
        ):
            findings.append(
                _finding(
                    Severity.error,
                    "ipv6_prefix_outside_block",
                    (
                        f"Assignment {assignment.name!r} ({assigned}) lies outside "
                        f"the supplied block {network}."
                    ),
                    "Move the explicit prefix inside the block or change the block.",
                    [assignment.name, str(network)],
                )
            )
        assigned_networks.append((assignment.name, assigned))

    for index, (name_a, network_a) in enumerate(assigned_networks):
        for name_b, network_b in assigned_networks[index + 1 :]:
            if network_a.overlaps(network_b):
                findings.append(
                    _finding(
                        Severity.error,
                        "ipv6_prefix_overlap",
                        (
                            f"IPv6 prefixes for {name_a!r} ({network_a}) and "
                            f"{name_b!r} ({network_b}) overlap."
                        ),
                        "Give each VLAN a distinct /64 inside the block.",
                        [name_a, name_b],
                    )
                )

    if addressing is not None:
        expected: dict[str, int | None] = {}
        for subnet in addressing.subnets:
            if subnet.network.version == 4:
                expected[subnet.name] = subnet.vlan_id
        for vlan_plan in addressing.vlan_plans:
            for subnet in vlan_plan.subnets:
                if subnet.network.version == 4:
                    expected[subnet.name] = (
                        subnet.vlan_id
                        if subnet.vlan_id is not None
                        else vlan_plan.vlan_id
                    )
        actual = {assignment.name: assignment.vlan_id for assignment in plan.assignments}
        missing = sorted(set(expected) - set(actual))
        if missing:
            findings.append(
                _finding(
                    Severity.error,
                    "ipv6_missing_for_vlan",
                    (
                        f"{len(missing)} IPv4 VLAN/subnet(s) have no modeled IPv6 "
                        "prefix: " + ", ".join(missing) + "."
                    ),
                    "Add a dual-stack request for each IPv4 VLAN subnet.",
                    missing,
                )
            )
        mismatched = sorted(
            name
            for name in set(expected) & set(actual)
            if expected[name] != actual[name]
        )
        if mismatched:
            findings.append(
                _finding(
                    Severity.warning,
                    "ipv4_ipv6_plan_mismatch",
                    (
                        "IPv4 and IPv6 plans disagree for: "
                        + ", ".join(mismatched)
                        + ". VLAN ids must match for a dual-stack pairing."
                    ),
                    "Align the VLAN ids in both plans.",
                    mismatched,
                )
            )

    findings.sort(key=lambda item: (item.code, tuple(item.affected_entities)))
    return findings


def dual_stack_rows(plan: DualStackPlan) -> list[dict[str, object]]:
    """Return UI-agnostic rows for one dual-stack plan."""
    return [
        {
            "name": assignment.name,
            "vlan_id": assignment.vlan_id if assignment.vlan_id is not None else "",
            "ipv4_network": assignment.ipv4_network or "",
            "ipv6_network": assignment.ipv6_network,
            "prefix_length": assignment.prefix_length,
            "scope": assignment.scope.value,
            "origin": assignment.origin,
        }
        for assignment in plan.assignments
    ]


__all__ = [
    "IPV6_VLAN_PREFIX_LENGTH",
    "DualStackAssignment",
    "DualStackPlan",
    "DualStackRequest",
    "Ipv6Scope",
    "available_prefixes",
    "classify_ipv6_scope",
    "dual_stack_rows",
    "plan_dual_stack",
    "prefix_at",
    "requests_from_plan",
    "validate_dual_stack",
]
