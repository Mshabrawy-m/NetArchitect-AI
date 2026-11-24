"""Requirement-derived topology policy tests.

These are first-run style tests: they use the same structured form builder and
the same parsed free-text entry point as the UI, then run the deterministic
workflow with no provider and no live network.
"""

from __future__ import annotations

import json

import pytest

from agents import (
    Orchestrator,
    WorkflowStopReason,
    understand_requirements,
)
from agents.planning import (
    MAX_PLANNING_SITES,
    REDUNDANCY_ASSUMPTION_DESCRIPTION,
    REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION,
    TopologyPolicyError,
    build_topology,
)
from agents.tools import registry_with_defaults
from core.schemas.network import Device, DeviceRole, DeviceType
from core.schemas.organization import Department, Organization, Site
from core.schemas.requirements import NetworkRequirements, UserFacts
from services.llm.testing import FakeProvider
from ui.components.requirements_form import build_requirements

RAW_GENERATOR_ERROR = "redundant_uplinks requires distribution_count"
REGISTRY = registry_with_defaults()


def extraction(**overrides: object) -> str:
    payload: dict[str, object] = {
        "organization_name": "Acme",
        "site_name": "Headquarters",
        "departments": [],
        "total_user_count": None,
        "constraints": [],
        "design_goals": [],
        "assumptions": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def make_requirements(
    users: int,
    department_count: int,
    redundancy: bool | None,
    *,
    site_count: int = 1,
) -> NetworkRequirements:
    """Build valid requirements from the documented form/agent inputs."""
    goals = (
        []
        if redundancy is None
        else ["Provide redundancy and failover."]
        if redundancy
        else ["Keep the design simple."]
    )
    per_site = [
        Department(
            id=f"dept-{index + 1}",
            name=f"Department {index + 1}",
            user_count=users // department_count,
        )
        for index in range(department_count)
    ]
    if site_count == 1:
        return build_requirements(
            organization_name="Acme",
            site_name="Headquarters",
            departments=[(item.name, item.user_count) for item in per_site],
            design_goals=goals,
            constraints=[],
        )
    sites = [
        Site(
            id=f"site-{site_index + 1}",
            name=f"Site {site_index + 1}",
            departments=[
                item.model_copy(update={"id": f"site-{site_index + 1}-{item.id}"})
                for item in per_site
            ],
        )
        for site_index in range(site_count)
    ]
    return NetworkRequirements(
        user_provided=UserFacts(
            organization=Organization(id="org-1", name="Acme", sites=sites),
            sites=sites,
            total_user_count=users,
        ),
        design_goals=goals,
    )


def _topology_from_tool(requirements: NetworkRequirements):
    return REGISTRY.invoke(
        "topology_from_requirements",
        {"requirements": requirements},
        agent="test",
        allowed=frozenset({"topology_from_requirements"}),
    )


def test_reproduce_small_site_with_redundancy_defaulted_on() -> None:
    requirements = make_requirements(37, 2, True)

    state = Orchestrator().run_structured(requirements)

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.results["topology"].topology.name
    assert not state.error
    core = [
        device
        for device in state.results["topology"].topology.devices
        if device.role.value == "core"
    ]
    distribution = [
        device
        for device in state.results["topology"].topology.devices
        if device.role.value == "distribution"
    ]
    assert len(core) == 2
    assert len(distribution) == 2
    assert any(
        item.description == REDUNDANCY_ASSUMPTION_DESCRIPTION
        for item in requirements.assumptions
    )
    trace = state.trace.to_json()
    assert RAW_GENERATOR_ERROR not in trace
    assert RAW_GENERATOR_ERROR not in state.error


def test_redundancy_not_explicitly_requested_disables_uplinks() -> None:
    requirements = make_requirements(24, 6, None)

    state = Orchestrator().run_structured(requirements)

    core = [
        device
        for device in state.results["topology"].topology.devices
        if device.role.value == "core"
    ]
    assert state.stop_reason is WorkflowStopReason.completed
    assert len(core) == 1
    assert any(
        item.description == REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION
        for item in requirements.assumptions
    )
    assert not any(
        item.description == REDUNDANCY_ASSUMPTION_DESCRIPTION
        for item in requirements.assumptions
    )


def test_parsed_free_text_requirement_repairs_small_org() -> None:
    provider = FakeProvider(
        [
            extraction(
                departments=[
                    {"name": "Engineering", "user_count": 12},
                    {"name": "Sales", "user_count": 5},
                ],
                total_user_count=17,
                design_goals=["Provide resilience."],
            )
        ]
    )
    output = understand_requirements(
        "Engineering has 12 users and Sales has 5 users. Provide resilience.",
        provider=provider,
    )
    assert output.requirements is not None

    state = Orchestrator().run_structured(output.requirements)

    assert state.stop_reason is WorkflowStopReason.completed
    assert any(
        item.description == REDUNDANCY_ASSUMPTION_DESCRIPTION
        for item in output.requirements.assumptions
    )
    report = state.results["documentation"]
    assert any(
        REDUNDANCY_ASSUMPTION_DESCRIPTION in item
        and "topology_from_requirements" in item
        for item in report.assumptions
    )
    assert RAW_GENERATOR_ERROR not in state.error


@pytest.mark.parametrize("users", [1, 2, 4, 8, 25, 100, 1000, 2000])
@pytest.mark.parametrize("department_count", range(1, 9))
@pytest.mark.parametrize("redundancy", [True, False, None])
@pytest.mark.parametrize("site_count", [1, 3])
def test_requirement_size_grid_never_passes_an_invalid_combination(
    users: int,
    department_count: int,
    redundancy: bool | None,
    site_count: int,
) -> None:
    requirements = make_requirements(
        users, department_count, redundancy, site_count=site_count
    )

    topology = _topology_from_tool(requirements)

    assert topology.devices
    assert topology.links
    core = [device for device in topology.devices if device.role.value == "core"]
    assert len(core) == site_count * (2 if redundancy else 1)
    distribution = [
        device for device in topology.devices if device.role.value == "distribution"
    ]
    if redundancy:
        assert distribution
    assert RAW_GENERATOR_ERROR not in str(requirements.assumptions)


def test_every_user_count_from_1_to_2000_is_topologically_valid() -> None:
    for users in range(1, 2001):
        topology = build_topology(make_requirements(users, 2, None))

        assert topology.devices
        assert topology.links
        assert any(device.role.value == "core" for device in topology.devices)


@pytest.mark.parametrize("users", [1, 2000])
@pytest.mark.parametrize("department_count", [1, 4, 8])
@pytest.mark.parametrize("redundancy", [True, False, None])
@pytest.mark.parametrize("site_count", [1, 3])
def test_workflow_grid_completes_or_reports_a_typed_repair(
    users: int,
    department_count: int,
    redundancy: bool | None,
    site_count: int,
) -> None:
    state = Orchestrator().run_structured(
        make_requirements(users, department_count, redundancy, site_count=site_count)
    )

    assert state.stop_reason in {
        WorkflowStopReason.completed,
        WorkflowStopReason.critic_rejected,
    }
    assert RAW_GENERATOR_ERROR not in state.error
    assert RAW_GENERATOR_ERROR not in state.trace.to_json()


def test_zero_users_and_no_departments_are_repaired_with_assumptions() -> None:
    requirements = NetworkRequirements(user_provided=UserFacts(total_user_count=0))

    topology = _topology_from_tool(requirements)

    descriptions = {item.description for item in requirements.assumptions}
    assert "no departments supplied; modeled as one general users department" in (
        descriptions
    )
    assert "zero reported users modeled as one planning user" in descriptions
    assert REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION in descriptions
    assert topology.devices
    assert topology.links


def test_many_sites_are_capped_with_a_recorded_assumption() -> None:
    requirements = make_requirements(40, 2, True, site_count=20)

    topology = _topology_from_tool(requirements)

    sites = {device.site for device in topology.devices}
    assert len(sites) <= MAX_PLANNING_SITES
    assert any(
        f"site list limited to {MAX_PLANNING_SITES} sites" in item.description
        for item in requirements.assumptions
    )


@pytest.mark.parametrize(
    ("family", "params", "field"),
    (
        ("mesh", {"node_count": 1}, "params.node_count"),
        ("ring", {"node_count": 2}, "params.node_count"),
        ("spine_leaf", {"spines": 0}, "params.spines"),
        ("campus", {"distribution_count": 1, "redundant_uplinks": True}, "params.distribution_count"),
        ("mesh", {"node_count": 100}, "params.node_count"),
    ),
)
def test_direct_generator_parameters_fail_with_typed_fields(
    family: str, params: dict[str, object], field: str
) -> None:
    with pytest.raises(TopologyPolicyError) as caught:
        REGISTRY.invoke(
            "topology_generate",
            {"family": family, "params": params},
            agent="test",
            allowed=frozenset({"topology_generate"},),
        )

    assert field in str(caught.value)
    assert "must be" not in str(caught.value) or field in str(caught.value)
    assert RAW_GENERATOR_ERROR not in str(caught.value)


def test_user_supplied_limits_are_typed_without_raw_generator_text() -> None:
    devices = [
        Device(
            id=f"dev-{index:03d}",
            type=DeviceType.router,
            site="site-1",
            role=DeviceRole.core,
        )
        for index in range(501)
    ]
    requirements = NetworkRequirements(
        user_provided=UserFacts(device_requirements=devices, total_user_count=1)
    )

    with pytest.raises(TopologyPolicyError) as caught:
        _topology_from_tool(requirements)

    assert "user_provided.device_requirements" in str(caught.value)
    assert "user_provided.link_requirements" in str(caught.value)
    assert "limit is 500" not in str(caught.value)


def test_failing_workflow_step_explains_fields_and_skips_later_steps() -> None:
    devices = [
        Device(
            id=f"dev-{index:03d}",
            type=DeviceType.router,
            site="site-1",
            role=DeviceRole.core,
        )
        for index in range(501)
    ]
    requirements = NetworkRequirements(
        user_provided=UserFacts(device_requirements=devices, total_user_count=1)
    )

    state = Orchestrator().run_structured(requirements)

    assert state.stop_reason is WorkflowStopReason.failed
    assert "user_provided.device_requirements" in state.tasks["topology"].error
    assert "supplied requirements exceed" in state.error
    assert RAW_GENERATOR_ERROR not in state.error
    assert "dependency 'topology' failed" in state.tasks["report"].skipped_reason
