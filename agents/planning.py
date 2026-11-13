"""Deterministic design policy used by the structured-form workflow.

Nothing here calls an LLM, Streamlit, or a random source. The policy converts
:class:`~core.schemas.requirements.NetworkRequirements` into a topology, an
IP/VLAN plan, modeled traffic demands, and a derived working twin, using the
existing deterministic engines. Every choice is documented in this module so
the resulting plan can be audited and replicated.
"""

from __future__ import annotations

import ipaddress
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.schemas.addressing import AddressingPlan, Subnet, VlanPlan
from core.schemas.network import Device, Link, Topology
from core.schemas.requirements import Assumption, NetworkRequirements
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.addressing import VlsmRequirement, allocate_vlsm
from network.topology import (
    enforce_limits,
    generate_hierarchical_campus,
    generate_star,
)
from network.vlan import VlanPlanResult, VlanRequest, plan_vlans

DEFAULT_BASE_NETWORK = "10.0.0.0/16"
DEFAULT_LINK_CAPACITY_MBPS = 1_000.0
DEFAULT_LINK_COST = 1.0
DEFAULT_VLAN_START = 10
DEFAULT_DEMAND_BANDWIDTH_MBPS = 10.0

_REDUNDANCY_TERMS = (
    "redundan",
    "resilien",
    "high availability",
    "failover",
    "fault toleran",
)
_BASE_NETWORK_PATTERN = re.compile(
    r"base\s+network\s*[:=]?\s*([0-9a-fA-F:.]+/[0-9]{1,3})",
    re.IGNORECASE,
)


class IpPlanResult(BaseModel):
    """Deterministic IP/VLAN plan produced from requirements.

    ``addressing`` and ``vlan_plan`` are optional so a deliberately seeded
    invalid subnet list can be represented for re-plan tests. Production plans
    always populate both.
    """

    base_network: str
    attempt: int = Field(default=1, ge=1)
    subnets: list[Subnet] = Field(default_factory=list)
    vlan_plan: VlanPlanResult | None = None
    addressing: AddressingPlan | None = None
    department_names: list[str] = Field(default_factory=list)


class DemandPlan(BaseModel):
    """Modeled traffic demands derived from a topology and user counts."""

    demands: list[TrafficDemand] = Field(default_factory=list)
    note: str = ""


def _goal_text(requirements: NetworkRequirements) -> str:
    facts = requirements.user_provided
    return " ".join(
        [
            *requirements.design_goals,
            *facts.constraints,
        ]
    ).lower()


def redundancy_requested(requirements: NetworkRequirements) -> bool:
    """Return whether the user asked for resilience or high availability."""
    text = _goal_text(requirements)
    return any(term in text for term in _REDUNDANCY_TERMS)


def departments(
    requirements: NetworkRequirements,
) -> list[tuple[str, str, int]]:
    """Return ``(unique_key, display_name, user_count)`` planning departments.

    Departments are collected from the organization, the explicit site list,
    and the flat department list without mixing assumptions into user facts.
    Duplicate ids across sites are disambiguated with the site id.
    """
    facts = requirements.user_provided
    collected: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()

    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    for site in sites:
        for department in site.departments:
            if department.id in seen:
                continue
            seen.add(department.id)
            collected.append(
                (department.id, department.name, site.id, department.user_count)
            )
    for department in facts.departments:
        if department.id in seen:
            continue
        seen.add(department.id)
        collected.append(
            (department.id, department.name, "site-1", department.user_count)
        )

    if not collected:
        users = max(1, facts.total_user_count or 50)
        return [("users", "General users", users)]

    id_counts: dict[str, int] = {}
    for department_id, _, _, _ in collected:
        id_counts[department_id] = id_counts.get(department_id, 0) + 1
    return [
        (
            department_id
            if id_counts[department_id] == 1
            else f"{site_id}-{department_id}",
            name,
            user_count,
        )
        for department_id, name, site_id, user_count in collected
    ]


def base_network_for(requirements: NetworkRequirements) -> str:
    """Return the first user-specified base network, else the documented default."""
    for constraint in requirements.user_provided.constraints:
        match = _BASE_NETWORK_PATTERN.search(constraint)
        if match is None:
            continue
        try:
            return str(ipaddress.ip_network(match.group(1), strict=False))
        except ValueError:
            continue
    return DEFAULT_BASE_NETWORK


