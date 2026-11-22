"""Executive-summary report tests (task B4).

The document is built from the same deterministic engines as the full report,
then checked for structure, Arabic parity, provenance, missing-input handling,
and exporter compatibility. No UI or exporter code is modified here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from capacity import CapacityRun, DemandMapping, evaluate_capacity
from core.schemas.network import Topology
from core.schemas.scenario import ScenarioType
from core.schemas.security import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
)
from digital_twin import DigitalTwin
from forecasting import DataProvenance
from security import SecurityAnalysis, analyze_design
from services.copilot import DecisionKind, DecisionLog, DecisionRecord
from services.export.json_export import from_json, to_json
from services.export.pdf import pdf_page_count, pdf_warnings, to_pdf
from services.reporting.builder import ReportSources, build_report
from services.reporting.consistency import check_consistency
from services.reporting.executive import (
    AR,
    EN,
    EXECUTIVE_SECTION_ID,
    LANGUAGES,
    build_executive_summary,
)
from services.reporting.formatting import format_number, numeric_tokens
from services.reporting.models import (
    DISCLOSURE_TEXT,
    MODELED_ESTIMATE_LABEL,
    KeyValueBlock,
    NoteBlock,
    ParagraphBlock,
    ReportDocument,
    ReportSection,
    TableBlock,
)
from simulation import FailureSweepResult, run_failure_sweep, run_scenario
from simulation.scenarios import ScenarioRun
from tests.unit.capacity.helpers import constant_run
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.simulation.helpers import make_scenario

GENERATED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
FILLED_BLOCK_KINDS = (
    "paragraph",
    "key_value",
    "table",
    "key_value",
    "table",
    "key_value",
    "paragraph",
)


@dataclass(frozen=True)
class Case:
    """One populated, deterministic executive-summary input set."""

    sources: ReportSources
    twin: DigitalTwin
    scenario_run: ScenarioRun
    sweep: FailureSweepResult
    analysis: SecurityAnalysis
    capacity_run: CapacityRun
    decisions: tuple[DecisionRecord, ...]


def value(document: ReportDocument, key: str):
    """Return one sourced value record by key."""
    return next(record for record in document.values if record.key == key)


def executive_section(document: ReportDocument) -> ReportSection:
    """Return the report's only section."""
    assert document.section_ids() == (EXECUTIVE_SECTION_ID,)
    section = document.section(EXECUTIVE_SECTION_ID)
    assert section is not None
    return section


def block_by_id(document: ReportDocument, table_id: str) -> TableBlock:
    """Return one table block by its stable id."""
    return next(
        block
        for block in executive_section(document).blocks
        if isinstance(block, TableBlock) and block.id == table_id
    )


def visible_text(document: ReportDocument) -> str:
    """Return every string the executive section prints."""
    pieces = [document.title, document.subtitle]
    for section in document.sections:
        pieces.extend([section.title, section.unavailable_reason, section.producer_page])
        for block in section.blocks:
            if isinstance(block, (ParagraphBlock, NoteBlock)):
                pieces.append(block.text)
            elif isinstance(block, KeyValueBlock):
                pieces.append(block.title)
                for item in block.items:
                    pieces.extend([item.key, item.value, item.unit])
            elif isinstance(block, TableBlock):
                pieces.append(block.title)
                pieces.extend(block.columns)
                for row in block.rows:
                    pieces.extend(row)
    return " ".join(pieces)


def printed_numeric_tokens(document: ReportDocument) -> list[str]:
    """Return sorted numeric tokens from everything the section prints."""
    tokens: list[str] = []
    for section in document.sections:
        for block in section.blocks:
            if isinstance(block, (ParagraphBlock, NoteBlock)):
                tokens.extend(numeric_tokens(block.text))
            elif isinstance(block, KeyValueBlock):
                for item in block.items:
                    tokens.extend(numeric_tokens(item.key))
                    tokens.extend(numeric_tokens(item.value))
                    tokens.extend(numeric_tokens(item.unit))
            elif isinstance(block, TableBlock):
                tokens.extend(numeric_tokens(block.title))
                for column in block.columns:
                    tokens.extend(numeric_tokens(column))
                for row in block.rows:
                    for cell in row:
                        tokens.extend(numeric_tokens(cell))
    return sorted(tokens)


