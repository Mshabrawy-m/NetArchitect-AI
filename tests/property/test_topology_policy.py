"""Bounded property checks for the requirement-derived topology policy."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from agents.planning import build_topology
from core.schemas.organization import Department, Organization, Site
from core.schemas.requirements import NetworkRequirements, UserFacts
from tests.property.config import BOUNDED


@st.composite
def _valid_requirements(draw):
    site_count = draw(st.integers(0, 12))
    department_count = draw(st.integers(0, 8))
    users = draw(st.integers(0, 1_000_000))
    redundancy = draw(st.sampled_from((True, False, None)))
    goals = (
        []
        if redundancy is None
        else (["Provide resilience."] if redundancy else ["Minimize cost."])
    )
    constraints = draw(
        st.lists(
            st.sampled_from(
                (
                    "base network: 10.30.0.0/16",
                    "Every site needs redundant uplinks.",
                )
            ),
            max_size=2,
        )
    )
    sites = [
        Site(
            id=f"site-{site_index + 1}",
            name=f"Site {site_index + 1}",
            departments=[
                Department(
                    id=f"site-{site_index + 1}-dept-{index + 1}",
                    name=f"Department {index + 1}",
                    user_count=draw(st.integers(0, 1000)),
                )
                for index in range(department_count)
            ],
        )
        for site_index in range(site_count)
    ]
    return NetworkRequirements(
        user_provided=UserFacts(
            organization=(
                Organization(id="org-1", name="Acme", sites=sites)
                if sites
                else None
            ),
            sites=sites,
            constraints=constraints,
            total_user_count=users,
        ),
        design_goals=goals,
    )


@given(_valid_requirements())
@BOUNDED
def test_topology_step_never_raises_for_valid_requirements(
    requirements: NetworkRequirements,
) -> None:
    topology = build_topology(requirements)

    assert topology.devices
    assert topology.links
    assert any(device.role.value == "core" for device in topology.devices)
    assert {device.site for device in topology.devices}