def next_base_network(base_network: str, attempt: int = 1) -> str:
    """Return a non-overlapping sibling block for a bounded re-plan attempt."""
    network = ipaddress.ip_network(base_network, strict=False)
    offset = network.num_addresses * max(1, attempt)
    start = int(network.network_address) + offset
    maximum = (1 << (32 if network.version == 4 else 128)) - 1
    if start > maximum:
        return DEFAULT_BASE_NETWORK
    candidate = ipaddress.ip_network(
        (start, network.prefixlen), strict=False
    )
    return str(candidate)


def _site_catalog(requirements: NetworkRequirements) -> list[tuple[str, str, int]]:
    """Return ``(site_id, site_name, department_count)`` for topology generation."""
    facts = requirements.user_provided
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    if not sites:
        return [("site-1", "Main site", len(departments(requirements)))]
    counts = [len(site.departments) for site in sites]
    if not any(counts):
        counts = [len(departments(requirements)), *([0] * (len(sites) - 1))]
    return [
        (site.id, site.name, count)
        for site, count in zip(sites, counts, strict=True)
    ]


def _user_topology(requirements: NetworkRequirements) -> Topology | None:
    facts = requirements.user_provided
    if not facts.device_requirements:
        return None
    devices = list(facts.device_requirements)
    links = list(facts.link_requirements)
    if not links and len(devices) > 1:
        hub = devices[0]
        links = [
            Link(
                id=f"user-link-{index:02d}",
                endpoints=(hub.id, device.id),
                capacity_mbps=DEFAULT_LINK_CAPACITY_MBPS,
                cost=DEFAULT_LINK_COST,
            )
            for index, device in enumerate(devices[1:], start=1)
        ]
    return Topology(
        name=(
            facts.organization.name
            if facts.organization is not None
            else "User-supplied design"
        ),
        devices=devices,
        links=links,
    )


def _site_topology(
    site_id: str,
    site_name: str,
    department_count: int,
    *,
    index: int,
    redundant: bool,
) -> Topology:
    prefix = f"site{index + 1}"
    if department_count <= 4 and not redundant:
        return generate_star(
            name=f"{site_name} access",
            site=site_id,
            spoke_count=max(3, department_count),
            hub_id=f"{prefix}-hub",
            id_prefix=prefix,
            link_capacity_mbps=DEFAULT_LINK_CAPACITY_MBPS,
            link_cost=DEFAULT_LINK_COST,
        )
    distribution_count = max(1, min(8, math.ceil(max(1, department_count) / 4)))
    access_per_distribution = max(
        1, min(4, math.ceil(max(1, department_count) / distribution_count))
    )
    return generate_hierarchical_campus(
        name=f"{site_name} campus",
        site=site_id,
        distribution_count=distribution_count,
        access_per_distribution=access_per_distribution,
        redundant_uplinks=redundant,
        id_prefix=prefix,
        link_capacity_mbps=DEFAULT_LINK_CAPACITY_MBPS,
        link_cost=DEFAULT_LINK_COST,
    )


def build_topology(requirements: NetworkRequirements) -> Topology:
    """Build a topology from user devices or from the documented site policy.

    Policy: a user-supplied device/link set is used as-is. Otherwise each site
    gets an access star when it has at most four departments and resilience was
    not requested, and a three-tier campus above that threshold. Multiple site
    topologies are connected in a ring by WAN links so the design is a single
    connected graph.
    """
    user_topology = _user_topology(requirements)
    if user_topology is not None:
        return enforce_limits(user_topology)

    redundant = redundancy_requested(requirements)
    catalog = _site_catalog(requirements)
    parts = [
        _site_topology(
            site_id,
            site_name,
            count,
            index=index,
            redundant=redundant,
        )
        for index, (site_id, site_name, count) in enumerate(catalog)
    ]
    if len(parts) == 1:
        name = (
            requirements.user_provided.organization.name
            if requirements.user_provided.organization is not None
            else parts[0].name
        )
        return enforce_limits(parts[0].model_copy(update={"name": name}))

    devices = [device for part in parts for device in part.devices]
    links = [link for part in parts for link in part.links]
    cores = [
        next(device for device in part.devices if device.role.value == "core")
        for part in parts
    ]
    for index, (left, right) in enumerate(zip(cores, [*cores[1:], cores[0]], strict=True)):
        links.append(
            Link(
                id=f"wan-link-{index + 1:02d}",
                endpoints=(left.id, right.id),
                capacity_mbps=DEFAULT_LINK_CAPACITY_MBPS,
                cost=DEFAULT_LINK_COST,
            )
        )
    name = (
        requirements.user_provided.organization.name
        if requirements.user_provided.organization is not None
        else "Multi-site design"
    )
    return enforce_limits(Topology(name=name, devices=devices, links=links))