def decision_record(*, suffix: str, hour: int, title: str) -> DecisionRecord:
    """Build one deterministic decision record with real fingerprints."""
    return DecisionRecord(
        kind=DecisionKind.suggestion_accepted,
        subject_id=f"link-{suffix}",
        title=title,
        page="Optimization Center",
        source_fingerprint=sha256(f"source-{suffix}".encode()).hexdigest(),
        result_fingerprint=sha256(f"result-{suffix}".encode()).hexdigest(),
        created_at=datetime(2026, 11, 15, hour, 0, tzinfo=UTC),
    )


@pytest.fixture(scope="module")
def case() -> Case:
    """Build one twin with simulation, failure, security, capacity, and decisions."""
    model = SecurityModel(
        zones=(
            Zone(
                id="z1",
                name="Users",
                type=ZoneType.user,
                criticality=3,
                member_device_ids=("sw1",),
            ),
        ),
        services=(
            Service(name="http", protocol=Protocol.tcp, port_start=80, port_end=80),
        ),
        rules=(
            FirewallRule(
                id="allow-http",
                order=0,
                src_zone="z1",
                dst_zone="z1",
                services=("http",),
                action=PolicyAction.allow,
            ),
        ),
    )
    twin = make_twin(security=model)
    analysis = analyze_design(twin)
    scenario_run = run_scenario(
        twin,
        make_scenario(
            ScenarioType.single_link_failure,
            affected_links=["l2"],
        ),
    )
    sweep = run_failure_sweep(twin, limit=2)
    forecast = constant_run(
        150.0,
        2,
        series_id="subscribers",
        provenance=DataProvenance.synthetic,
    )
    capacity_run = evaluate_capacity(
        twin,
        forecast,
        DemandMapping(
            series_to_demand={"subscribers": "client-to-server"},
            per_user_mbps=1.0,
        ),
    )
    decisions = (
        decision_record(suffix="a", hour=12, title="Raise capacity on l2"),
        decision_record(suffix="b", hour=13, title="Accept security proposal"),
    )
    log = DecisionLog()
    log.records = decisions
    sources = ReportSources(
        twin=twin,
        scenario_run=scenario_run,
        security_analysis=analysis,
        failure_sweep=sweep,
        capacity_run=capacity_run,
        decisions=log,
        generated_at=GENERATED_AT,
    )
    return Case(
        sources=sources,
        twin=twin,
        scenario_run=scenario_run,
        sweep=sweep,
        analysis=analysis,
        capacity_run=capacity_run,
        decisions=decisions,
    )


def test_public_api_and_bilingual_labels(case: Case) -> None:
    assert EXECUTIVE_SECTION_ID == "executive_summary"
    assert LANGUAGES == ("en", "ar")
    assert set(EN) == set(AR)
    assert all(text.strip() for text in (*EN.values(), *AR.values()))

    arabic_text = "".join(AR.values())
    assert any("\u0600" <= char <= "\u06ff" for char in arabic_text)
    assert not any("\u0660" <= char <= "\u0669" for char in arabic_text)
    assert not any("\u06f0" <= char <= "\u06f9" for char in arabic_text)

    with pytest.raises(ValueError, match="Unsupported executive summary language"):
        build_executive_summary(case.sources, language="fr")


def test_populated_document_has_exactly_seven_bounded_blocks(case: Case) -> None:
    document = build_executive_summary(case.sources)
    section = executive_section(document)

    assert document.generated_at == GENERATED_AT
    assert section.title == EN["section"]
    assert tuple(block.kind for block in section.blocks) == FILLED_BLOCK_KINDS
    assert all(getattr(block, "text", "") or getattr(block, "items", None) or getattr(block, "rows", None) for block in section.blocks)

    assert value(document, "executive.device_count").numeric == len(
        case.twin.topology.devices
    )
    assert value(document, "executive.link_count").numeric == len(
        case.twin.topology.links
    )
    assert value(document, "executive.served_demand_count").numeric == (
        case.scenario_run.baseline_state.served_demand_count
    )
    assert value(document, "executive.max_utilization_percent").numeric == (
        case.scenario_run.baseline_state.max_utilization_percent
    )
    assert value(document, "executive.capacity.horizon").numeric == (
        case.capacity_run.projection.horizon
    )

    risks = block_by_id(document, "executive_top_risks")
    total_risks = len(case.sweep.cases) + len(case.analysis.findings)
    assert risks.total_rows == total_risks
    assert len(risks.rows) == min(5, total_risks)
    assert {row[3] for row in risks.rows} <= {"simulation", "security"}


