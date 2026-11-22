"""Arabic-capable PDF export tests (task B3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.export.arabic import (
    ARABIC_FONT_PATH,
    contains_arabic,
    logical_to_visual,
    shape_arabic,
)
from services.export.pdf import pdf_page_count, pdf_warnings, to_pdf
from services.reporting import (
    ParagraphBlock,
    Provenance,
    ReportDocument,
    ReportSection,
    ReportTwin,
    TableBlock,
    ValueRecord,
)
from simulation import twin_fingerprint
from tests.unit.digital_twin.helpers import make_twin

GENERATED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _document(title: str, *, arabic: bool) -> ReportDocument:
    """Build one minimal report document without depending on another task."""
    twin = make_twin()
    provenance = Provenance(
        step="test", tool="tests", twin_version=twin_fingerprint(twin)
    )
    scope = "النطاق" if arabic else "Scope"
    paragraph = (
        "هذا ملخص للنموذج. الشبكة 192.168.1.0/24"
        if arabic
        else "Model summary. Network 192.168.1.0/24"
    )
    count_title = "العدد" if arabic else "Counts"
    columns = ("العنصر", "العدد") if arabic else ("Item", "Count")
    row = ("الأجهزة", "3") if arabic else ("Devices", "3")
    label = "الأجهزة" if arabic else "Devices"
    return ReportDocument(
        title=title,
        subtitle="ملخص تنفيذي للنموذج" if arabic else "Model executive summary",
        generated_at=GENERATED_AT,
        twin=ReportTwin(
            name=twin.metadata.name,
            created_at=twin.metadata.created_at,
            schema_version=twin.metadata.schema_version,
            fingerprint=twin_fingerprint(twin),
        ),
        sections=(
            ReportSection(
                id="scope",
                title=scope,
                blocks=(
                    ParagraphBlock(text=paragraph, provenance=provenance),
                    TableBlock(
                        id="counts",
                        title=count_title,
                        columns=columns,
                        rows=(row,),
                        total_rows=1,
                        provenance=provenance,
                    ),
                ),
            ),
        ),
        values=(
            ValueRecord(
                key="devices",
                label=label,
                display="3",
                numeric=3,
                provenance=provenance,
            ),
        ),
    )


@pytest.fixture(scope="module")
def arabic_document():
    return _document("ملخص تنفيذي", arabic=True)


@pytest.fixture(scope="module")
def english_document():
    return _document("Executive summary", arabic=False)


def test_arabic_pdf_is_valid_deterministic_and_embeds_font(
    arabic_document,
) -> None:
    data = to_pdf(arabic_document, language="ar")
    assert data.startswith(b"%PDF")
    assert pdf_page_count(data) >= 1
    assert to_pdf(arabic_document, language="ar") == data
    assert b"NotoNaskhArabic" in data
    assert pdf_warnings(arabic_document, language="ar") == ()
    assert not any("Latin-only" in item for item in pdf_warnings(
        arabic_document, language="ar"
    ))


def test_language_variants_normalize_to_arabic(arabic_document) -> None:
    expected = to_pdf(arabic_document, language="ar")
    for value in ("ar", "arabic", "العربية"):
        assert to_pdf(arabic_document, language=value) == expected


def test_shaping_uses_presentation_forms_and_handles_empty_text() -> None:
    original = "مرحبا بالعالم"
    shaped = shape_arabic(original)
    assert shaped != original
    assert all(
        character == " " or 0xFE70 <= ord(character) <= 0xFEFF
        for character in shaped
    )
    # ReportLab draws glyphs left to right, so the shaped RTL run is reversed
    # for display while its presentation forms stay in logical-shaped order.
    assert logical_to_visual(shaped) == shaped[::-1]
    assert len(shape_arabic("لا")) == 1  # lam-alef ligature
    assert shape_arabic("") == ""
    assert logical_to_visual("") == ""
    assert contains_arabic("") is False


def test_bidi_preserves_ltr_tokens() -> None:
    latin = "IP 192.168.1.0/24 and VLAN 10"
    assert logical_to_visual(latin) == latin
    mixed = "شبكة 192.168.1.0/24 CIDR 10.0.0.0/8"
    shaped = shape_arabic(mixed)
    assert "192.168.1.0/24" in shaped
    assert "10.0.0.0/8" in shaped
    visual = logical_to_visual(shaped)
    assert "192.168.1.0/24" in visual
    assert "10.0.0.0/8" in visual
    assert visual.index("192.168.1.0/24") < visual.index("10.0.0.0/8")


def test_pdf_size_bounds_and_bundled_font_size(arabic_document) -> None:
    assert len(to_pdf(arabic_document, language="ar")) < 5_000_000
    assert ARABIC_FONT_PATH.is_file()
    assert ARABIC_FONT_PATH.stat().st_size < 1_000_000


def test_large_value_registry_is_capped(
    arabic_document, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = tuple(
        ValueRecord(
            key=f"extra-{index}",
            label=f"Label {index}",
            display=str(index),
            provenance=Provenance(step="test", tool="tests"),
        )
        for index in range(520)
    )
    document = arabic_document.model_copy(update={"values": values})
    monkeypatch.setattr("services.export.pdf.MAX_REPORT_TABLE_ROWS", 2)
    text = to_pdf(document, language="ar").decode("latin-1")
    assert "Showing first 2 of 520 values" in text


def test_english_and_legacy_warning_paths_are_unchanged(
    arabic_document, english_document
) -> None:
    english_pdf = to_pdf(english_document)
    assert english_pdf.startswith(b"%PDF")
    assert pdf_warnings(english_document) == ()
    chinese = english_document.model_copy(update={"title": "网络"})
    assert any("Latin-only" in item for item in pdf_warnings(chinese))
    # Existing callers rely on the legacy notice even for Arabic input.
    assert any("Latin-only" in item for item in pdf_warnings(arabic_document))
    assert "Latin-only" in to_pdf(arabic_document).decode("latin-1")


def test_empty_arabic_string_does_not_crash(english_document) -> None:
    document = english_document.model_copy(
        update={"title": "ملخص", "subtitle": ""}
    )
    data = to_pdf(document, language="ar")
    assert data.startswith(b"%PDF")
    assert pdf_page_count(data) >= 1
