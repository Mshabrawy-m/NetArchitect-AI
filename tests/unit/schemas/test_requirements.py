"""Unit tests for ``core.schemas.requirements``."""

import pytest
from pydantic import ValidationError

from core.schemas.network import Device, DeviceRole, DeviceType, Link
from core.schemas.organization import Department, Organization, Site
from core.schemas.requirements import Assumption, NetworkRequirements, UserFacts


def _sample_user_facts() -> UserFacts:
    return UserFacts(
        organization=Organization(id="org-1", name="Acme"),
        sites=[Site(id="site-1", name="HQ")],
        departments=[Department(id="dept-1", name="Engineering", user_count=25)],
        device_requirements=[
            Device(id="dev-1", type=DeviceType.router, site="site-1", role=DeviceRole.core),
            Device(id="dev-2", type=DeviceType.switch, site="site-1", role=DeviceRole.access),
        ],
        link_requirements=[
            Link(id="link-1", endpoints=("dev-1", "dev-2"), capacity_mbps=1000.0, cost=1.0)
        ],
        constraints=["Every site needs redundant WAN connectivity."],
        total_user_count=120,
    )


def _sample_assumption() -> Assumption:
    return Assumption(
        id="asum-1",
        category="growth",
        description="Headcount grows 10% annually.",
        rationale="Historical hiring trend.",
    )


def test_network_requirements_valid() -> None:
    reqs = NetworkRequirements(
        user_provided=_sample_user_facts(),
        assumptions=[_sample_assumption()],
        design_goals=["Minimize cost", "Maximize redundancy"],
    )
    assert reqs.user_provided.total_user_count == 120
    assert len(reqs.assumptions) == 1
    assert reqs.assumptions[0].id == "asum-1"


def test_assumptions_distinct_from_user_provided() -> None:
    facts = _sample_user_facts()
    assumption = _sample_assumption()
    reqs = NetworkRequirements(user_provided=facts, assumptions=[assumption])

    # Assumptions live only in the assumptions field, never on user_provided.
    assert reqs.assumptions == [assumption]
    assert not hasattr(reqs.user_provided, "assumptions")
    # The assumption is not folded into any user_provided collection.
    assert assumption not in reqs.user_provided.constraints
    assert reqs.user_provided.organization is not None
    assert reqs.user_provided.organization != assumption


def test_network_requirements_round_trip_preserves_both() -> None:
    reqs = NetworkRequirements(
        user_provided=_sample_user_facts(),
        assumptions=[_sample_assumption()],
        design_goals=["Minimize cost"],
    )
    restored = NetworkRequirements.model_validate_json(reqs.model_dump_json())
    assert restored == reqs
    # Both halves survive the round trip independently.
    assert restored.user_provided == reqs.user_provided
    assert restored.assumptions == reqs.assumptions


def test_user_facts_negative_total_user_count_invalid() -> None:
    with pytest.raises(ValidationError):
        UserFacts(total_user_count=-1)


def test_user_facts_defaults_empty() -> None:
    facts = UserFacts()
    assert facts.organization is None
    assert facts.sites == []
    assert facts.departments == []
    assert facts.device_requirements == []
    assert facts.link_requirements == []
    assert facts.constraints == []
    assert facts.total_user_count == 0


def test_assumption_default_rationale() -> None:
    assumption = Assumption(id="asum-2", category="traffic", description="Peak hours 9-5.")
    assert assumption.rationale == ""
