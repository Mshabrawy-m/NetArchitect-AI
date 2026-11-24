"""Documentation Agent tests (Phase 10c).

The tests run the real deterministic workflow, then inspect the collected
report. A scripted :class:`FakeProvider` stands in for the optional explanation
model; no network request is made and the deterministic path needs no provider.
"""

from __future__ import annotations

import csv
import io
import json

from agents import (
    DocumentationAgent,
    DocumentationOutput,
    Orchestrator,
    export_csv,
    export_json,
    export_markdown,
    run_structured_design,
)
from agents.network_agents import default_agents
from agents.planning import (
    REDUNDANCY_ASSUMPTION_DESCRIPTION,
    REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION,
)
from core.exceptions import LLMProviderError
from core.schemas.requirements import Assumption
from services.llm.testing import FakeProvider
from tests.unit.agents.helpers import sample_requirements


def documented_state(provider: FakeProvider | None = None):
    """Run the standard plan with an injectable documentation provider."""
    agents = {**default_agents(), "documentation": DocumentationAgent(provider)}
    return Orchestrator(agents=agents).run_structured(sample_requirements())


def requirements_with_assumption():
    return sample_requirements().model_copy(
        update={
            "assumptions": [
                Assumption(
                    id="assumption-1",
                    category="traffic",
                    description="Demand is modeled at ten percent of users.",
                    rationale="No measured traffic was supplied.",
                )
            ]
        }
    )


def test_documentation_runs_last_in_a_complete_plan_without_a_provider() -> None:
    state = run_structured_design(sample_requirements())

    assert state.stop_reason.value == "completed"
    assert state.steps == 11
    report = state.results["documentation"]
    assert isinstance(report, DocumentationOutput)
    assert report.provider_used is False
    assert report.ai_explanation == ""
    assert report.verdict == "APPROVED"
    assert "critic verdict APPROVED" in report.summary
    assert [section.title for section in report.sections] == [
        "Requirements",
        "Topology",
        "IP addressing and VLANs",
        "Routing",
        "Simulation",
        "Optimization",
        "Critic review",
    ]


def test_addressing_table_matches_the_ip_engine() -> None:
    state = run_structured_design(sample_requirements())
    report = state.results["documentation"]
    plan = state.results["ip_vlan"].plan

    table = next(
        table
        for table in report.tables
        if table.title == "Addressing and VLAN allocation"
    )
    assert table.columns == ["Department", "Subnet", "VLAN", "Purpose"]
    assert table.rows == [
        [
            assignment.department,
            str(assignment.network),
            str(assignment.vlan_id),
            assignment.purpose or "-",
        ]
        for assignment in plan.vlan_plan.assignments
    ]
    assert table.step == "ip_vlan"
    assert table.tool == "ip_plan_from_requirements"


def test_routing_and_topology_values_match_the_engines() -> None:
    state = run_structured_design(sample_requirements())
    report = state.results["documentation"]
    routing = state.results["routing"]
    topology = state.results["topology"].topology

    routing_table = next(
        table for table in report.tables if table.title == "Routing path"
    )
    assert routing_table.rows == [
        [
            routing.source,
            routing.destination,
            str(routing.path.reachable),
            f"{routing.path.total_cost:.2f}",
            str(routing.path.hop_count),
        ]
    ]
    topology_section = next(
        section for section in report.sections if section.title == "Topology"
    )
    values = {value.label: value.value for value in topology_section.values}
    assert values["Devices"] == str(len(topology.devices))
    assert values["Links"] == str(len(topology.links))


def test_every_number_carries_step_and_tool_provenance() -> None:
    report = run_structured_design(sample_requirements()).results["documentation"]

    for section in report.sections:
        assert section.step
        for value in section.values:
            assert value.step
            assert value.tool
    for table in report.tables:
        assert table.step
        assert table.tool


def test_critic_findings_are_copied_not_recomputed() -> None:
    state = run_structured_design(sample_requirements())
    report = state.results["documentation"]
    critic = state.results["critic"]

    findings = next(
        table for table in report.tables if table.title == "Critic findings"
    ) if any(table.title == "Critic findings" for table in report.tables) else None
    if critic.findings:
        assert findings is not None
        assert len(findings.rows) == len(critic.findings)
    else:
        assert findings is None
    assert report.verdict == critic.verdict.value


