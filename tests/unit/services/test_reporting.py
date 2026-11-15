"""Report builder, consistency, and explanation tests (Phase 11a).

The tests build reports from the real deterministic engines and from the real
structured workflow. A scripted :class:`FakeProvider` stands in for the optional
explanation model; no network request is made.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents import run_structured_design
from core.exceptions import LLMProviderError
from core.schemas.scenario import ScenarioType
from digital_twin import DigitalTwin
from network.analysis import analyze_topology
from network.routing import reachability_matrix, routing_table
from optimization import Algorithm, run_optimization
from services.llm.testing import FakeProvider
from services.reporting import (
    DISCLOSURE_TEXT,
    MODELED_ESTIMATE_LABEL,
    REQUIRED_LABELS,
    AIExplanation,
    ConsistencyCode,
    ConsistencySeverity,
    Provenance,
    ReportDocument,
    ReportSection,
    ReportSources,
    TableBlock,
    build_report,
    check_consistency,
    filter_sections,
    format_number,
    generate_ai_explanation,
    numeric_tokens,
)
from simulation import run_scenario
from simulation.scenarios import ScenarioRun
from tests.unit.agents.helpers import sample_requirements
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.optimization.helpers import settings, tiny_twin
from tests.unit.simulation.helpers import line_twin, make_demand, make_scenario

GENERATED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

SECTION_IDS = (
    "architecture_summary",
    "topology",
    "addressing",
    "vlan_dhcp",
    "routing",
    "graph_analysis",
    "simulation",
    "optimization",
    "assumptions",
    "limitations",
    "agent_trace",
)


def value(document: ReportDocument, key: str):
    """Return one sourced value record by key."""
    return next(record for record in document.values if record.key == key)


@pytest.fixture(scope="module")
def twin():
    return make_twin()


@pytest.fixture(scope="module")
def base_report(twin) -> ReportDocument:
    return build_report(ReportSources(twin=twin, generated_at=GENERATED_AT))


@pytest.fixture(scope="module")
def scenario_case() -> tuple[DigitalTwin, ScenarioRun]:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 80.0),))
    run = run_scenario(
        twin,
        make_scenario(ScenarioType.single_link_failure, affected_links=["ab"]),
    )
    return twin, run


def test_report_has_the_required_ordered_sections(base_report: ReportDocument) -> None:
    assert base_report.section_ids() == SECTION_IDS
    assert base_report.generated_at == GENERATED_AT
    assert base_report.twin.fingerprint
    assert base_report.twin.name == "Campus twin"


def test_sections_without_inputs_are_marked_not_run_with_a_pointer(
    base_report: ReportDocument,
) -> None:
    for section_id, producer_page in (
        ("simulation", "Simulation Lab"),
        ("optimization", "Optimization Center"),
        ("agent_trace", "AI Network Designer"),
    ):
        section = base_report.section(section_id)
        assert section is not None
        assert section.status.value == "not_run"
        assert section.unavailable_reason
        assert section.producer_page == producer_page
        assert section.blocks == ()


def test_summary_values_equal_the_twin_and_engines(
    base_report: ReportDocument, twin
) -> None:
    assert value(base_report, "architecture.device_count").numeric == len(
        twin.topology.devices
    )
    assert value(base_report, "architecture.link_count").numeric == len(
        twin.topology.links
    )
    assert value(base_report, "architecture.demand_count").numeric == len(
        twin.demands
    )
    assert value(base_report, "topology.total_capacity_mbps").numeric == sum(
        link.capacity_mbps for link in twin.topology.links
    )

    analysis = analyze_topology(twin.topology)
    assert value(base_report, "graph.component_count").numeric == (
        analysis.components.component_count
    )
    assert value(base_report, "graph.critical_device_count").numeric == len(
        analysis.critical_nodes.nodes
    )
    assert value(base_report, "graph.critical_link_count").numeric == len(
        analysis.critical_links.links
    )
    assert value(base_report, "architecture.spof_count").numeric == len(
        analysis.spof.entries
    )

    source = twin.demands[0].source
    matrix = reachability_matrix(twin.topology)
    table = routing_table(twin.topology, source)
    assert value(base_report, "routing.unreachable_pairs").numeric == (
        matrix.unreachable_pairs
    )
    assert value(base_report, "routing.entry_count").numeric == len(table.entries)


def test_addressing_values_equal_the_stored_plan(
    base_report: ReportDocument, twin
) -> None:
    plan = twin.addressing
    assert plan is not None
    stored = sum(len(vlan.subnets) for vlan in plan.vlan_plans) + len(plan.subnets)
    assert value(base_report, "addressing.subnet_count").numeric == stored
    assert value(base_report, "vlan.assignment_count").numeric == len(
        twin.vlan_plan.assignments
    )
    assert value(base_report, "dhcp.scope_count").numeric == len(twin.dhcp_scopes)


def test_every_value_has_step_tool_and_twin_version(base_report: ReportDocument) -> None:
    assert base_report.values
    for record in base_report.values:
        assert record.provenance.step
        assert record.provenance.tool
        assert record.provenance.twin_version


def test_report_is_deterministic_for_an_injected_clock(
    twin, base_report: ReportDocument
) -> None:
    rebuilt = build_report(ReportSources(twin=twin, generated_at=GENERATED_AT))
    assert rebuilt.model_dump() == base_report.model_dump()


def test_clean_report_passes_consistency(base_report: ReportDocument) -> None:
    result = check_consistency(base_report)
    assert result.ok, result.findings
    assert result.checked_numbers > 0
    assert result.checked_values == len(base_report.values)
    assert "numbers match" in result.summary()


def test_tampered_number_is_detected(base_report: ReportDocument) -> None:
    section = base_report.section("architecture_summary")
    assert section is not None
    paragraph = section.blocks[0]
    tampered_block = paragraph.model_copy(
        update={
            "text": paragraph.text
            + " Measured throughput of the live network was 987654321 Mbps."
        }
    )
    tampered_section = section.model_copy(
        update={"blocks": (tampered_block, *section.blocks[1:])}
    )
    tampered = base_report.model_copy(
        update={
            "sections": tuple(
                tampered_section if item.id == section.id else item
                for item in base_report.sections
            )
        }
    )

    result = check_consistency(tampered)
    assert not result.ok
    orphan = [
        finding
        for finding in result.findings
        if finding.code is ConsistencyCode.orphan_number
    ]
    assert orphan
    assert any(finding.token == "987654321" for finding in orphan)
    assert all(
        finding.severity is ConsistencySeverity.error for finding in orphan
    )


def test_missing_disclosure_label_is_detected(base_report: ReportDocument) -> None:
    tampered = base_report.model_copy(
        update={"labels": tuple(label for label in base_report.labels if label != DISCLOSURE_TEXT)}
    )
    result = check_consistency(tampered)
    assert not result.ok
    assert any(
        finding.code is ConsistencyCode.missing_label
        and DISCLOSURE_TEXT in finding.message
        for finding in result.findings
    )


def test_built_report_carries_every_required_label(
    base_report: ReportDocument,
) -> None:
    for label in REQUIRED_LABELS:
        assert label in base_report.labels
    assert MODELED_ESTIMATE_LABEL in base_report.labels


def test_table_truncation_reports_the_source_row_count() -> None:
    rows = tuple(("row", str(index)) for index in range(500))
    table = TableBlock(
        id="long_table",
        title="Long table",
        columns=("Name", "Value"),
        rows=rows,
        total_rows=600,
        provenance=Provenance(step="test", tool="tests", twin_version="abc"),
    )
    assert table.truncated
    assert table.truncation_note() == "Showing first 500 of 600 rows."


def test_builder_bounds_tables_to_the_configured_limit(
    monkeypatch: pytest.MonkeyPatch, twin
) -> None:
    monkeypatch.setattr("services.reporting.builder.MAX_REPORT_TABLE_ROWS", 1)
    document = build_report(ReportSources(twin=twin, generated_at=GENERATED_AT))
    table = next(
        block
        for block in document.tables()
        if block.id == "routing_table"
    )
    assert len(table.rows) == 1
    assert table.total_rows >= 2
    assert table.truncation_note().startswith("Showing first 1 of ")


def test_filter_sections_keeps_requested_order(
    base_report: ReportDocument,
) -> None:
    filtered = filter_sections(
        base_report, ["routing", "architecture_summary"]
    )
    assert filtered.section_ids() == ("architecture_summary", "routing")
    assert base_report.section_ids() == SECTION_IDS
    assert filtered.values == base_report.values


def test_not_run_section_requires_reason_and_producer_page() -> None:
    with pytest.raises(ValidationError):
        ReportSection(id="missing", title="Missing", status="not_run")


def test_duplicate_section_ids_are_rejected(base_report: ReportDocument) -> None:
    payload = base_report.model_dump()
    payload["sections"] = [*payload["sections"], payload["sections"][0]]
    with pytest.raises(ValidationError):
        ReportDocument.model_validate(payload)


def test_simulation_values_equal_the_scenario_run(
    scenario_case: tuple[DigitalTwin, ScenarioRun],
) -> None:
    twin, scenario_run = scenario_case
    document = build_report(
        ReportSources(
            twin=twin,
            scenario_run=scenario_run,
            generated_at=GENERATED_AT,
        )
    )
    assert document.section("simulation").status.value == "available"
    assert value(document, "simulation.baseline_served").numeric == (
        scenario_run.baseline_state.served_demand_count
    )
    assert value(document, "simulation.scenario_served").numeric == (
        scenario_run.scenario_state.served_demand_count
    )
    assert value(document, "simulation.max_utilization_delta").numeric == pytest.approx(
        scenario_run.comparison.max_utilization_delta_percent
    )
    assert value(document, "simulation.link.0.baseline_util") is not None
    assert check_consistency(document).ok


def test_optimization_values_equal_the_run() -> None:
    optimization_run = run_optimization(
        tiny_twin(), settings(), Algorithm.genetic
    )
    document = build_report(
        ReportSources(
            twin=tiny_twin(),
            optimization_run=optimization_run,
            generated_at=GENERATED_AT,
        )
    )
    assert document.section("optimization").status.value == "available"
    assert value(document, "optimization.seed").numeric == optimization_run.seed
    assert value(document, "optimization.evaluations").numeric == (
        optimization_run.evaluations
    )
    assert value(document, "optimization.candidate_count").numeric == len(
        optimization_run.candidates
    )
    assert value(document, "optimization.best_score").numeric == pytest.approx(
        optimization_run.best.evaluation.weighted_score
    )
    assert check_consistency(document).ok


def test_workflow_report_matches_the_execution_trace() -> None:
    workflow = run_structured_design(sample_requirements())
    assert workflow.current_twin is not None
    document = build_report(
        ReportSources(
            twin=workflow.current_twin,
            workflow=workflow,
            generated_at=GENERATED_AT,
        )
    )
    assert document.section("agent_trace").status.value == "available"
    assert value(document, "agent.steps").numeric == workflow.steps
    assert value(document, "agent.task_count").numeric == len(
        workflow.ordered_task_ids()
    )
    assert value(document, "agent.trace_count").numeric == len(
        workflow.trace.entries
    )
    assert check_consistency(document).ok


def test_ai_explanation_is_absent_without_a_provider(
    base_report: ReportDocument,
) -> None:
    explanation = generate_ai_explanation(base_report, None)
    assert explanation.provider_used is False
    assert explanation.text == ""


def test_ai_explanation_is_accepted_when_numbers_are_sourced(
    base_report: ReportDocument,
) -> None:
    provider = FakeProvider(
        ["The modeled campus uses 3 devices and 2 links."]
    )
    explanation = generate_ai_explanation(base_report, provider)
    assert explanation.provider_used is True
    assert explanation.rejected is False
    assert explanation.text == "The modeled campus uses 3 devices and 2 links."
    assert len(provider.calls) == 1


def test_ai_explanation_is_rejected_for_an_unsourced_number(
    base_report: ReportDocument,
) -> None:
    provider = FakeProvider(["Peak utilization reached 987654 percent."])
    explanation = generate_ai_explanation(base_report, provider)
    assert explanation.provider_used is True
    assert explanation.rejected is True
    assert explanation.text == ""
    assert "rejected" in explanation.note


def test_ai_provider_error_leaves_the_report_untouched(
    base_report: ReportDocument,
) -> None:
    provider = FakeProvider([LLMProviderError("provider unavailable")])
    explanation = generate_ai_explanation(base_report, provider)
    assert explanation.provider_used is False
    assert explanation.rejected is False
    assert explanation.text == ""
    assert "unavailable" in explanation.note


def test_ai_text_in_a_document_is_checked_like_any_other_text(
    base_report: ReportDocument,
) -> None:
    tampered = base_report.model_copy(
        update={
            "ai": AIExplanation(text="The network had 555555 failures."),
        }
    )
    result = check_consistency(tampered)
    assert any(
        finding.code is ConsistencyCode.orphan_number
        and finding.token == "555555"
        for finding in result.findings
    )


def test_number_formatting_and_token_masking() -> None:
    assert format_number(3.0) == "3"
    assert format_number(1.23456, digits=3) == "1.235"
    assert format_number(10.5) == "10.5"
    assert numeric_tokens("10.0.0.0/24 and site-1 and 4 devices") == ["4"]
