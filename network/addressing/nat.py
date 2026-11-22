"""NAT/PAT design model: modeled rules only, no packet simulation.

This module sizes a designer-supplied NAT plan using prefix arithmetic and
explicit, documented assumptions. It does not configure a device, translate a
packet, or inspect traffic. Every finding is a *modeled design rule* result.

Host-count model
----------------
``NatRule.inside_hosts`` is the modeled number of inside hosts that need
translation. When it is omitted, the count is derived from IPv4 inside
subnets: ``2`` for ``/31`` (RFC 3021), ``1`` for ``/32``, and
``num_addresses - 2`` otherwise (network and broadcast withheld). No IPv6 host
is ever enumerated.

Pool model
----------
A NAT pool is a set of outside IPv4 or IPv6 prefixes. Every address in a pool
prefix is modeled as a usable translated address; unlike a LAN subnet, a NAT
pool has no network or broadcast address. ``static`` and ``dynamic_pool``
require one outside address per inside host. ``pat_overload`` allows many
sessions per outside address:

    required_sessions = inside_hosts * sessions_per_host
    session_capacity  = pool_addresses * usable_ports_per_address

``usable_ports_per_address`` defaults to ``65535 - 1024 + 1 = 64512``: the
documented assumption is source ports 1024..65535 for TCP and UDP, with one
session per port. It is a parameter on each rule so a designer can model a
different port budget; the formula and the selected value are always shown in
the finding text.

Findings
--------
* ``nat_pool_too_small`` - static/dynamic pool address count below host count.
* ``nat_pat_port_capacity_exceeded`` - modeled sessions above port capacity.
* ``nat_overlapping_translations`` - two rules share an inside or outside prefix.
* ``nat_private_space_outside`` - an outside pool uses RFC 1918 or ULA space.
* ``nat_empty_pool``, ``nat_no_inside_subnets``, ``nat_unknown_type`` -
  incomplete or unsupported rule definitions.
"""

from __future__ import annotations

import ipaddress
from enum import Enum

from pydantic import BaseModel, Field

from config.limits import MAX_NAT_RULES
from core.exceptions import LimitsExceededError
from core.schemas.addressing import NetworkType
from core.schemas.validation import Finding, Severity

DEFAULT_USABLE_PORTS_PER_ADDRESS = 65535 - 1024 + 1  # hand: 64,512
DEFAULT_SESSIONS_PER_HOST = 1

_PRIVATE_V4 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_PRIVATE_V6 = ipaddress.ip_network("fc00::/7")


class NatType(str, Enum):
    """The three modeled translation styles."""

    static = "static"
    dynamic_pool = "dynamic_pool"
    pat_overload = "pat_overload"


class NatRule(BaseModel):
    """One designer-supplied translation rule."""

    id: str = Field(min_length=1, description="Stable rule identifier.")
    name: str = Field(min_length=1, description="Human-readable rule label.")
    nat_type: NatType = Field(description="Modeled translation style.")
    inside_zone: str = Field(
        min_length=1,
        description="Name of the modeled inside zone this rule serves.",
    )
    inside_subnets: tuple[NetworkType, ...] = Field(
        default_factory=tuple,
        description="Inside prefixes whose hosts need translation.",
    )
    outside_pools: tuple[NetworkType, ...] = Field(
        default_factory=tuple,
        description="Outside prefixes supplying translated addresses.",
    )
    inside_hosts: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Modeled host count; when omitted it is derived from IPv4 inside "
            "subnets as documented in this module."
        ),
    )
    sessions_per_host: int = Field(
        default=DEFAULT_SESSIONS_PER_HOST,
        ge=0,
        description="Modeled concurrent sessions per inside host (PAT only).",
    )
    usable_ports_per_address: int = Field(
        default=DEFAULT_USABLE_PORTS_PER_ADDRESS,
        ge=0,
        description="Documented source-port budget per outside address (PAT only).",
    )


class NatPlan(BaseModel):
    """A bounded set of modeled NAT/PAT rules."""

    rules: tuple[NatRule, ...] = Field(default_factory=tuple)