def test_assumptions_and_limitations_are_separate() -> None:
    agents = {**default_agents()}
    state = Orchestrator(agents=agents).run_structured(requirements_with_assumption())
    report = state.results["documentation"]

    assert any("ten percent" in item for item in report.assumptions)
    assert any("modeled estimates" in item for item in report.limitations)
    assert any("no PDF" in item for item in report.limitations)
    assert not any("modeled estimates" in item for item in report.assumptions)


def test_topology_repair_assumption_is_reported_with_provenance() -> None:
    requirements = sample_requirements()
    requirements.design_goals.append("Provide resilience and failover.")

    state = run_structured_design(requirements)
    report = state.results["documentation"]

    assert state.stop_reason.value == "completed"
    assert any(
        REDUNDANCY_ASSUMPTION_DESCRIPTION in item
        and "topology_from_requirements" in item
        and "design_goals" in item
        for item in report.assumptions
    )
    assert not any(
        REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION in item
        for item in report.assumptions
    )


def test_redundancy_disabled_assumption_is_reported_with_provenance() -> None:
    state = run_structured_design(sample_requirements())
    report = state.results["documentation"]

    assert any(
        REDUNDANCY_DISABLED_ASSUMPTION_DESCRIPTION in item
        and "design_goals" in item
        and "user_provided.constraints" in item
        for item in report.assumptions
    )


def test_hostile_model_number_is_rejected_and_replaced() -> None:
    provider = FakeProvider(["The design serves 9999 users on 4 devices."])
    state = documented_state(provider)

    report = state.results["documentation"]
    assert report.provider_used is True
    assert report.ai_rejected is True
    assert report.ai_explanation == report.deterministic_explanation
    assert "does not match the computed results" in report.ai_note
    assert "9999" not in report.ai_explanation


def test_model_text_with_computed_numbers_is_kept() -> None:
    provider = FakeProvider(
        ["The design covers 37 reported users across 4 devices and 3 links."]
    )
    state = documented_state(provider)

    report = state.results["documentation"]
    assert report.ai_rejected is False
    assert report.ai_explanation.startswith("The design covers 37")
    assert report.ai_note == ""


def test_provider_failure_does_not_block_the_report() -> None:
    provider = FakeProvider([LLMProviderError("provider is down")])
    state = documented_state(provider)

    report = state.results["documentation"]
    assert report.provider_used is False
    assert report.ai_explanation == ""
    assert "unavailable" in report.ai_note


def test_exports_round_trip() -> None:
    report = run_structured_design(sample_requirements()).results["documentation"]

    payload = json.loads(export_json(report))
    assert payload["verdict"] == "APPROVED"
    assert DocumentationOutput.model_validate(payload) == report

    rows = list(csv.reader(io.StringIO(export_csv(report))))
    assert rows[0] == ["table", "row", "column", "value", "step", "tool"]
    expected_cells = sum(len(row) for table in report.tables for row in table.rows)
    assert len(rows) - 1 == expected_cells
    assert {row[4] for row in rows[1:]} >= {"ip_vlan", "routing", "orchestrator"}

    markdown = export_markdown(report)
    assert markdown.startswith("# NetArchitect AI design report")
    assert "## Assumptions" in markdown
    assert "## Limitations" in markdown
    assert "## Execution trace" in markdown
    assert "Source: `ip_vlan/ip_plan_from_requirements`" in markdown


def test_rejected_explanation_is_labelled_in_markdown() -> None:
    provider = FakeProvider(["There are 9999 users."])
    report = documented_state(provider).results["documentation"]

    markdown = export_markdown(report)
    assert "rejected and replaced deterministically" in markdown
    assert "rejected because it contained a number" in markdown
    assert "9999" not in markdown


def test_trace_is_included_and_matches_the_workflow() -> None:
    state = run_structured_design(sample_requirements())
    report = state.results["documentation"]

    assert report.trace
    assert report.trace[0].action == "workflow_started"
    assert any(entry.agent == "critic" for entry in report.trace)
    trace_table = next(
        table for table in report.tables if table.title == "Execution trace"
    )
    assert len(trace_table.rows) == len(report.trace)
    assert trace_table.columns[-1] == "Duration (s)"


def test_tool_allowlist_is_empty() -> None:
    assert DocumentationAgent.allowed_tools == frozenset()


def test_documentation_module_has_no_execution_or_network_imports() -> None:
    from pathlib import Path

    import agents.documentation as documentation_module

    source = Path(documentation_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "streamlit",
        "urllib",
        "http.client",
    ):
        assert forbidden not in source
