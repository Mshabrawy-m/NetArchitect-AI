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
from capacity import CapacityRun, DemandMapping, evaluate_capacity
from core.exceptions import LLMProviderError
from core.schemas.scenario import ScenarioType
from digital_twin import DigitalTwin
from forecasting import DataProvenance
from network.analysis import analyze_topology
from network.routing import reachability_matrix, routing_table
from optimization import (
    Algorithm,
    ObjectiveKind,
    ObjectiveSpec,
    ParetoReranking,
    SensitivityReport,
    SensitivityScenario,
    analyze_sensitivity,
    rerank_pareto_front,
    run_optimization,
)
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
from simulation import (
    DEFAULT_COMPARISON_MODES,
    FailureSweepResult,
    RoutingModeComparison,
    compare_routing_modes,
    run_failure_sweep,
    run_scenario,
    twin_fingerprint,
)
from simulation.scenarios import ScenarioRun
from tests.unit.agents.helpers import sample_requirements
from tests.unit.capacity.helpers import constant_run, line_capacity_twin
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
    "capacity",
    "optimization",
    "failure_sweep",
    "mode_comparison",
    "sensitivity",
    "reranking",
    "security",
    "assumptions",
    "limitations",
    "agent_trace",
)


def value(document: ReportDocument, key: str):
    """Return one sourced value record by key."""
    return next(record for record in document.values if record.key == key)


def warning_texts(section: ReportSection) -> list[str]:
    """Return visible warning-note text from one report section."""
    return [
        block.text
        for block in section.blocks
        if getattr(block, "kind", "") == "note"
        and getattr(block, "severity", "") == "warning"
    ]


def renamed_twin(twin: DigitalTwin) -> DigitalTwin:
    """Return a twin with one metadata change, so its fingerprint differs."""
    # A metadata name change is a new twin revision (different SHA-256 input)
    # without changing any topology, demand, or engine result.
    metadata = twin.metadata.model_copy(update={"name": "Current revised twin"})
    return twin.model_copy(update={"metadata": metadata})


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


@pytest.fixture(scope="module")
def capacity_case() -> tuple[DigitalTwin, CapacityRun]:
    twin = line_capacity_twin()
    forecast = constant_run(
        30.0,
        2,
        series_id="subscribers",
        provenance=DataProvenance.synthetic,
    )
    mapping = DemandMapping(
        series_to_demand={"subscribers": "call"},
        per_user_mbps=1.0,
    )
    return twin, evaluate_capacity(twin, forecast, mapping)


@pytest.fixture(scope="module")
def e5_case() -> tuple[
    DigitalTwin,
    FailureSweepResult,
    RoutingModeComparison,
    SensitivityReport,
    ParetoReranking,
]:
    """One small twin and four bounded E5 results derived from it."""
    twin = tiny_twin(capacity_mbps=40.0)
    objectives = (
        ObjectiveSpec(
            kind=ObjectiveKind.infrastructure_cost,
            weight=0.5,
            lower_bound=0.0,
            upper_bound=500.0,
        ),
        ObjectiveSpec(
            kind=ObjectiveKind.max_utilization,
            weight=0.5,
            lower_bound=0.0,
            upper_bound=200.0,
        ),
    )
    config = settings(objectives=objectives, max_iterations=8, max_evaluations=250)
    run = run_optimization(twin, config, Algorithm.nsga2)
    return (
        twin,
        run_failure_sweep(twin, limit=2),
        compare_routing_modes(twin),
        analyze_sensitivity(
            twin,
            run,
            scenarios=(
                SensitivityScenario(
                    id="demand_up",
                    label="Higher demand",
                    demand_multiplier=1.25,
                ),
                SensitivityScenario(
                    id="capacity_down",
                    label="Lower capacity",
                    capacity_multiplier=0.8,
                ),
            ),
        ),
        rerank_pareto_front(run),
    )


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
        ("capacity", "Capacity Planning"),
        ("optimization", "Optimization Center"),
        ("failure_sweep", "Simulation Lab"),
        ("mode_comparison", "Simulation Lab"),
        ("sensitivity", "Optimization Center"),
        ("reranking", "Optimization Center"),
        ("security", "Security Analysis"),
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


