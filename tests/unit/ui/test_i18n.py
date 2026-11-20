"""Ar/en catalog, fallback, RTL, and Settings language-switch coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.unit.ui.nav_helpers import open_page
from ui import i18n

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"
FSI, PDI = "\u2068", "\u2069"


def _plain(text: str) -> str:
    """Remove Unicode direction isolates for readable value assertions."""
    return text.replace(FSI, "").replace(PDI, "")


def test_catalogs_have_full_arabic_key_and_placeholder_parity() -> None:
    assert i18n.catalog_parity()
    assert i18n.missing_translation_keys() == ()
    assert set(i18n.AR) == set(i18n.EN)


def test_translate_falls_back_to_english_for_a_missing_arabic_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "AR", dict(i18n.AR))
    monkeypatch.setattr(i18n, "EN", dict(i18n.EN))
    i18n.AR.pop("progress.title")
    i18n.EN["progress.title"] = "Project progress"

    assert _plain(i18n.translate("progress.title", language="ar")) == (
        "Project progress"
    )


def test_translate_falls_back_when_arabic_placeholders_are_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "AR", dict(i18n.AR))
    i18n.AR["progress.detail.design"] = "{missing} devices"

    value = i18n.translate(
        "progress.detail.design",
        {"devices": 3, "links": 4},
        language="ar",
    )
    assert "3" in value
    assert "devices" in value
    assert "links" in value


def test_unknown_key_is_deterministic() -> None:
    assert i18n.translate("not.in.catalog", language="en") == "not.in.catalog"
    assert _plain(i18n.translate("not.in.catalog", language="ar")) == (
        "not.in.catalog"
    )


def test_engineering_terms_numbers_and_cidrs_stay_ltr() -> None:
    protected = i18n.protect_latin_tokens(
        "استخدم OSPF و VLAN مع CIDR 10.0.0.0/8"
    )
    for token in ("OSPF", "VLAN", "CIDR", "10.0.0.0/8"):
        assert f"{FSI}{token}{PDI}" in protected
    assert i18n.protect_latin_tokens("بدون رموز لاتينية") == (
        "بدون رموز لاتينية"
    )

    monkeypatch_language = pytest.MonkeyPatch()
    monkeypatch_language.setattr(
        i18n, "current_language", lambda: "ar", raising=False
    )
    try:
        label = i18n.page_label("VLAN & DHCP Planner")
        assert f"{FSI}VLAN{PDI}" in label
        assert f"{FSI}DHCP{PDI}" in label
        assert i18n.direction() == "rtl"
        assert i18n.ltr("10.0.0.0/8") == f"{FSI}10.0.0.0/8{PDI}"
        assert i18n.ltr(None) == ""
    finally:
        monkeypatch_language.undo()


def test_language_values_normalize_to_supported_codes() -> None:
    assert i18n.normalize_language("AR") == "ar"
    assert i18n.normalize_language("العربية") == "ar"
    assert i18n.normalize_language("en-US") == "en"
    assert i18n.normalize_language(None) == "en"
    assert i18n.normalize_language("unknown") == "en"


def test_arabic_session_renders_rtl_css_and_localized_dashboard() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[i18n.LANGUAGE_KEY] = "ar"
    at.run()

    assert not at.exception
    assert any("direction: rtl" in html.value for html in at.html)
    assert any(".i18n-ltr" in html.value for html in at.html)

    open_page(at, "Dashboard")
    assert not at.exception
    assert at.title[0].value == "لوحة التحكم"
    assert "البدء السريع" in [header.value for header in at.subheader]
    assert any(
        "نموذج - مكتب صغير" in text.value for text in at.markdown
    )
    assert any("تقدم المشروع" in caption.value for caption in at.caption)
    assert any(
        "التصميم" in link.label for link in at.get("page_link")
    )
    assert any(f"{FSI}VLAN{PDI}" in caption.value for caption in at.caption)
    assert at.session_state[i18n.LANGUAGE_KEY] == "ar"


def test_settings_language_toggle_switches_session_only() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "Settings")

    assert not at.exception
    control = at.segmented_control[0]
    assert control.key == i18n.LANGUAGE_KEY
    assert control.label == "Language"
    assert control.value == "en"
    assert not at.html

    control.set_value("ar").run()
    assert not at.exception
    assert at.title[0].value == "الإعدادات"
    assert at.segmented_control[0].label == "اللغة"
    assert at.session_state[i18n.LANGUAGE_KEY] == "ar"
    assert any("direction: rtl" in html.value for html in at.html)

    at.segmented_control[0].set_value("en").run()
    assert not at.exception
    assert at.title[0].value == "Settings"
    assert at.session_state[i18n.LANGUAGE_KEY] == "en"
    assert not at.html
