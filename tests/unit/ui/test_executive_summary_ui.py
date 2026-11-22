"""AppTest coverage for the B4 two-page executive summary UI."""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.schemas.network import Topology
from services.reporting import ReportSources, build_executive_summary
from simulation import twin_fingerprint
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.ui.nav_helpers import open_page
from ui import i18n, state
from ui.cache import cached_executive_exports
from ui.pages import reports as page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _reports(language: str = "en", twin: object | None = None) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin if twin is not None else make_twin()
    at.session_state[i18n.LANGUAGE_KEY] = language
    at.run()
    return open_page(at, "Reports & Documentation")


def _count(elements: object, key: str) -> int:
    """Count elements by user key; AppTest raises when a key is missing."""
    return sum(1 for element in elements if getattr(element, "key", None) == key)


def test_executive_controls_render_and_first_click_works_from_empty_sources() -> None:
    at = _reports()

    assert not at.exception
    assert any(
        "Executive summary" in subheader.value for subheader in at.subheader
    )
    assert at.download_button(key=page.EXECUTIVE_PDF_KEY)
    assert at.download_button(key=page.EXECUTIVE_MARKDOWN_KEY)
    assert any("Report language: English." in cap.value for cap in at.caption)
    assert any("Sections not run:" in cap.value for cap in at.caption)
    assert any("Simulation Lab" in cap.value for cap in at.caption)
    assert any(cap.value.startswith("PDF: 2 page(s), ") for cap in at.caption)

    at.download_button(key=page.EXECUTIVE_PDF_KEY).click().run()
    assert not at.exception
    assert _count(at.download_button, page.EXECUTIVE_PDF_KEY) == 1


def test_executive_zero_case_shows_not_run_without_blocking_the_page() -> None:
    empty = make_twin(
        topology=Topology(name="Empty", devices=[], links=[]),
        addressing=None,
        vlan_plan=None,
        dhcp_scopes=(),
        demands=(),
        assumptions=(),
    )
    at = _reports(twin=empty)

    assert not at.exception
    assert at.download_button(key=page.EXECUTIVE_PDF_KEY)
    assert at.download_button(key=page.EXECUTIVE_MARKDOWN_KEY)
    assert any("Topology Editor" in cap.value for cap in at.caption)
    captions = " ".join(cap.value for cap in at.caption)
    assert "Build links on Topology Editor." in captions
    assert "PDF: 2 page(s)" in captions
    # The full report still requires a device, but the executive summary does not.
    assert any(
        "Digital twin required" in f"{getattr(info, 'title', '')} {info.value}"
        for info in at.info
    )


def test_executive_follows_the_interface_language_switch() -> None:
    english = _reports(language="en")
    arabic = _reports(language="ar")

    assert not english.exception
    assert not arabic.exception
    assert any(
        subheader.value == "Executive summary (two pages)" for subheader in english.subheader
    )
    assert any(
        subheader.value == "الملخص التنفيذي (صفحتان)" for subheader in arabic.subheader
    )
    assert (
        arabic.download_button(key=page.EXECUTIVE_PDF_KEY).label
        != english.download_button(key=page.EXECUTIVE_PDF_KEY).label
    )
    assert any("لغة التقرير: العربية." in cap.value for cap in arabic.caption)

    def pdf_size(at: AppTest) -> int:
        # Arabic captions wrap Latin tokens in bidi isolates, so match on the
        # token and the two numbers rather than a literal prefix.
        for caption in at.caption:
            numbers = re.findall(r"\d+", caption.value)
            if "PDF" in caption.value and len(numbers) >= 2:
                return int(numbers[1])
        raise AssertionError("No executive PDF size caption found.")

    # The Arabic PDF embeds the bundled font, so it is larger than the Latin one.
    assert pdf_size(arabic) > pdf_size(english)


def test_executive_run_twice_is_deterministic() -> None:
    twin = make_twin()
    first = _reports(twin=twin)
    second = _reports(twin=twin)

    def ready_line(at: AppTest) -> str:
        return next(
            cap.value for cap in at.caption if cap.value.startswith("PDF: 2 page(s), ")
        )

    assert not first.exception
    assert not second.exception
    assert ready_line(first) == ready_line(second)

    first.download_button(key=page.EXECUTIVE_PDF_KEY).click().run()
    first.download_button(key=page.EXECUTIVE_PDF_KEY).click().run()
    assert not first.exception
    assert ready_line(first) == ready_line(second)

    document = build_executive_summary(
        ReportSources(
            twin=twin,
            generated_at=state.report_generated_at(twin_fingerprint(twin)),
        )
    )
    payload = document.model_dump_json()
    a = cached_executive_exports(payload, "en")
    b = cached_executive_exports(payload, "en")
    assert a.pdf == b.pdf
    assert a.markdown == b.markdown
    assert a.pages == 2