def test_arabic_document_is_real_arabic_with_numeric_token_parity(case: Case) -> None:
    english = build_executive_summary(case.sources, language="en")
    arabic = build_executive_summary(case.sources, language="ar")
    section = executive_section(arabic)

    assert arabic.title == AR["title"]
    assert section.title == AR["section"]
    assert tuple(block.kind for block in section.blocks) == FILLED_BLOCK_KINDS
    assert any("\u0600" <= char <= "\u06ff" for char in visible_text(arabic))

    arabic_text = visible_text(arabic)
    assert not any("\u0660" <= char <= "\u0669" for char in arabic_text)
    assert not any("\u06f0" <= char <= "\u06f9" for char in arabic_text)
    assert printed_numeric_tokens(arabic)
    assert printed_numeric_tokens(arabic) == printed_numeric_tokens(english)
    assert check_consistency(arabic).findings == ()


def test_values_have_step_tool_and_twin_fingerprint(case: Case) -> None:
    document = build_executive_summary(case.sources)
    assert document.values

    for record in document.values:
        assert record.provenance.step
        assert record.provenance.tool
        assert record.provenance.twin_version

    fingerprint = document.twin.fingerprint
    assert value(document, "executive.device_count").provenance.step == "topology"
    assert (
        value(document, "executive.twin_fingerprint").provenance.twin_version
        == fingerprint
    )
    assert (
        value(document, "executive.served_demand_count").provenance.twin_version
        == case.scenario_run.baseline_twin.fingerprint
    )
    assert (
        value(document, "executive.risk.sweep.0.loss").provenance.twin_version
        == case.sweep.baseline.fingerprint
    )
    assert (
        value(document, "executive.capacity.horizon").provenance.twin_version
        == case.capacity_run.twin_fingerprint
    )


def test_absent_inputs_name_producing_pages_and_add_no_numbers() -> None:
    document = build_executive_summary(
        ReportSources(twin=make_twin(), generated_at=GENERATED_AT)
    )
    section = executive_section(document)
    assert tuple(block.kind for block in section.blocks) == (
        "paragraph",
        "key_value",
        "note",
        "note",
        "table",
        "note",
        "paragraph",
    )

    texts = visible_text(document)
    for page in (
        "Simulation Lab",
        "Security Analysis",
        "Capacity Planning",
        "Digital Twin",
    ):
        assert page in texts
    assert EN["not_run"].format(page="Simulation Lab") in texts
    assert EN["capacity.not_run"] in texts
    assert EN["risk.not_run"] in texts
    assert EN["decision.not_run"] in texts

    limits = section.blocks[-1]
    assert isinstance(limits, ParagraphBlock)
    assert MODELED_ESTIMATE_LABEL in limits.text
    assert DISCLOSURE_TEXT in limits.text
    assert EN["limits.not_run_prefix"] in limits.text

    notes = [block for block in section.blocks if isinstance(block, NoteBlock)]
    assert notes
    assert all(numeric_tokens(note.text) == [] for note in notes)
    assert not any(
        record.key.startswith(
            (
                "executive.served_demand_count",
                "executive.risk.",
                "executive.capacity.",
                "executive.decision.",
            )
        )
        for record in document.values
    )


def test_zero_case_twin_has_zero_counts_and_no_bom_proxy() -> None:
    twin = make_twin(
        topology=Topology(name="Empty", devices=[], links=[]),
        addressing=None,
        vlan_plan=None,
        dhcp_scopes=(),
        demands=(),
        assumptions=(),
    )
    document = build_executive_summary(
        ReportSources(twin=twin, generated_at=GENERATED_AT)
    )
    section = executive_section(document)

    assert value(document, "executive.device_count").numeric == 0
    assert value(document, "executive.link_count").numeric == 0
    assert value(document, "executive.critical_link_count").numeric == 0
    assert value(document, "executive.spof_count").numeric == 0
    assert EN["cost.not_run"] in visible_text(document)
    assert not any(block.kind == "table" for block in section.blocks[:4])
    assert check_consistency(document).findings == ()