def test_capacity_values_equal_the_run(
    capacity_case: tuple[DigitalTwin, CapacityRun],
) -> None:
    twin, capacity_run = capacity_case
    document = build_report(
        ReportSources(
            twin=twin,
            capacity_run=capacity_run,
            generated_at=GENERATED_AT,
        )
    )
    section = document.section("capacity")
    assert section.status.value == "available"
    assert value(document, "capacity.projected_steps").numeric == len(
        capacity_run.steps
    )
    assert value(document, "capacity.mapped_demands").numeric == len(
        capacity_run.projection.demands
    )
    assert value(document, "capacity.data_label").display == "SYNTHETIC"
    assert value(document, "capacity.crossing_count").numeric == len(
        capacity_run.crossings
    )
    assert value(document, "capacity.cost_delta").numeric == pytest.approx(
        capacity_run.total_cost_delta
    )
    record = value(document, "capacity.data_label")
    assert record.provenance.step == "capacity"
    assert record.provenance.tool == "capacity.engine.evaluate_capacity"
    assert record.provenance.twin_version == capacity_run.twin_fingerprint
    assert check_consistency(document).ok


def test_tampered_capacity_number_is_detected(
    capacity_case: tuple[DigitalTwin, CapacityRun],
) -> None:
    twin, capacity_run = capacity_case
    document = build_report(
        ReportSources(
            twin=twin,
            capacity_run=capacity_run,
            generated_at=GENERATED_AT,
        )
    )
    section = document.section("capacity")
    paragraph = section.blocks[0]
    tampered_block = paragraph.model_copy(
        update={
            "text": paragraph.text
            + " An invented measurement reported 987654321 Mbps."
        }
    )
    tampered = document.model_copy(
        update={
            "sections": tuple(
                section.model_copy(update={"blocks": (tampered_block, *section.blocks[1:])})
                if item.id == "capacity"
                else item
                for item in document.sections
            )
        }
    )

    result = check_consistency(tampered)
    assert not result.ok
    assert any(
        finding.code is ConsistencyCode.orphan_number
        and finding.section_id == "capacity"
        and finding.token == "987654321"
        for finding in result.findings
    )


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


def test_simulation_report_warns_on_source_fingerprint_mismatch(
    scenario_case: tuple[DigitalTwin, ScenarioRun],
) -> None:
    source_twin, scenario_run = scenario_case
    current_twin = renamed_twin(source_twin)
    # The run was produced from source_twin; reporting it against current_twin
    # is a revision mismatch even though the modeled topology is unchanged.
    source_fingerprint = scenario_run.baseline_twin.fingerprint
    current_fingerprint = twin_fingerprint(current_twin)
    assert source_fingerprint != current_fingerprint

    document = build_report(
        ReportSources(
            twin=current_twin,
            scenario_run=scenario_run,
            generated_at=GENERATED_AT,
        )
    )
    warnings = warning_texts(document.section("simulation"))
    assert any(
        "Source twin mismatch" in text
        and source_fingerprint in text
        and current_fingerprint in text
        for text in warnings
    )
    assert check_consistency(document).ok


def test_capacity_report_warns_on_source_fingerprint_mismatch(
    capacity_case: tuple[DigitalTwin, CapacityRun],
) -> None:
    source_twin, capacity_run = capacity_case
    current_twin = renamed_twin(source_twin)
    # Same arithmetic as above: the stored run identifies its original twin.
    source_fingerprint = capacity_run.twin_fingerprint
    current_fingerprint = twin_fingerprint(current_twin)
    assert source_fingerprint != current_fingerprint

    document = build_report(
        ReportSources(
            twin=current_twin,
            capacity_run=capacity_run,
            generated_at=GENERATED_AT,
        )
    )
    warnings = warning_texts(document.section("capacity"))
    assert any(
        "Source twin mismatch" in text
        and source_fingerprint in text
        and current_fingerprint in text
        for text in warnings
    )
    assert check_consistency(document).ok


def test_optimization_report_warns_on_source_fingerprint_mismatch() -> None:
    source_twin = tiny_twin()
    current_twin = renamed_twin(source_twin)
    optimization_run = run_optimization(source_twin, settings(), Algorithm.greedy)
    # OptimizationRun has no persisted fingerprint, so the UI records it when
    # the run is created and supplies it to the report builder.
    source_fingerprint = twin_fingerprint(source_twin)
    current_fingerprint = twin_fingerprint(current_twin)
    assert source_fingerprint != current_fingerprint

    document = build_report(
        ReportSources(
            twin=current_twin,
            optimization_run=optimization_run,
            optimization_source_fingerprint=source_fingerprint,
            generated_at=GENERATED_AT,
        )
    )
    warnings = warning_texts(document.section("optimization"))
    assert any(
        "Source twin mismatch" in text
        and source_fingerprint in text
        and current_fingerprint in text
        for text in warnings
    )
    assert check_consistency(document).ok


