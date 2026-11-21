"""Three clearly labeled sample projects for the Dashboard quick start.

Every sample is assembled with the same deterministic generators, addressing
engines, and twin model used by the working pages. Building a sample never
touches session state; ``load_sample`` replaces the baseline twin only when the
caller passes explicit confirmation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet, VlanPlan
from core.schemas.network import Topology
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.addressing import VlsmRequirement, allocate_vlsm
from network.topology import (
    generate_hierarchical_campus,
    generate_spine_leaf,
    generate_star,
)
from network.vlan import VlanPlanResult, VlanRequest, plan_vlans
from network.vlan.dhcp import plan_dhcp_scopes
from simulation import twin_fingerprint
from ui import state

PENDING_KEY = "sample_project_pending"
_SAMPLE_TIME = datetime(2026, 11, 21, tzinfo=UTC)


@dataclass(frozen=True)
class SampleProject:
    """One sample project offered on the Dashboard."""

    key: str
    name: str
    description: str
    summary: str
    builder: Callable[[], DigitalTwin]


@dataclass(frozen=True)
class _AddressingSpec:
    parent: str
    groups: tuple[tuple[str, int], ...]
    demands: tuple[tuple[str, str], ...]


def _plan_addressing(spec: _AddressingSpec) -> tuple[
    AddressingPlan, VlanPlanResult, tuple[DhcpScope, ...]
]:
    allocations = allocate_vlsm(
        spec.parent,
        [VlsmRequirement(name=name, required_hosts=hosts) for name, hosts in spec.groups],
    ).allocations
    subnets = [
        Subnet(name=item.name, network=str(item.network), vlan_id=10 + index)
        for index, item in enumerate(allocations)
    ]
    vlan_result = plan_vlans(
        [
            VlanRequest(
                department=subnet.name,
                subnet=subnet,
                vlan_id=subnet.vlan_id,
                vlan_name=subnet.name.replace("-", " ").title(),
            )
            for subnet in subnets
        ]
    )
    addressing = AddressingPlan(
        vlan_plans=[
            VlanPlan(
                vlan_id=assignment.vlan_id,
                name=assignment.vlan_name,
                subnets=[subnet],
            )
            for assignment, subnet in zip(vlan_result.assignments, subnets, strict=True)
        ]
    )
    return addressing, vlan_result, tuple(plan_dhcp_scopes(subnets))


def _make_twin(
    topology: Topology,
    spec: _AddressingSpec,
) -> DigitalTwin:
    addressing, vlan_plan, scopes = _plan_addressing(spec)
    demands = tuple(
        TrafficDemand(
            name=f"{source}-to-{target}",
            source=source,
            destination=target,
            bandwidth_mbps=10.0,
            priority=1,
        )
        for source, target in spec.demands
    )
    return DigitalTwin(
        metadata=TwinMetadata(name=topology.name, created_at=_SAMPLE_TIME),
        topology=topology,
        addressing=addressing,
        vlan_plan=vlan_plan,
        dhcp_scopes=scopes,
        demands=demands,
    )


def _small_office() -> DigitalTwin:
    topology = generate_star(
        name="SAMPLE - Small office",
        site="office",
        spoke_count=4,
        hub_id="office-hub",
        id_prefix="office",
        link_capacity_mbps=1000.0,
    )
    return _make_twin(
        topology,
        _AddressingSpec(
            parent="192.168.10.0/24",
            groups=(("office-users", 20),),
            demands=(
                ("office-spoke-00", "office-hub"),
                ("office-spoke-01", "office-hub"),
            ),
        ),
    )


def _campus() -> DigitalTwin:
    topology = generate_hierarchical_campus(
        name="SAMPLE - Campus",
        site="campus",
        distribution_count=2,
        access_per_distribution=2,
        redundant_uplinks=True,
        id_prefix="campus",
        link_capacity_mbps=1000.0,
    )
    return _make_twin(
        topology,
        _AddressingSpec(
            parent="10.20.0.0/16",
            groups=(("faculty", 40), ("students", 60)),
            demands=(
                ("campus-acc-01-01", "campus-acc-01-02"),
                ("campus-acc-02-01", "campus-acc-02-02"),
            ),
        ),
    )


def _spine_leaf() -> DigitalTwin:
    topology = generate_spine_leaf(
        name="SAMPLE - Spine-leaf DC",
        site="dc",
        spines=2,
        leaves=4,
        full_mesh=True,
        id_prefix="fabric",
        link_capacity_mbps=10000.0,
    )
    return _make_twin(
        topology,
        _AddressingSpec(
            parent="10.30.0.0/16",
            groups=(("applications", 50), ("storage", 30)),
            demands=(
                ("fabric-leaf-01", "fabric-leaf-02"),
                ("fabric-leaf-03", "fabric-leaf-04"),
            ),
        ),
    )


SAMPLE_PROJECTS: tuple[SampleProject, ...] = (
    SampleProject(
        key="small-office",
        name="SAMPLE - Small office",
        description="One core switch with four access hosts and a single user VLAN.",
        summary="5 devices | 4 links | 2 demands",
        builder=_small_office,
    ),
    SampleProject(
        key="campus",
        name="SAMPLE - Campus",
        description="Redundant two-tier campus with core, distribution, and access switches.",
        summary="8 devices | 12 links | 2 demands",
        builder=_campus,
    ),
    SampleProject(
        key="spine-leaf-dc",
        name="SAMPLE - Spine-leaf DC",
        description="Two spines and four leaves in a full-mesh fabric with two server VLANs.",
        summary="6 devices | 8 links | 2 demands",
        builder=_spine_leaf,
    ),
)


def sample_by_key(key: str) -> SampleProject:
    """Return one sample project by its stable key."""
    for sample in SAMPLE_PROJECTS:
        if sample.key == key:
            return sample
    raise ValueError(f"Unknown sample project: {key!r}")


def build_sample(key: str) -> DigitalTwin:
    """Build a fresh sample twin without changing session state."""
    return sample_by_key(key).builder()


def request_sample(key: str) -> None:
    """Record which sample the user explicitly selected, pending confirmation."""
    sample_by_key(key)
    state.session_set(PENDING_KEY, key)


def cancel_sample() -> None:
    """Clear a pending sample selection without loading anything."""
    state.session_delete(PENDING_KEY)


def pending_sample() -> SampleProject | None:
    """Return the sample awaiting confirmation, if any."""
    key = state.session_get(PENDING_KEY)
    if not isinstance(key, str):
        return None
    try:
        return sample_by_key(key)
    except ValueError:
        state.session_delete(PENDING_KEY)
        return None


def load_sample(key: str, *, confirmed: bool) -> DigitalTwin:
    """Replace the baseline twin with a sample only after explicit confirmation."""
    if not confirmed:
        raise ValueError("A sample project requires explicit confirmation before loading.")
    twin = build_sample(key)
    before = state.peek_twin()
    source_fingerprint = twin_fingerprint(before) if before is not None else ""
    state.replace_twin(twin)
    state.record_decision(
        kind="sample_applied",
        subject_id=key,
        title=f"Loaded sample project: {sample_by_key(key).name}",
        page="Dashboard",
        source_fingerprint=source_fingerprint,
        result_fingerprint=twin_fingerprint(twin),
    )
    state.session_delete(PENDING_KEY)
    return twin


__all__ = [
    "PENDING_KEY",
    "SAMPLE_PROJECTS",
    "SampleProject",
    "build_sample",
    "cancel_sample",
    "load_sample",
    "pending_sample",
    "request_sample",
    "sample_by_key",
]
