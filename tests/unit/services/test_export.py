"""Report exporter tests (Phase 11b).

Every export is exercised in memory. The PDF is inspected by decoding its
uncompressed page streams and searching for literal text; no visual renderer is
involved.
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import zipfile
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.exceptions import ReportExportError, ReportLimitError
from services.export import (
    CSV_ENCODING_NOTE,
    CSV_TABLE_IDS,
    NON_LATIN_NOTICE,
    TEMPLATE_HEADER,
    config_templates,
    csv_tables,
    from_json,
    pdf_page_count,
    pdf_warnings,
    to_config_bundle,
    to_csv_bundle,
    to_json,
    to_markdown,
    to_pdf,
)
from services.reporting import (
    DISCLOSURE_TEXT,
    MODELED_ESTIMATE_LABEL,
    SAMPLE_DATA_LABEL,
    TEMPLATE_LABEL,
    Provenance,
    ReportDocument,
    ReportSources,
    TableBlock,
    build_report,
)
from simulation import twin_reference
from tests.unit.digital_twin.helpers import make_twin

GENERATED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def twin():
    return make_twin()


@pytest.fixture(scope="module")
def report(twin) -> ReportDocument:
    return build_report(ReportSources(twin=twin, generated_at=GENERATED_AT))


def _with_table(report: ReportDocument, table: TableBlock) -> ReportDocument:
    section = report.section("architecture_summary")
    assert section is not None
    changed = section.model_copy(update={"blocks": (*section.blocks, table)})
    return report.model_copy(
        update={
            "sections": tuple(
                changed if item.id == section.id else item
                for item in report.sections
            )
        }
    )


def _table(
    report: ReportDocument,
    *,
    rows: tuple[tuple[str, ...], ...],
    total_rows: int | None = None,
) -> TableBlock:
    return TableBlock(
        id="test_table",
        title="Test table",
        columns=("Name", "Value"),
        rows=rows,
        total_rows=len(rows) if total_rows is None else total_rows,
        provenance=Provenance(
            step="test",
            tool="tests",
            twin_version=report.twin.fingerprint,
        ),
    )


def test_json_round_trip_is_exact_and_stable(report: ReportDocument) -> None:
    payload = to_json(report)
    restored = from_json(payload)
    assert restored == report
    assert to_json(restored) == payload
    assert to_json(report) == payload
    # Stable ordering: keys are sorted and indentation is fixed.
    assert payload.startswith(b'{\n  "ai":')
    assert payload.endswith(b"\n")


def test_json_rejects_malformed_and_unsupported_payloads(
    report: ReportDocument,
) -> None:
    with pytest.raises(ReportExportError):
        from_json(b"{not json")
    with pytest.raises(ReportExportError):
        from_json(b"[]")
    payload = json.loads(to_json(report))
    payload["schema_version"] = 99
    with pytest.raises(ReportExportError):
        from_json(json.dumps(payload))
    payload = json.loads(to_json(report))
    payload["sections"] = "not-a-list"
    with pytest.raises((ReportExportError, ValidationError)):
        from_json(json.dumps(payload))


def test_markdown_contains_sections_tables_and_disclosure(
    report: ReportDocument,
) -> None:
    markdown = to_markdown(report).decode("utf-8")
    assert markdown.startswith(f"# {report.title}")
    for section in report.sections:
        assert section.title in markdown
    assert "This section was not run." in markdown
    assert "Produced on: Simulation Lab" in markdown
    assert DISCLOSURE_TEXT in markdown
    assert MODELED_ESTIMATE_LABEL in markdown
    assert SAMPLE_DATA_LABEL in markdown
    assert TEMPLATE_LABEL in markdown
    assert "| Subnet | Network | VLAN | Description |" in markdown
    assert "Value provenance appendix" in markdown


def test_markdown_is_deterministic(report: ReportDocument) -> None:
    assert to_markdown(report) == to_markdown(
        build_report(
            ReportSources(twin=make_twin(), generated_at=GENERATED_AT)
        )
    )


def test_markdown_marks_table_truncation(report: ReportDocument) -> None:
    table = _table(
        report,
        rows=tuple(("row", str(index)) for index in range(3)),
        total_rows=10,
    )
    markdown = to_markdown(_with_table(report, table)).decode("utf-8")
    assert "Showing first 3 of 10 rows." in markdown


def test_csv_tables_match_the_report_and_bom_is_optional(
    report: ReportDocument,
) -> None:
    tables = {table.table_id: table for table in csv_tables(report)}
    assert set(tables) == {"ip_plan", "vlan_assignments", "dhcp_scopes", "routing_table", "findings"}
    source = next(item for item in report.tables() if item.id == "ip_plan")
    exported = tables["ip_plan"]
    assert exported.columns == source.columns
    assert exported.rows == source.rows

    plain = exported.to_bytes()
    with_bom = exported.to_bytes(bom=True)
    assert not plain.startswith(codecs.BOM_UTF8)
    assert with_bom.startswith(codecs.BOM_UTF8)
    assert with_bom[len(codecs.BOM_UTF8):] == plain
    rows = list(csv.reader(io.StringIO(plain.decode("utf-8"))))
    assert tuple(rows[0]) == exported.columns
    assert tuple(rows[1]) == exported.rows[0]


def test_csv_bundle_is_stable_and_documents_encoding(
    report: ReportDocument,
) -> None:
    first = to_csv_bundle(report)
    second = to_csv_bundle(report)
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert "README.txt" in names
        assert set(names) - {"README.txt"} == set(CSV_TABLE_IDS.values()) & set(names)
        readme = archive.read("README.txt").decode("utf-8")
        assert CSV_ENCODING_NOTE in readme
        assert "BOM: not written" in readme
        assert DISCLOSURE_TEXT in readme
        assert archive.read("ip_plan.csv").decode("utf-8").startswith(
            "Subnet,Network,VLAN,Description"
        )


def test_csv_bundle_reports_table_truncation(report: ReportDocument) -> None:
    table = _table(
        report,
        rows=(("row", "1"), ("row", "2")),
        total_rows=9,
    )
    document = _with_table(report, table)
    assert not any(
        item.table_id == "test_table" for item in csv_tables(document)
    )
    with zipfile.ZipFile(io.BytesIO(to_csv_bundle(document))) as archive:
        readme = archive.read("README.txt").decode("utf-8")
    assert "ip_plan.csv" in readme


def test_configuration_templates_use_only_twin_data(twin) -> None:
    templates = {item.template_id: item for item in config_templates(twin)}
    assert set(templates) == {"devices", "interfaces", "subnets", "vlans", "dhcp"}
    for template in templates.values():
        assert template.content.startswith(TEMPLATE_HEADER + "\n")
    devices = templates["devices"].content
    for device in twin.topology.devices:
        assert f"device {device.id}" in devices
        assert device.type.value in devices
        assert device.site in devices
    interfaces = templates["interfaces"].content
    for link in twin.topology.links:
        assert f"link {link.id}" in interfaces
        assert link.endpoints[0] in interfaces
        assert link.endpoints[1] in interfaces
    assert twin.metadata.name in devices
    assert twin.metadata.name in templates["devices"].content
    assert str(twin.vlan_plan.assignments[0].vlan_id) in templates["vlans"].content
    assert twin.dhcp_scopes[0].name in templates["dhcp"].content
    assert "static route" not in interfaces.lower()


def test_configuration_bundle_is_stable_and_has_the_header(twin) -> None:
    first = to_config_bundle(twin)
    assert first == to_config_bundle(twin)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert "README.txt" in archive.namelist()
        for name in archive.namelist():
            assert archive.read(name).decode("utf-8").startswith(TEMPLATE_HEADER)
        readme = archive.read("README.txt").decode("utf-8")
        assert twin_reference(twin).fingerprint in readme


def test_pdf_structure_footer_and_injected_clock(report: ReportDocument) -> None:
    data = to_pdf(report)
    assert data.startswith(b"%PDF")
    assert pdf_page_count(data) > 0
    text = data.decode("latin-1")
    assert DISCLOSURE_TEXT in text
    assert "Page 1 of" in text
    assert "Generated 2026-11-15T12:00:00+00:00" in text
    assert "20261115120000" in text
    assert report.title in text
    assert "Contents" in text
    assert "Template, not device-applied." in text


def test_pdf_is_byte_identical_for_the_same_clock(report: ReportDocument) -> None:
    first = to_pdf(report, generated_at=GENERATED_AT)
    second = to_pdf(report, generated_at=GENERATED_AT)
    assert first == second


def test_pdf_paginates_a_long_table(report: ReportDocument) -> None:
    rows = tuple((f"row-{index}", f"value-{index}") for index in range(120))
    document = _with_table(report, _table(report, rows=rows, total_rows=120))
    data = to_pdf(document)
    assert pdf_page_count(data) >= 3
    assert b"row-119" in data


def test_pdf_shows_a_visible_truncation_note(report: ReportDocument) -> None:
    rows = (("row-a", "1"), ("row-b", "2"))
    document = _with_table(report, _table(report, rows=rows, total_rows=8))
    text = to_pdf(document).decode("latin-1")
    assert "Showing first 2 of 8 rows." in text


def test_pdf_warns_and_falls_back_for_non_latin_text(
    report: ReportDocument,
) -> None:
    document = report.model_copy(
        update={
            "title": "تقرير الشبكة",
            "subtitle": "ملخص التصميم",
        }
    )
    warnings = pdf_warnings(document)
    assert warnings
    assert "Latin-only" in warnings[0]
    text = to_pdf(document).decode("latin-1")
    assert "Latin-only" in text
    assert "تقرير" not in text
    # The original text survives in the UTF-8 exports.
    markdown = to_markdown(document).decode("utf-8")
    assert "تقرير الشبكة" in markdown
    assert from_json(to_json(document)).title == "تقرير الشبكة"


def test_pdf_has_no_font_warning_for_latin_text(report: ReportDocument) -> None:
    assert pdf_warnings(report) == ()
    assert NON_LATIN_NOTICE.split("{")[0] in NON_LATIN_NOTICE


def test_exports_enforce_the_size_bound(
    report: ReportDocument, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("services.export.common.MAX_REPORT_BYTES", 10)
    with pytest.raises(ReportLimitError):
        to_json(report)
    with pytest.raises(ReportLimitError):
        to_markdown(report)
    with pytest.raises(ReportLimitError):
        to_pdf(report)
    with pytest.raises(ReportLimitError):
        to_csv_bundle(report)