class NatSizing(BaseModel):
    """Computed, hand-checkable sizing for one rule."""

    rule_id: str
    nat_type: str = Field(description="Modeled type value, including unknown values.")
    inside_hosts: int = Field(ge=0)
    pool_addresses: int = Field(ge=0)
    required_addresses: int = Field(ge=0)
    required_sessions: int = Field(ge=0)
    session_capacity: int = Field(ge=0)
    usable_ports_per_address: int = Field(ge=0)


class NatAnalysis(BaseModel):
    """The complete deterministic result of one NAT plan review."""

    sizings: tuple[NatSizing, ...] = Field(default_factory=tuple)
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    assumptions: tuple[str, ...] = Field(default_factory=tuple)


def derived_host_count(rule: NatRule) -> int:
    """Return the documented host count for ``rule``."""
    if rule.inside_hosts is not None:
        return rule.inside_hosts
    total = 0
    for subnet in rule.inside_subnets:
        if subnet.version != 4:
            continue
        prefixlen = subnet.prefixlen
        if prefixlen == 32:
            total += 1
        elif prefixlen == 31:
            total += 2
        else:
            total += max(subnet.num_addresses - 2, 0)
    return total


def _pool_addresses(rule: NatRule) -> int:
    # Every address in a NAT pool prefix is modeled as usable; no network or
    # broadcast address is withheld (unlike a LAN subnet).
    return sum(pool.num_addresses for pool in rule.outside_pools)


def _finding(
    severity: Severity,
    code: str,
    explanation: str,
    remediation: str,
    entities: list[str],
) -> Finding:
    return Finding(
        severity=severity,
        code=code,
        affected_entities=entities,
        explanation=explanation,
        remediation=remediation,
    )