def test_e5_sections_are_available_with_engine_values_and_provenance(
    e5_case: tuple[
        DigitalTwin,
        FailureSweepResult,
        RoutingModeComparison,
        SensitivityReport,
        ParetoReranking,
    ],
) -> None:
    twin, sweep, comparison, sensitivity, reranking = e5_case
    source_fingerprint = twin_fingerprint(twin)
    document = build_report(
        ReportSources(
            twin=twin,
            failure_sweep=sweep,
            mode_comparison=comparison,
            sensitivity_report=sensitivity,
            reranking=reranking,
            rerank_source_fingerprint=source_fingerprint,
            generated_at=GENERATED_AT,
        )
    )

    for section_id in ("failure_sweep", "mode_comparison", "sensitivity", "reranking"):
        section = document.section(section_id)
        assert section is not None
        assert section.status.value == "available"
        assert section.blocks

    assert value(document, "failure_sweep.total_cases").numeric == sweep.total_cases
    assert value(document, "failure_sweep.evaluated_cases").numeric == (
        sweep.evaluated_cases
    )
    assert value(document, "failure_sweep.stop_reason").display == (
        sweep.stop_reason.value
    )
    assert value(document, "failure_sweep.case.0.rank").numeric == sweep.cases[0].rank
    assert value(document, "failure_sweep.case.0.served").numeric == (
        sweep.cases[0].state.served_demand_count
    )

    assert value(document, "mode_comparison.mode_count").numeric == len(
        DEFAULT_COMPARISON_MODES
    )
    assert value(document, "mode_comparison.mode.0").display == (
        comparison.results[0].mode.value
    )
    assert value(document, "mode_comparison.served.0").numeric == (
        comparison.results[0].state.served_demand_count
    )

    assert value(document, "sensitivity.evaluated_candidates").numeric == (
        sensitivity.evaluated_candidates
    )
    assert value(document, "sensitivity.evaluations").numeric == (
        sensitivity.evaluations
    )
    assert value(document, "sensitivity.robust_count").numeric == len(
        sensitivity.robust_candidate_hashes
    )

    assert value(document, "reranking.source_evaluations").numeric == (
        reranking.source_evaluations
    )
    assert value(document, "reranking.items").numeric == len(reranking.items)
    assert value(document, "reranking.source_seed").numeric == reranking.source_seed
    recommendation = (
        reranking.recommended_candidate_hash[:12]
        if reranking.recommended_candidate_hash
        else "none"
    )
    recommend_item = next(
        item
        for block in document.section("reranking").blocks
        for item in getattr(block, "items", ())
        if item.key == "recommendation"
    )
    assert recommend_item.value == recommendation

    e5_prefixes = ("failure_sweep.", "mode_comparison.", "sensitivity.", "reranking.")
    e5_values = [
        record for record in document.values if record.key.startswith(e5_prefixes)
    ]
    assert e5_values
    for record in e5_values:
        assert record.provenance.step
        assert record.provenance.tool
        assert record.provenance.twin_version
    for key, step, tool, version in (
        (
            "failure_sweep.total_cases",
            "simulation",
            "simulation.plan_failure_sweep",
            sweep.baseline.fingerprint,
        ),
        (
            "failure_sweep.evaluated_cases",
            "simulation",
            "simulation.run_failure_sweep",
            sweep.baseline.fingerprint,
        ),
        (
            "mode_comparison.mode_count",
            "simulation",
            "simulation.compare_routing_modes",
            comparison.twin.fingerprint,
        ),
        (
            "mode_comparison.served.0",
            "simulation",
            "simulation.evaluate",
            comparison.twin.fingerprint,
        ),
        (
            "sensitivity.evaluated_candidates",
            "optimization",
            "optimization.analyze_sensitivity",
            sensitivity.source_twin_fingerprint,
        ),
        (
            "sensitivity.evaluations",
            "optimization",
            "optimization.analyze_sensitivity",
            sensitivity.source_twin_fingerprint,
        ),
        (
            "reranking.source_evaluations",
            "optimization",
            "optimization.rerank_pareto_front",
            source_fingerprint,
        ),
        (
            "reranking.items",
            "optimization",
            "optimization.ParetoReranking",
            source_fingerprint,
        ),
    ):
        record = value(document, key)
        assert record.provenance.step == step
        assert record.provenance.tool == tool
        assert record.provenance.twin_version == version
    assert check_consistency(document).ok


