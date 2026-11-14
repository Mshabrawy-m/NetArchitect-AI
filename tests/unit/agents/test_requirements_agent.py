"""Requirements Understanding Agent tests (Phase 10a).

Every test runs without a network or a real provider. The scripted
:class:`FakeProvider` stands in for the optional language model; the
deterministic structured-form path is exercised with no provider at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agents import (
    AgentContext,
    Clock,
    ExecutionTrace,
    RequirementsAgentInput,
    RequirementsAgentOutput,
    RequirementsAgentStatus,
    RequirementsUnderstandingAgent,
    WorkflowPlan,
    WorkflowState,
    WorkflowTask,
    registry_with_defaults,
)
from config.limits import (
    MAX_HOSTS_PER_SUBNET,
    MAX_REQUIREMENTS_DEPARTMENTS,
    MAX_REQUIREMENTS_TEXT_CHARS,
)
from core.exceptions import AgentValidationError, LLMProviderError
from core.schemas.organization import Department, Site
from core.schemas.requirements import NetworkRequirements, UserFacts
from core.schemas.validation import Severity
from services.llm.testing import FakeProvider
from tests.unit.agents.helpers import sample_requirements


def extraction(**overrides: object) -> str:
    """Return one JSON extraction payload with deterministic defaults."""
    payload: dict[str, object] = {
        "organization_name": "",
        "site_name": "",
        "departments": [],
        "total_user_count": None,
        "constraints": [],
        "design_goals": [],
        "assumptions": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def run_agent(
    agent: RequirementsUnderstandingAgent,
    payload: RequirementsAgentInput,
) -> tuple[RequirementsAgentOutput, ExecutionTrace]:
    """Run the agent in a one-task context and return its output and trace."""
    plan = WorkflowPlan(
        name="Requirements test",
        tasks=(WorkflowTask(id="requirements", agent=agent.name),),
    )
    clock = Clock(
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    state = WorkflowState(plan, clock=clock)
    trace = ExecutionTrace(clock)
    context = AgentContext(
        agent=agent,
        state=state,
        registry=registry_with_defaults(),
        trace=trace,
        clock=clock,
    ).for_task("requirements")
    validated = agent.validate_input(payload)
    return agent.run(validated, context), trace


def all_departments(facts: UserFacts) -> list[Department]:
    """Return every department in ``facts`` without double counting ids."""
    seen: set[str] = set()
    result: list[Department] = []
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    for site in sites:
        for department in site.departments:
            if department.id not in seen:
                seen.add(department.id)
                result.append(department)
    for department in facts.departments:
        if department.id not in seen:
            seen.add(department.id)
            result.append(department)
    return result


def test_valid_extraction_keeps_user_numbers_as_facts() -> None:
    text = (
        "Acme has one site, Headquarters. Engineering has 25 users and Sales "
        "has 12 users. The total is 37 users. Design goals: resilience. "
        "Constraint: budget is 5000."
    )
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                site_name="Headquarters",
                departments=[
                    {"name": "Engineering", "user_count": 25},
                    {"name": "Sales", "user_count": 12},
                ],
                total_user_count=37,
                constraints=["budget is 5000"],
                design_goals=["resilience"],
            )
        ]
    )
    agent = RequirementsUnderstandingAgent(provider)
    output, trace = run_agent(agent, RequirementsAgentInput(free_text=text))

    assert output.status is RequirementsAgentStatus.parsed
    assert output.requirements is not None
    facts = output.requirements.user_provided
    assert [(d.name, d.user_count) for d in all_departments(facts)] == [
        ("Engineering", 25),
        ("Sales", 12),
    ]
    assert facts.total_user_count == 37
    assert output.contradictions == []
    assert output.missing_information == []
    assert output.requirements.design_goals == ["resilience"]
    assert facts.constraints == ["budget is 5000"]
    assert output.provider_used is True
    assert provider.calls[0].schema == "RequirementsExtraction"
    tool_calls = [entry.tool for entry in trace.entries if entry.action == "tool_call"]
    assert tool_calls == ["requirements_validate"]


def test_model_inferences_stay_in_assumptions_and_ungrounded_goals_are_dropped() -> None:
    text = (
        "Acme has 25 users in Engineering. The total is 25 users. "
        "The main goal is resilience."
    )
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                site_name="Headquarters",
                departments=[{"name": "Engineering", "user_count": 25}],
                total_user_count=25,
                design_goals=["resilience", "high availability"],
                constraints=["no downtime"],
                assumptions=[
                    {
                        "category": "security",
                        "description": "Assume a flat Layer 2 domain per site.",
                        "rationale": "The text does not describe VLAN segmentation.",
                    }
                ],
            )
        ]
    )
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text=text),
    )

    assert output.status is RequirementsAgentStatus.parsed
    assert output.facts is not None
    assert output.requirements is not None
    assert [a.description for a in output.assumptions] == [
        "Assume a flat Layer 2 domain per site."
    ]
    assert "Assume a flat Layer 2 domain per site." not in output.facts.model_dump_json()
    assert output.requirements.design_goals == ["resilience"]
    assert "high availability" not in output.requirements.design_goals
    assert output.facts.constraints == []


def test_invented_user_count_never_becomes_a_user_fact() -> None:
    text = "Engineering has 25 users."
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                departments=[{"name": "Engineering", "user_count": 40}],
                total_user_count=40,
            )
        ]
    )
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text=text),
    )

    assert output.status is RequirementsAgentStatus.parsed
    assert output.facts is not None
    assert all_departments(output.facts) == []
    assert output.facts.total_user_count == 0
    assert "40" not in output.facts.model_dump_json()
    codes = {gap.code for gap in output.missing_information}
    assert "unverified_user_count" in codes
    assert "missing_user_counts" in codes
    assert any("Engineering" in question.question for question in output.questions)


def test_missing_information_produces_bounded_questions() -> None:
    text = "Acme is deploying a network."
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                departments=[{"name": "Engineering", "user_count": None}],
            )
        ]
    )
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text=text),
    )

    codes = {gap.code for gap in output.missing_information}
    assert {
        "missing_user_count",
        "missing_user_counts",
        "missing_site",
        "missing_design_goals",
    } <= codes
    assert 1 <= len(output.questions) <= 20
    assert all(question.severity in Severity for question in output.questions)
    assert output.facts is not None
    assert all_departments(output.facts) == []


def test_stated_total_mismatch_is_detected_as_a_contradiction() -> None:
    text = (
        "Engineering has 25 users, Sales has 12 users, and the total is 40 users."
    )
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                departments=[
                    {"name": "Engineering", "user_count": 25},
                    {"name": "Sales", "user_count": 12},
                ],
                total_user_count=40,
            )
        ]
    )
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text=text),
    )

    assert output.status is RequirementsAgentStatus.parsed
    assert [gap.code for gap in output.contradictions] == ["user_count_mismatch"]
    assert "37" in output.contradictions[0].description
    assert output.facts is not None
    assert sum(d.user_count for d in all_departments(output.facts)) == 37
    assert output.facts.total_user_count == 40


def test_user_counts_above_the_planning_limit_are_rejected() -> None:
    oversized = MAX_HOSTS_PER_SUBNET + 1
    text = f"The total is {oversized} users."
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                total_user_count=oversized,
            )
        ]
    )
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text=text),
    )

    assert output.status is RequirementsAgentStatus.parsed
    assert any(
        gap.code == "user_count_limit" for gap in output.missing_information
    )
    assert output.facts is not None
    assert output.facts.total_user_count == 0


def test_provider_failure_returns_a_typed_failed_result() -> None:
    provider = FakeProvider([LLMProviderError("provider is down")])
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text="Acme has 25 users."),
    )

    assert output.status is RequirementsAgentStatus.failed
    assert output.requirements is None
    assert output.provider_used is True
    assert "provider is down" in output.error


def test_malformed_output_is_repaired_within_the_bound() -> None:
    text = "Acme has 25 users in Engineering. The total is 25 users."
    valid = extraction(
        organization_name="Acme",
        departments=[{"name": "Engineering", "user_count": 25}],
        total_user_count=25,
    )
    provider = FakeProvider(["this is not JSON", valid])
    agent = RequirementsUnderstandingAgent(provider, max_repair_retries=1)
    output, _ = run_agent(agent, RequirementsAgentInput(free_text=text))

    assert output.status is RequirementsAgentStatus.parsed
    assert len(provider.calls) == 2
    assert "rejected by schema validation" in provider.calls[1].messages[-1].content


def test_exhausted_repairs_fail_without_fabricated_requirements() -> None:
    provider = FakeProvider(["not JSON", "still not JSON"])
    agent = RequirementsUnderstandingAgent(provider, max_repair_retries=1)
    output, _ = run_agent(agent, RequirementsAgentInput(free_text="Acme has 25 users."))

    assert output.status is RequirementsAgentStatus.failed
    assert output.requirements is None
    assert output.error


def test_without_a_provider_free_text_is_unavailable_not_fabricated() -> None:
    agent = RequirementsUnderstandingAgent(provider=None)
    output, _ = run_agent(
        agent,
        RequirementsAgentInput(free_text="Acme needs a resilient network."),
    )

    assert output.status is RequirementsAgentStatus.unavailable
    assert output.requirements is None
    assert output.provider_used is False
    assert "No AI provider" in output.error
    assert output.questions[0].field == "free_text"
    assert any("structured requirements form" in note for note in output.notes)
    assert output.facts is None


def test_without_a_provider_supplied_structured_data_is_kept() -> None:
    requirements = sample_requirements()
    agent = RequirementsUnderstandingAgent(provider=None)
    output, _ = run_agent(
        agent,
        RequirementsAgentInput(
            free_text="Please interpret this.",
            requirements=requirements,
        ),
    )

    assert output.status is RequirementsAgentStatus.unavailable
    assert output.requirements == requirements
    assert output.facts == requirements.user_provided
    assert output.assumptions == requirements.assumptions


def test_structured_only_path_runs_without_a_provider() -> None:
    requirements = sample_requirements()
    agent = RequirementsUnderstandingAgent(provider=None)
    output, trace = run_agent(
        agent,
        RequirementsAgentInput(free_text="", requirements=requirements),
    )

    assert output.status is RequirementsAgentStatus.structured
    assert output.requirements == requirements
    assert output.provider_used is False
    assert "1 site(s)" in output.summary
    assert "2 department(s)" in output.summary
    assert "37 reported user(s)" in output.summary
    assert [entry.tool for entry in trace.entries] == ["requirements_validate"]


def test_structured_input_is_authoritative_and_extracted_departments_are_merged() -> None:
    site = Site(
        id="site-1",
        name="Headquarters",
        departments=[Department(id="dept-eng", name="Engineering", user_count=25)],
    )
    structured = NetworkRequirements(
        user_provided=UserFacts(sites=[site], total_user_count=0),
        design_goals=["Keep it simple"],
    )
    text = (
        "Engineering has 25 users and Sales has 12 users, with a total of "
        "37 users. Keep it simple."
    )
    provider = FakeProvider(
        [
            extraction(
                organization_name="Acme",
                site_name="Headquarters",
                departments=[
                    {"name": "Engineering", "user_count": 25},
                    {"name": "Sales", "user_count": 12},
                ],
                total_user_count=37,
            )
        ]
    )
    output, _ = run_agent(
        RequirementsUnderstandingAgent(provider),
        RequirementsAgentInput(free_text=text, requirements=structured),
    )

    assert output.status is RequirementsAgentStatus.parsed
    assert output.contradictions == []
    assert output.facts is not None
    assert sorted((d.name, d.user_count) for d in all_departments(output.facts)) == [
        ("Engineering", 25),
        ("Sales", 12),
    ]
    assert output.facts.organization is not None
    assert output.facts.organization.name == "Acme"
    assert output.requirements is not None
    assert output.requirements.design_goals == ["Keep it simple"]


def test_oversized_free_text_is_rejected_at_the_input_boundary() -> None:
    agent = RequirementsUnderstandingAgent(provider=None)
    with pytest.raises(AgentValidationError):
        agent.validate_input(
            {"free_text": "x" * (MAX_REQUIREMENTS_TEXT_CHARS + 1)}
        )


def test_department_count_above_the_bound_is_rejected() -> None:
    departments = [
        {"name": f"Department {index}", "user_count": 1}
        for index in range(MAX_REQUIREMENTS_DEPARTMENTS + 1)
    ]
    provider = FakeProvider([extraction(departments=departments)])
    agent = RequirementsUnderstandingAgent(provider, max_repair_retries=0)
    output, _ = run_agent(
        agent,
        RequirementsAgentInput(free_text="A network for many departments."),
    )

    assert output.status is RequirementsAgentStatus.failed
    assert output.requirements is None


def test_tool_allowlist_is_exactly_the_requirements_validator() -> None:
    assert RequirementsUnderstandingAgent.allowed_tools == frozenset(
        {"requirements_validate"}
    )