def _private_outside(pool: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    network = pool
    if network.version == 4:
        return any(network.subnet_of(prefix) for prefix in _PRIVATE_V4)
    if network.version == 6:
        return network.subnet_of(_PRIVATE_V6)
    return False


def analyze_nat_plan(plan: NatPlan) -> NatAnalysis:
    """Size and check every rule in ``plan`` without simulating traffic."""
    if len(plan.rules) > MAX_NAT_RULES:
        raise LimitsExceededError(
            f"NAT plan has {len(plan.rules)} rules; the limit is {MAX_NAT_RULES}"
        )

    findings: list[Finding] = []
    sizings: list[NatSizing] = []
    seen_ids: set[str] = set()

    inside_owner: dict[str, str] = {}
    outside_owner: dict[str, str] = {}
    for rule in plan.rules:
        if rule.id in seen_ids:
            findings.append(
                _finding(
                    Severity.error,
                    "nat_duplicate_rule_id",
                    f"NAT rule id {rule.id!r} is used more than once.",
                    "Give every rule a unique id.",
                    [rule.id],
                )
            )
        seen_ids.add(rule.id)

        hosts = derived_host_count(rule)
        addresses = _pool_addresses(rule)
        is_pat = rule.nat_type is NatType.pat_overload
        required_addresses = 0 if is_pat else hosts
        required_sessions = hosts * rule.sessions_per_host if is_pat else 0
        capacity = addresses * rule.usable_ports_per_address if is_pat else 0
        sizings.append(
            NatSizing(
                rule_id=rule.id,
                nat_type=(
                    rule.nat_type.value
                    if isinstance(rule.nat_type, NatType)
                    else str(rule.nat_type)
                ),
                inside_hosts=hosts,
                pool_addresses=addresses,
                required_addresses=required_addresses,
                required_sessions=required_sessions,
                session_capacity=capacity,
                usable_ports_per_address=rule.usable_ports_per_address,
            )
        )

        if not rule.inside_subnets:
            findings.append(
                _finding(
                    Severity.error,
                    "nat_no_inside_subnets",
                    f"Rule {rule.id!r} names no inside subnets.",
                    "Add at least one inside prefix or an explicit inside_hosts count.",
                    [rule.id],
                )
            )
        if not rule.outside_pools:
            findings.append(
                _finding(
                    Severity.error,
                    "nat_empty_pool",
                    f"Rule {rule.id!r} has no outside pool addresses.",
                    "Add at least one outside prefix.",
                    [rule.id],
                )
            )

        if rule.nat_type is NatType.static or rule.nat_type is NatType.dynamic_pool:
            if addresses < required_addresses:
                findings.append(
                    _finding(
                        Severity.error,
                        "nat_pool_too_small",
                        (
                            f"Rule {rule.id!r} ({rule.nat_type.value}) models "
                            f"{required_addresses} required outside address(es) for "
                            f"{hosts} inside host(s), but its pools hold only "
                            f"{addresses}. Shortfall: "
                            f"{required_addresses - addresses}."
                        ),
                        "Enlarge the outside pool or reduce the inside host count.",
                        [rule.id],
                    )
                )
        elif is_pat:
            if required_sessions > capacity:
                findings.append(
                    _finding(
                        Severity.error,
                        "nat_pat_port_capacity_exceeded",
                        (
                            f"Rule {rule.id!r} needs {required_sessions} modeled "
                            f"sessions ({hosts} hosts x {rule.sessions_per_host} "
                            f"sessions/host) but its {addresses} outside address(es) "
                            f"hold {capacity} sessions. Formula: "
                            f"{addresses} x {rule.usable_ports_per_address} = "
                            f"{capacity}; assumption: ports 1024..65535 give 64512 "
                            "ports per address by default. Overload: "
                            f"{required_sessions - capacity} session(s)."
                        ),
                        "Add outside addresses, lower sessions_per_host, or document "
                        "a larger usable_ports_per_address.",
                        [rule.id],
                    )
                )
        else:
            findings.append(
                _finding(
                    Severity.error,
                    "nat_unknown_type",
                    f"Rule {rule.id!r} has unsupported NAT type {rule.nat_type!r}.",
                    "Use static, dynamic_pool, or pat_overload.",
                    [rule.id],
                )
            )

        for subnet in rule.inside_subnets:
            key = str(subnet)
            if key in inside_owner and inside_owner[key] != rule.id:
                findings.append(
                    _finding(
                        Severity.error,
                        "nat_overlapping_translations",
                        (
                            f"Inside prefix {key} is shared by rules "
                            f"{inside_owner[key]!r} and {rule.id!r}."
                        ),
                        "Give each rule a distinct inside zone or subnet.",
                        [inside_owner[key], rule.id, key],
                    )
                )
            inside_owner[key] = rule.id
        for pool in rule.outside_pools:
            key = str(pool)
            if key in outside_owner and outside_owner[key] != rule.id:
                findings.append(
                    _finding(
                        Severity.error,
                        "nat_overlapping_translations",
                        (
                            f"Outside pool {key} is shared by rules "
                            f"{outside_owner[key]!r} and {rule.id!r}."
                        ),
                        "Allocate disjoint outside pools per rule.",
                        [outside_owner[key], rule.id, key],
                    )
                )
            outside_owner[key] = rule.id
            if _private_outside(pool):
                findings.append(
                    _finding(
                        Severity.error,
                        "nat_private_space_outside",
                        (
                            f"Rule {rule.id!r} uses private {pool.version} space "
                            f"{key} as an outside pool (RFC 1918 or ULA). The modeled "
                            "design leaks private space toward the outside."
                        ),
                        "Use globally routable outside addresses, or document the "
                        "pool as an internal-only translation domain.",
                        [rule.id, key],
                    )
                )

    findings.sort(key=lambda item: (item.code, tuple(item.affected_entities)))
    assumptions = (
        "Modeled design rules only: no packet behavior is simulated.",
        "Ports 1024..65535 => 64512 usable source ports per outside address by default.",
        "One modeled concurrent session per inside host by default.",
        "All addresses in an outside prefix are usable pool addresses.",
        (
            "Inside host count is explicit or derived from IPv4 prefixes "
            "(2 for /31, 1 for /32, num_addresses - 2 otherwise)."
        ),
    )
    return NatAnalysis(
        sizings=tuple(sizings),
        findings=tuple(findings),
        assumptions=assumptions,
    )


__all__ = [
    "DEFAULT_SESSIONS_PER_HOST",
    "DEFAULT_USABLE_PORTS_PER_ADDRESS",
    "NatAnalysis",
    "NatPlan",
    "NatRule",
    "NatSizing",
    "NatType",
    "analyze_nat_plan",
    "derived_host_count",
]
