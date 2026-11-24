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

from config.limits import MAX_EDGES, MAX_NODES
from core.exceptions import AgentValidationError
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
MAX_PLANNING_SITES = 8

REDUNDANCY_ASSUMPTION_DESCRIPTION = (
    "distribution layer raised to 2 switches to support redundant uplinks"
)
REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION = (
    "redundant uplinks disabled because resilience was not explicitly requested"
)


class TopologyPolicyError(AgentValidationError):
    """A requirement or parameter combination no generator can accept safely.

    The message is written for users and names the exact inputs to change. Raw
    generator exceptions never become this type's display text.
    """

    def __init__(self, reason: str, *, fields: Sequence[str]) -> None:
        self.reason = reason
        self.fields = tuple(fields)
        field_text = ", ".join(self.fields) or "the supplied requirements"
        super().__init__(f"{reason} Check: {field_text}.")


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


def _record_topology_assumption(
    requirements: NetworkRequirements,
    *,
    key: str,
    description: str,
    rationale: str,
) -> None:
    """Append a deterministic, system-inferred topology assumption once.

    Assumptions stay in ``NetworkRequirements.assumptions``; user facts are
    never modified. The rationale is the provenance shown in the report.
    """
    if any(item.description == description for item in requirements.assumptions):
        return
    base_id = f"assumption-topology-{key}"
    taken = {item.id for item in requirements.assumptions}
    assumption_id = base_id
    suffix = 2
    while assumption_id in taken:
        assumption_id = f"{base_id}-{suffix}"
        suffix += 1
    requirements.assumptions.append(
        Assumption(
            id=assumption_id,
            category="topology",
            description=description,
            rationale=rationale,
        )
    )


def _raw_department_count(requirements: NetworkRequirements) -> int:
    """Count user-supplied departments before planning defaults are applied."""
    facts = requirements.user_provided
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    return len({department.id for site in sites for department in site.departments}) + len(
        facts.departments
    )