def test_e5_source_fingerprints_come_from_models_and_passed_values(
    e5_case: tuple[
        DigitalTwin,
        FailureSweepResult,
        RoutingModeComparison,
        SensitivityReport,
        ParetoReranking,
    ],
) -> None:
    twin, sweep, comparison, sensitivity, reranking = e5_case
    source_fingerprint = twin_fingerprint(twin)
    assert source_fingerprint == sweep.baseline.fingerprint
    assert source_fingerprint == comparison.twin.fingerprint
    assert source_fingerprint == sensitivity.source_twin_fingerprint

    document = build_report(
        ReportSources(
            twin=twin,
            failure_sweep=sweep,
            mode_comparison=comparison,
            sensitivity_report=sensitivity,
            sensitivity_source_fingerprint=sensitivity.source_twin_fingerprint,
            reranking=reranking,
            rerank_source_fingerprint=source_fingerprint,
            generated_at=GENERATED_AT,
        )
    )
    assert (
        value(document, "failure_sweep.total_cases").provenance.twin_version
        == sweep.baseline.fingerprint
    )
    assert (
        value(document, "mode_comparison.mode_count").provenance.twin_version
        == comparison.twin.fingerprint
    )
    assert (
        value(document, "sensitivity.evaluated_candidates").provenance.twin_version
        == sensitivity.source_twin_fingerprint
    )
    assert (
        value(document, "reranking.source_evaluations").provenance.twin_version
        == source_fingerprint
    )
    assert (
        value(document, "reranking.items").provenance.twin_version
        == source_fingerprint
    )
    assert check_consistency(document).ok


def test_e5_sections_warn_on_stale_source_fingerprint(
    e5_case: tuple[
        DigitalTwin,
        FailureSweepResult,
        RoutingModeComparison,
        SensitivityReport,
        ParetoReranking,
    ],
) -> None:
    source_twin, sweep, comparison, sensitivity, reranking = e5_case
    current_twin = renamed_twin(source_twin)
    source_fingerprint = twin_fingerprint(source_twin)
    current_fingerprint = twin_fingerprint(current_twin)
    assert source_fingerprint != current_fingerprint

    document = build_report(
        ReportSources(
            twin=current_twin,
            failure_sweep=sweep,
            mode_comparison=comparison,
            sensitivity_report=sensitivity,
            sensitivity_source_fingerprint=source_fingerprint,
            reranking=reranking,
            rerank_source_fingerprint=source_fingerprint,
            generated_at=GENERATED_AT,
        )
    )
    for section_id in ("failure_sweep", "mode_comparison", "sensitivity", "reranking"):
        warnings = warning_texts(document.section(section_id))
        assert any(
            "Source twin mismatch" in text
            and source_fingerprint in text
            and current_fingerprint in text
            for text in warnings
        ), (section_id, warnings)
    assert (
        value(document, "sensitivity.source_warning").provenance.twin_version
        == source_fingerprint
    )
    assert (
        value(document, "reranking.source_warning").provenance.twin_version
        == source_fingerprint
    )
    assert check_consistency(document).ok


def test_e5_sections_stay_not_run_without_their_own_source(
    e5_case: tuple[
        DigitalTwin,
        FailureSweepResult,
        RoutingModeComparison,
        SensitivityReport,
        ParetoReranking,
    ],
) -> None:
    twin, sweep, _, _, _ = e5_case
    document = build_report(
        ReportSources(twin=twin, failure_sweep=sweep, generated_at=GENERATED_AT)
    )
    assert document.section("failure_sweep").status.value == "available"
    for section_id, producer_page in (
        ("mode_comparison", "Simulation Lab"),
        ("sensitivity", "Optimization Center"),
        ("reranking", "Optimization Center"),
    ):
        section = document.section(section_id)
        assert section is not None
        assert section.status.value == "not_run"
        assert section.unavailable_reason
        assert section.producer_page == producer_page
        assert section.blocks == ()


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
