"""Report Security section tests."""

from __future__ import annotations

from datetime import UTC, datetime

from security import SECURITY_DISCLAIMER, PolicyAction, analyze_design
from services.reporting import ReportSources, build_report, check_consistency
from tests.unit.security.design_helpers import hardened_design

GENERATED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _security_case():
    twin, model = hardened_design()
    strict = model.model_copy(update={"default_action": PolicyAction.allow})
    return twin, analyze_design(twin, model=strict)


def test_security_section_uses_exact_disclaimer_and_provenance() -> None:
    twin, analysis = _security_case()

    document = build_report(
        ReportSources(
            twin=twin,
            security_analysis=analysis,
            generated_at=GENERATED_AT,
        )
    )
    section = document.section("security")
    assert section is not None
    assert section.title == "Design-time security analysis"
    assert section.status.value == "available"
    texts = [getattr(block, "text", "") for block in section.blocks]
    assert SECURITY_DISCLAIMER in texts

    score = next(record for record in document.values if record.key == "security.risk_score")
    assert score.numeric == analysis.risk.score == 6
    assert score.provenance.step == "security"
    assert score.provenance.tool == "security.analyze_design"

    findings_table = next(
        table for table in section.blocks if getattr(table, "id", "") == "security_findings"
    )
    assert any("POLICY-DEFAULT-ALLOW" in row for row in findings_table.rows)


def test_security_design_additions_have_provenance_and_consistent_numbers() -> None:
    twin, analysis = _security_case()

    document = build_report(
        ReportSources(
            twin=twin,
            security_analysis=analysis,
            generated_at=GENERATED_AT,
        )
    )
    section = document.section("security")
    assert section is not None
    tool_by_key = {
        "security.reachability.zones": "security.reachability.build_reachability_report",
        "security.segmentation.score": "security.segmentation.score_segmentation",
        "security.optimizer.proposals": "security.optimizer.build_optimization_plan",
        "security.microsegmentation.proposals": (
            "security.microsegmentation.build_microsegmentation_plan"
        ),
        "security.checklist.pass": "security.checklist.build_design_checklist",
    }
    for key, tool in tool_by_key.items():
        record = next(record for record in document.values if record.key == key)
        assert record.provenance.step == "security"
        assert record.provenance.tool == tool

    table_ids = {
        getattr(block, "id", "") for block in section.blocks
    }
    assert "security_blast_radius" in table_ids
    assert "security_segmentation_inputs" in table_ids
    assert "security_checklist" in table_ids

    consistency = check_consistency(document)
    assert consistency.ok
    assert consistency.errors == ()


def test_security_section_is_deterministic() -> None:
    twin, analysis = _security_case()
    sources = ReportSources(
        twin=twin,
        security_analysis=analysis,
        generated_at=GENERATED_AT,
    )

    first = build_report(sources)
    second = build_report(sources)

    assert first.model_dump() == second.model_dump()
    assert first.section_ids() == second.section_ids()