def test_cost_proxy_groups_only_twin_link_capacities(case: Case) -> None:
    document = build_executive_summary(case.sources)
    table = block_by_id(document, "executive_cost_proxy")
    grouped = Counter(link.capacity_mbps for link in case.twin.topology.links)

    assert "proxy, not a quote" in table.title
    assert table.columns == (EN["cost.tier"], EN["cost.count"], EN["cost.basis"])
    assert [(row[0], row[1]) for row in table.rows] == [
        (format_number(capacity, digits=2), str(count))
        for capacity, count in sorted(grouped.items())
    ]
    assert all(row[2] == EN["cost.basis_value"] for row in table.rows)
    assert {
        record.numeric
        for record in document.values
        if record.key.startswith("executive.cost.")
    } == {*grouped.keys(), *grouped.values()}


def test_decisions_block_prefers_keyword_and_keeps_fingerprints(case: Case) -> None:
    record = case.decisions[0]
    document = build_executive_summary(case.sources, decisions=(record,))
    section = executive_section(document)
    block = next(
        item
        for item in section.blocks
        if isinstance(item, KeyValueBlock) and item.title == EN["decisions"]
    )
    items = {item.key: item for item in block.items}

    assert items[EN["decision.count"]].value == "1"
    assert items[EN["decision.latest"]].value == record.title
    assert items[EN["decision.source"]].value == record.source_fingerprint
    assert items[EN["decision.result"]].value == record.result_fingerprint
    assert any(
        item.key.startswith("executive.decision.time.token.")
        and item.display == "00"
        for item in document.values
    )
    for item in block.items:
        assert item.provenance.step == "decision"
        assert item.provenance.tool == "services.copilot.decisions"
        assert item.provenance.twin_version == record.source_fingerprint

    fallback = build_executive_summary(case.sources)
    fallback_block = next(
        item
        for item in executive_section(fallback).blocks
        if isinstance(item, KeyValueBlock) and item.title == EN["decisions"]
    )
    fallback_items = {item.key: item for item in fallback_block.items}
    assert fallback_items[EN["decision.count"]].value == "2"
    assert (
        fallback_items[EN["decision.latest"]].value == case.decisions[-1].title
    )


def test_limits_paragraph_carries_both_required_disclosures(case: Case) -> None:
    document = build_executive_summary(case.sources)
    limits = executive_section(document).blocks[-1]
    assert isinstance(limits, ParagraphBlock)
    assert MODELED_ESTIMATE_LABEL in limits.text
    assert DISCLOSURE_TEXT in limits.text
    assert EN["proxy.note"] in limits.text
    assert EN["limits.all_available"] in limits.text
    assert value(document, "executive.limits.note").display == limits.text


def test_to_json_is_deterministic_and_round_trips(case: Case) -> None:
    first = build_executive_summary(case.sources)
    second = build_executive_summary(case.sources)
    payload = to_json(first)

    assert first.model_dump() == second.model_dump()
    assert to_json(second) == payload
    assert from_json(payload) == first


def test_single_section_ir_renders_with_pdf_fallback(case: Case) -> None:
    document = build_executive_summary(case.sources)
    assert document.section_ids() == (EXECUTIVE_SECTION_ID,)
    assert len(build_report(case.sources).sections) > 1

    data = to_pdf(document, generated_at=GENERATED_AT)
    assert data.startswith(b"%PDF")
    text = data.decode("latin-1")
    assert EN["section"] in text
    assert DISCLOSURE_TEXT in text
    # The exporter always appends a source-value appendix after a PageBreak, so
    # this single-section IR renders at least two pages. An exact count would
    # couple this test to shared exporter pagination, which B4 cannot change.
    assert pdf_page_count(data) >= 2

    arabic = build_executive_summary(case.sources, language="ar")
    assert pdf_warnings(arabic)
    assert to_pdf(arabic, generated_at=GENERATED_AT).startswith(b"%PDF")