def _campus_parameters(
    department_count: int,
    *,
    redundant: bool,
) -> tuple[int, int, list[tuple[str, str]]]:
    """Return valid campus counts and the repairs that produced them."""
    reported = max(1, department_count)
    distribution_count = max(1, min(8, math.ceil(reported / 4)))
    access_per_distribution = max(
        1, min(4, math.ceil(reported / distribution_count))
    )
    repairs: list[tuple[str, str]] = []
    if redundant and distribution_count < 2:
        distribution_count = 2
        access_per_distribution = max(
            1, min(4, math.ceil(reported / distribution_count))
        )
        repairs.append(
            (
                REDUNDANCY_ASSUMPTION_DESCRIPTION,
                (
                    "user_provided.organization.sites[].departments (or "
                    "user_provided.sites[].departments) implies one distribution "
                    "switch, while design_goals/user_provided.constraints request "
                    "redundant uplinks; topology_from_requirements raised it to two."
                ),
            )
        )
    return distribution_count, access_per_distribution, repairs


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
    requirements: NetworkRequirements,
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
    distribution_count, access_per_distribution, repairs = _campus_parameters(
        department_count, redundant=redundant
    )
    for description, rationale in repairs:
        _record_topology_assumption(
            requirements,
            key="distribution-redundancy",
            description=description,
            rationale=rationale,
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


def _param_int(
    family: str,
    params: dict[str, object],
    name: str,
    default: int,
) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TopologyPolicyError(
            f"{family} parameter {name} must be a whole number.",
            fields=(f"params.{name}",),
        )
    return value


def _param_bool(
    family: str,
    params: dict[str, object],
    name: str,
    default: bool,
) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise TopologyPolicyError(
            f"{family} parameter {name} must be true or false.",
            fields=(f"params.{name}",),
        )
    return value


def _check_generator_counts(
    family: str,
    device_count: int,
    link_count: int,
    fields: Sequence[str],
) -> None:
    if device_count > MAX_NODES:
        raise TopologyPolicyError(
            f"{family} needs {device_count} devices; the limit is {MAX_NODES}.",
            fields=fields,
        )
    if link_count > MAX_EDGES:
        raise TopologyPolicyError(
            f"{family} needs {link_count} links; the limit is {MAX_EDGES}.",
            fields=fields,
        )


def validate_generator_params(
    family: str,
    params: dict[str, object],
) -> dict[str, object]:
    """Validate generator parameters before a generator is ever called.

    Invalid counts raise :class:`TopologyPolicyError` with the exact parameter
    names to change. This keeps generator ``ValueError`` text and limit errors
    out of tool and UI messages.
    """
    checked = dict(params)
    if family == "star":
        spokes = _param_int(family, checked, "spoke_count", 4)
        if spokes < 1:
            raise TopologyPolicyError(
                "A star topology needs at least one spoke.",
                fields=("params.spoke_count",),
            )
        _check_generator_counts(
            family, spokes + 1, spokes, ("params.spoke_count",)
        )
    elif family == "ring":
        nodes = _param_int(family, checked, "node_count", 4)
        if nodes < 3:
            raise TopologyPolicyError(
                "A ring topology needs at least three nodes to close the loop.",
                fields=("params.node_count",),
            )
        _check_generator_counts(family, nodes, nodes, ("params.node_count",))
    elif family == "mesh":
        nodes = _param_int(family, checked, "node_count", 4)
        if nodes < 2:
            raise TopologyPolicyError(
                "A full mesh topology needs at least two nodes.",
                fields=("params.node_count",),
            )
        _check_generator_counts(
            family,
            nodes,
            nodes * (nodes - 1) // 2,
            ("params.node_count",),
        )
    elif family == "tree":
        depth = _param_int(family, checked, "depth", 2)
        branching = _param_int(family, checked, "branching_factor", 2)
        if depth < 0:
            raise TopologyPolicyError(
                "A tree topology needs a depth of zero or more.",
                fields=("params.depth",),
            )
        if branching < 1:
            raise TopologyPolicyError(
                "A tree topology needs a branching factor of at least one.",
                fields=("params.branching_factor",),
            )
        if branching == 1:
            device_count = depth + 1
        else:
            device_count = 0
            for level in range(depth + 1):
                device_count += branching**level
                if device_count > MAX_NODES:
                    break
        _check_generator_counts(
            family,
            device_count,
            max(0, device_count - 1),
            ("params.depth", "params.branching_factor"),
        )
    elif family == "campus":
        distribution = _param_int(family, checked, "distribution_count", 2)
        access = _param_int(family, checked, "access_per_distribution", 4)
        redundant = _param_bool(family, checked, "redundant_uplinks", False)
        fields = ("params.distribution_count", "params.access_per_distribution")
        if distribution < 1:
            raise TopologyPolicyError(
                "A campus topology needs at least one distribution switch.",
                fields=("params.distribution_count",),
            )
        if access < 1:
            raise TopologyPolicyError(
                "A campus topology needs at least one access switch per "
                "distribution switch.",
                fields=("params.access_per_distribution",),
            )
        if redundant and distribution < 2:
            raise TopologyPolicyError(
                "Redundant uplinks need at least two distribution switches.",
                fields=("params.redundant_uplinks", "params.distribution_count"),
            )
        uplink_factor = 2 if redundant else 1
        access_count = distribution * access
        _check_generator_counts(
            family,
            (2 if redundant else 1) + distribution + access_count,
            uplink_factor * distribution + uplink_factor * access_count,
            (*fields, "params.redundant_uplinks"),
        )
    elif family == "spine_leaf":
        spines = _param_int(family, checked, "spines", 2)
        leaves = _param_int(family, checked, "leaves", 4)
        full_mesh = _param_bool(family, checked, "full_mesh", False)
        fields = ("params.spines", "params.leaves")
        if spines < 1:
            raise TopologyPolicyError(
                "A spine-leaf fabric needs at least one spine.",
                fields=("params.spines",),
            )
        if leaves < 1:
            raise TopologyPolicyError(
                "A spine-leaf fabric needs at least one leaf.",
                fields=("params.leaves",),
            )
        uplinks = spines if full_mesh else min(spines, 2)
        _check_generator_counts(
            family,
            spines + leaves,
            leaves * uplinks,
            (*fields, "params.full_mesh"),
        )
    elif family == "hybrid":
        cores = _param_int(family, checked, "core_nodes", 4)
        access = _param_int(family, checked, "access_per_core", 3)
        fields = ("params.core_nodes", "params.access_per_core")
        if cores < 3:
            raise TopologyPolicyError(
                "A hybrid topology needs at least three core nodes for its ring.",
                fields=("params.core_nodes",),
            )
        if access < 1:
            raise TopologyPolicyError(
                "A hybrid topology needs at least one access node per core.",
                fields=("params.access_per_core",),
            )
        _check_generator_counts(
            family,
            cores * (2 + access),
            cores * (access + 2),
            fields,
        )
    else:  # pragma: no cover - the tool contract limits the family literal
        raise TopologyPolicyError(
            f"Unknown topology family {family!r}.", fields=("family",)
        )
    return checked


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

    facts = requirements.user_provided
    site_field = (
        "user_provided.organization.sites"
        if facts.organization is not None and facts.organization.sites
        else "user_provided.sites"
    )
    if _raw_department_count(requirements) == 0:
        _record_topology_assumption(
            requirements,
            key="single-department",
            description="no departments supplied; modeled as one general users department",
            rationale=(
                f"{site_field} and user_provided.departments are empty; "
                "topology_from_requirements used one planning department."
            ),
        )
    if facts.total_user_count <= 0:
        _record_topology_assumption(
            requirements,
            key="zero-users",
            description="zero reported users modeled as one planning user",
            rationale=(
                "user_provided.total_user_count is zero; topology sizing needs "
                "at least one department with one user."
            ),
        )

    redundant = redundancy_requested(requirements)
    if not redundant:
        _record_topology_assumption(
            requirements,
            key="redundancy-disabled",
            description=REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION,
            rationale=(
                "design_goals and user_provided.constraints contain no "
                "explicit resilience request; topology_from_requirements "
                "disabled redundant uplinks."
            ),
        )

    catalog = _site_catalog(requirements)
    if len(catalog) > MAX_PLANNING_SITES:
        catalog = catalog[:MAX_PLANNING_SITES]
        _record_topology_assumption(
            requirements,
            key="site-cap",
            description=(
                f"site list limited to {MAX_PLANNING_SITES} sites for topology sizing"
            ),
            rationale=(
                f"{site_field} supplies more than {MAX_PLANNING_SITES} sites; "
                "topology_from_requirements kept the first ones to stay within "
                "the device and link limits."
            ),
        )
    parts = [
        _site_topology(
            site_id,
            site_name,
            count,
            index=index,
            redundant=redundant,
            requirements=requirements,
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
    "REDUNDANCY_ASSUMPTION_DESCRIPTION",
    "REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION",
    "DemandPlan",
    "IpPlanResult",
    "TopologyPolicyError",
    "base_network_for",
    "build_demands",
    "build_ip_plan",
    "build_topology",
    "build_working_twin",
    "departments",
    "next_base_network",
    "redundancy_requested",
    "user_devices",
    "validate_generator_params",
]