def build_ip_plan(
    requirements: NetworkRequirements,
    *,
    base_network: str | None = None,
    attempt: int = 1,
) -> IpPlanResult:
    """Allocate a VLSM block per department and assign VLAN ids."""
    resolved_base = base_network or base_network_for(requirements)
    catalog = departments(requirements)
    requirements_for_vlsm = [
        VlsmRequirement(name=key, required_hosts=max(1, user_count))
        for key, _, user_count in catalog
    ]
    allocation = allocate_vlsm(resolved_base, requirements_for_vlsm)

    display_by_key = {key: display_name for key, display_name, _ in catalog}
    subnets = [
        Subnet(
            name=item.name,
            network=item.network,
            description=(
                f"Department VLAN for {display_by_key.get(item.name, item.name)}"
            ),
        )
        for item in allocation.allocations
    ]
    requests = [
        VlanRequest(
            department=item.name,
            subnet=subnet,
            purpose=display_by_key.get(item.name, item.name),
        )
        for item, subnet in zip(allocation.allocations, subnets, strict=True)
    ]
    vlan_plan = plan_vlans(requests, start_vlan_id=DEFAULT_VLAN_START)

    by_department = {item.department: item for item in vlan_plan.assignments}
    tagged_subnets = [
        subnet.model_copy(
            update={"vlan_id": by_department[subnet.name].vlan_id}
        )
        for subnet in subnets
    ]
    vlan_plans = [
        VlanPlan(
            vlan_id=assignment.vlan_id,
            name=assignment.vlan_name,
            subnets=[subnet],
            purpose=assignment.purpose,
        )
        for assignment, subnet in zip(
            vlan_plan.assignments, tagged_subnets, strict=True
        )
    ]
    return IpPlanResult(
        base_network=str(resolved_base),
        attempt=attempt,
        subnets=tagged_subnets,
        vlan_plan=vlan_plan,
        addressing=AddressingPlan(vlan_plans=vlan_plans),
        department_names=[display_name for _, display_name, _ in catalog],
    )


def build_demands(
    requirements: NetworkRequirements,
    topology: Topology,
) -> DemandPlan:
    """Derive one modeled demand between the first and last device.

    The bandwidth is a modeled planning assumption (ten percent of the
    reported user count, bounded to 1-1000 Mbps). It is not measured traffic.
    """
    devices = sorted(topology.devices, key=lambda device: device.id)
    if len(devices) < 2:
        return DemandPlan(note="A demand needs at least two devices.")
    users = requirements.user_provided.total_user_count
    bandwidth = (
        DEFAULT_DEMAND_BANDWIDTH_MBPS
        if users <= 0
        else max(1.0, min(1_000.0, users * 0.1))
    )
    return DemandPlan(
        demands=[
            TrafficDemand(
                name="plan-demand",
                source=devices[0].id,
                destination=devices[-1].id,
                bandwidth_mbps=bandwidth,
            )
        ],
        note=(
            "Modeled planning demand: ten percent of the reported user count, "
            "bounded to 1-1000 Mbps."
        ),
    )


def build_working_twin(
    *,
    topology: Topology,
    addressing: AddressingPlan | None = None,
    vlan_plan: VlanPlanResult | None = None,
    demands: Sequence[TrafficDemand] = (),
    assumptions: Sequence[Assumption] = (),
    name: str | None = None,
    created_at: datetime | None = None,
) -> DigitalTwin:
    """Build a derived working twin without copying or mutating a baseline."""
    return DigitalTwin(
        metadata=TwinMetadata(
            name=name or topology.name,
            created_at=created_at or datetime.now(UTC),
        ),
        topology=topology,
        addressing=addressing,
        vlan_plan=vlan_plan,
        demands=tuple(demands),
        assumptions=tuple(assumptions),
    )


def user_devices(requirements: NetworkRequirements) -> list[Device]:
    """Return the user-supplied devices (used by report summaries)."""
    return list(requirements.user_provided.device_requirements)


__all__ = [
    "DEFAULT_BASE_NETWORK",
    "DEFAULT_DEMAND_BANDWIDTH_MBPS",
    "DEFAULT_LINK_CAPACITY_MBPS",
    "DEFAULT_LINK_COST",
    "DEFAULT_VLAN_START",
    "DemandPlan",
    "IpPlanResult",
    "base_network_for",
    "build_demands",
    "build_ip_plan",
    "build_topology",
    "build_working_twin",
    "departments",
    "next_base_network",
    "redundancy_requested",
    "user_devices",
]
