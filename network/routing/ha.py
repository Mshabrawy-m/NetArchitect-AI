"""First-hop gateway redundancy design model: VRRP/HSRP-style, modeled only.

This module models *design annotations*. It elects an active member from
documented priorities, checks the group definition, and reports findings. It
does not send advertisements, run VRRP/HSRP, or simulate packet forwarding.

Election model
--------------
The active member is the live member with the highest priority; an exact tie
is broken by the lexicographically lowest device id. ``preempt`` is recorded
as design metadata and reported, but no preemption behavior is simulated. A
designer may model a higher-priority member as failed through twin device
state; the evaluator's optional first-hop failover view then records the
before/after active member.

Attachment model
----------------
Topology devices have no interface-level VLAN field, so each member records
its modeled ``vlan_ids``. A group binding is checked against those annotations
and, when supplied, against the VLAN plan. Shared fate is derived from the
physical graph: if every member has exactly one non-member neighbor and all
members name the same neighbor, the group is flagged as behind one uplink.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from config.limits import MAX_HA_GROUPS, MAX_HA_MEMBERS
from core.exceptions import LimitsExceededError
from core.schemas.addressing import AddressType, NetworkType
from core.schemas.network import Topology
from core.schemas.validation import Finding, Severity
from network.vlan.plan import VlanPlanResult


class HaMember(BaseModel):
    """One modeled member of a first-hop redundancy group."""

    device_id: str = Field(min_length=1, description="Device id in the twin topology.")
    priority: int = Field(
        default=100,
        ge=0,
        le=255,
        description="Modeled election priority (higher wins).",
    )
    vlan_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        description="VLAN ids the member is modeled as attached to.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_vlans(cls, data: object) -> object:
        if isinstance(data, dict) and "vlan_ids" in data:
            return {**data, "vlan_ids": tuple(sorted(set(data["vlan_ids"])))}
        return data


class HaGroup(BaseModel):
    """One VRRP/HSRP-style gateway group design annotation."""

    id: str = Field(min_length=1, description="Stable group identifier.")
    name: str = Field(min_length=1, description="Human-readable group label.")
    virtual_ip: AddressType = Field(description="Modeled virtual IP (VIP).")
    subnet: NetworkType = Field(description="IPv4 or IPv6 subnet the VIP belongs to.")
    vlan_id: int | None = Field(
        default=None,
        ge=1,
        le=4094,
        description="VLAN this first-hop group is bound to, if any.",
    )
    members: tuple[HaMember, ...] = Field(default_factory=tuple)
    preempt: bool = Field(
        default=True,
        description="Modeled preempt flag; no preemption behavior is simulated.",
    )
    reserved_addresses: tuple[AddressType, ...] = Field(
        default_factory=tuple,
        description="Modeled already-assigned addresses the VIP must not collide with.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_reserved(cls, data: object) -> object:
        if isinstance(data, dict) and "reserved_addresses" in data:
            values = [str(value) for value in data["reserved_addresses"]]
            return {**data, "reserved_addresses": tuple(sorted(set(values)))}
        return data


class HaAnalysis(BaseModel):
    """Deterministic result of one group-design review."""

    active_members: dict[str, str] = Field(
        default_factory=dict,
        description="Group id to modeled active member device id (all members live).",
    )
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    assumptions: tuple[str, ...] = Field(default_factory=tuple)


def active_member(
    group: HaGroup,
    *,
    failed_devices: frozenset[str] | set[str] = frozenset(),
) -> HaMember | None:
    """Return the modeled active member, or None when no member is live."""
    live = [
        member
        for member in group.members
        if member.device_id not in failed_devices
    ]
    if not live:
        return None
    return min(live, key=lambda member: (-member.priority, member.device_id))


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


def analyze_ha_groups(
    groups: tuple[HaGroup, ...] | list[HaGroup],
    topology: Topology,
    *,
    vlan_plan: VlanPlanResult | None = None,
) -> HaAnalysis:
    """Check every modeled HA group and derive its nominal active member."""
    if len(groups) > MAX_HA_GROUPS:
        raise LimitsExceededError(
            f"HA design has {len(groups)} groups; the limit is {MAX_HA_GROUPS}"
        )
    for group in groups:
        if len(group.members) > MAX_HA_MEMBERS:
            raise LimitsExceededError(
                f"HA group {group.id!r} has {len(group.members)} members; "
                f"the limit is {MAX_HA_MEMBERS}"
            )

    findings: list[Finding] = []
    device_ids = {device.id for device in topology.devices}
    neighbors: dict[str, set[str]] = {device_id: set() for device_id in device_ids}
    for link in topology.links:
        start, end = link.endpoints
        neighbors.setdefault(start, set()).add(end)
        neighbors.setdefault(end, set()).add(start)

    vlan_assignments = (
        {assignment.vlan_id: assignment for assignment in vlan_plan.assignments}
        if vlan_plan is not None
        else {}
    )
    vip_owner: dict[str, str] = {}
    active: dict[str, str] = {}

    for group in groups:
        elected = active_member(group)
        if elected is not None:
            active[group.id] = elected.device_id

        if group.virtual_ip.version != group.subnet.version:
            findings.append(
                _finding(
                    Severity.error,
                    "ha_vip_subnet_mismatch",
                    (
                        f"Group {group.id!r} VIP {group.virtual_ip} is IPv"
                        f"{group.virtual_ip.version} but its subnet is IPv"
                        f"{group.subnet.version}."
                    ),
                    "Use a VIP and subnet of the same IP version.",
                    [group.id],
                )
            )
        elif group.virtual_ip not in group.subnet:
            findings.append(
                _finding(
                    Severity.error,
                    "ha_vip_outside_subnet",
                    (
                        f"VIP {group.virtual_ip} lies outside group {group.id!r} "
                        f"subnet {group.subnet}."
                    ),
                    "Move the VIP inside the subnet or correct the subnet.",
                    [group.id, str(group.virtual_ip)],
                )
            )
        elif group.subnet.version == 4 and group.virtual_ip in {
            group.subnet.network_address,
            group.subnet.broadcast_address,
        }:
            findings.append(
                _finding(
                    Severity.error,
                    "ha_vip_collision",
                    (
                        f"VIP {group.virtual_ip} is the network or broadcast address "
                        f"of {group.subnet}."
                    ),
                    "Choose a host address inside the subnet.",
                    [group.id, str(group.virtual_ip)],
                )
            )

        key = str(group.virtual_ip)
        if key in vip_owner and vip_owner[key] != group.id:
            findings.append(
                _finding(
                    Severity.error,
                    "ha_vip_collision",
                    (
                        f"VIP {key} is used by groups {vip_owner[key]!r} and "
                        f"{group.id!r}."
                    ),
                    "Give each group a distinct VIP.",
                    [vip_owner[key], group.id, key],
                )
            )
        vip_owner[key] = group.id
        for reserved in group.reserved_addresses:
            if reserved == group.virtual_ip:
                findings.append(
                    _finding(
                        Severity.error,
                        "ha_vip_collision",
                        (
                            f"VIP {group.virtual_ip} collides with a modeled reserved "
                            f"address in group {group.id!r}."
                        ),
                        "Choose a VIP that is not assigned to another entity.",
                        [group.id, str(group.virtual_ip)],
                    )
                )

        ids = [member.device_id for member in group.members]
        if len(ids) != len(set(ids)):
            findings.append(
                _finding(
                    Severity.error,
                    "ha_duplicate_member",
                    f"Group {group.id!r} lists a member device more than once.",
                    "Remove duplicate members.",
                    [group.id],
                )
            )
        for member in group.members:
            if member.device_id not in device_ids:
                findings.append(
                    _finding(
                        Severity.error,
                        "ha_unknown_member",
                        (
                            f"Group {group.id!r} references unknown device "
                            f"{member.device_id!r}."
                        ),
                        "Remove the stale reference or add the device to the topology.",
                        [group.id, member.device_id],
                    )
                )
            if group.vlan_id is not None:
                if not member.vlan_ids:
                    findings.append(
                        _finding(
                            Severity.warning,
                            "ha_member_vlan_unknown",
                            (
                                f"Member {member.device_id!r} has no modeled VLAN "
                                f"attachment; group {group.id!r} is bound to VLAN "
                                f"{group.vlan_id}."
                            ),
                            "Record the member's VLAN ids in the design annotation.",
                            [group.id, member.device_id],
                        )
                    )
                elif group.vlan_id not in member.vlan_ids:
                    findings.append(
                        _finding(
                            Severity.error,
                            "ha_member_not_on_vlan",
                            (
                                f"Member {member.device_id!r} is modeled on VLANs "
                                f"{list(member.vlan_ids)}, not group VLAN "
                                f"{group.vlan_id}."
                            ),
                            "Attach the member to the group's VLAN or change the group.",
                            [group.id, member.device_id],
                        )
                    )
        if group.vlan_id is not None and group.vlan_id in vlan_assignments:
            assignment = vlan_assignments[group.vlan_id]
            if str(assignment.network) != str(group.subnet):
                findings.append(
                    _finding(
                        Severity.warning,
                        "ha_subnet_vlan_mismatch",
                        (
                            f"Group {group.id!r} subnet {group.subnet} differs from "
                            f"VLAN {group.vlan_id} plan subnet {assignment.network}."
                        ),
                        "Align the group subnet with the VLAN plan.",
                        [group.id, str(group.vlan_id)],
                    )
                )

        priorities = [member.priority for member in group.members]
        top = max(priorities, default=-1)
        if priorities.count(top) > 1:
            findings.append(
                _finding(
                    Severity.warning,
                    "ha_priority_tie",
                    (
                        f"Group {group.id!r} has {priorities.count(top)} members tied "
                        f"at the top priority {top}; the model breaks ties by device id."
                    ),
                    "Give one member a higher priority to remove ambiguity.",
                    [group.id],
                )
            )
        if len(group.members) < 2:
            findings.append(
                _finding(
                    Severity.warning,
                    "ha_single_member",
                    f"Group {group.id!r} has {len(group.members)} member(s); "
                    "no redundant gateway is modeled.",
                    "Add at least one more member.",
                    [group.id],
                )
            )
        if not group.preempt:
            findings.append(
                _finding(
                    Severity.info,
                    "ha_preempt_disabled",
                    (
                        f"Group {group.id!r} records preempt=false. No preemption "
                        "behavior is simulated."
                    ),
                    "Confirm this is intentional for the modeled design.",
                    [group.id],
                )
            )

        member_set = set(ids)
        upstream_sets = {
            member_id: neighbors.get(member_id, set()) - member_set
            for member_id in member_set
        }
        if member_set and all(
            len(upstream) == 1 for upstream in upstream_sets.values()
        ):
            common = set.intersection(*upstream_sets.values()) if upstream_sets else set()
            if len(common) == 1:
                uplink = next(iter(common))
                findings.append(
                    _finding(
                        Severity.warning,
                        "ha_shared_fate_uplink",
                        (
                            f"All members of group {group.id!r} reach the rest of the "
                            f"modeled topology through one uplink device {uplink!r}."
                        ),
                        "Add a second upstream path or model a separate failure domain.",
                        [group.id, uplink],
                    )
                )

    findings.sort(key=lambda item: (item.code, tuple(item.affected_entities)))
    assumptions = (
        "Modeled design rules only: no VRRP/HSRP advertisements or packets are simulated.",
        "Active member = highest priority, ties by lexicographically lowest device id.",
        (
            "Member VLAN attachment is a design annotation checked against the "
            "group and the optional VLAN plan."
        ),
        "Shared fate is derived from each member's single common non-member neighbor.",
    )
    return HaAnalysis(
        active_members=active,
        findings=tuple(findings),
        assumptions=assumptions,
    )


__all__ = [
    "HaAnalysis",
    "HaGroup",
    "HaMember",
    "active_member",
    "analyze_ha_groups",
]
