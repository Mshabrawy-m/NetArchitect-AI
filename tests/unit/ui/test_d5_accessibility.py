"""D5 invariants: readable labels, full-width tables, and visible semantics."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from ui import formatting, i18n, theme
from ui.pages.simulation_lab import _scenario_level_labels

ROOT = Path(__file__).resolve().parents[3]
UI_ROOT = ROOT / "ui"

INPUT_WIDGETS = {
    "button",
    "camera_input",
    "checkbox",
    "color_picker",
    "date_input",
    "datetime_input",
    "download_button",
    "file_uploader",
    "form_submit_button",
    "link_button",
    "multiselect",
    "number_input",
    "pills",
    "radio",
    "segmented_control",
    "select_slider",
    "selectbox",
    "slider",
    "text_area",
    "text_input",
    "time_input",
    "toggle",
}
TABLE_CALLS = {"data_editor", "dataframe", "table"}


def _st_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
        ):
            yield node.func.attr, node


def test_every_input_widget_has_a_visible_label() -> None:
    offenders: list[str] = []
    for path in UI_ROOT.rglob("*.py"):
        for name, call in _st_calls(path):
            if name not in INPUT_WIDGETS:
                continue
            has_label = bool(call.args) or any(
                keyword.arg == "label" for keyword in call.keywords
            )
            visibility = next(
                (
                    keyword.value.value
                    for keyword in call.keywords
                    if keyword.arg == "label_visibility"
                    and isinstance(keyword.value, ast.Constant)
                ),
                "visible",
            )
            if not has_label or visibility != "visible":
                offenders.append(f"{path.relative_to(ROOT)}:{call.lineno}: st.{name}")
    assert offenders == []


def test_wide_tables_use_container_width() -> None:
    offenders: list[str] = []
    for path in UI_ROOT.rglob("*.py"):
        for name, call in _st_calls(path):
            if name not in TABLE_CALLS:
                continue
            width = next(
                (keyword.value for keyword in call.keywords if keyword.arg == "width"),
                None,
            )
            stretch = (
                isinstance(width, ast.Constant) and width.value == "stretch"
            ) or (
                isinstance(width, ast.Call)
                and isinstance(width.func, ast.Attribute)
                and width.func.attr == "stretch"
            )
            if not stretch:
                offenders.append(f"{path.relative_to(ROOT)}:{call.lineno}: st.{name}")
    assert offenders == []


def test_domain_errors_use_the_shared_formatter() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in UI_ROOT.rglob("*.py")
        if "st.error(str(error))" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_long_actions_show_a_bounded_loading_state() -> None:
    modules = (
        "components/feedback.py",
        "pages/ai_designer.py",
        "pages/capacity_planning.py",
        "pages/settings.py",
        "pages/simulation_lab.py",
    )
    for relative in modules:
        source = (UI_ROOT / relative).read_text(encoding="utf-8")
        assert "working(" in source, relative
    assert "with st.spinner(" in (
        UI_ROOT / "components" / "feedback.py"
    ).read_text(encoding="utf-8")


def test_status_badges_always_include_text() -> None:
    at = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.components import status_badge\n"
        "status_badge('stale')\n"
    ).run()
    assert not at.exception
    assert any("Stale" in element.value for element in at.markdown)


def test_congestion_colors_have_visible_text_labels() -> None:
    after = {
        "a-b": SimpleNamespace(level=SimpleNamespace(value="warning")),
        "b-c": SimpleNamespace(level=SimpleNamespace(value="overloaded")),
    }
    assert _scenario_level_labels(["a-b", "b-c", "c-d"], after) == [
        "warning",
        "overloaded",
        "failed",
    ]
    source = (UI_ROOT / "pages" / "simulation_lab.py").read_text(encoding="utf-8")
    assert "text=level_labels" in source


def test_rtl_stylesheet_is_declared_once() -> None:
    files = [
        path.relative_to(ROOT).as_posix()
        for path in UI_ROOT.rglob("*.py")
        if "direction: rtl" in path.read_text(encoding="utf-8")
    ]
    assert files == ["ui/i18n.py"]


def test_design_tokens_keep_text_contrast() -> None:
    assert theme.minimum_text_contrast() >= 4.5
    for token in (
        "l2_accent",
        "wan_accent",
        "wireless_accent",
        "qos_accent",
        "findings_accent",
    ):
        assert token in theme.LIGHT
        assert token in theme.DARK
        assert (token, "surface") in theme.TEXT_CONTRAST_PAIRS


def test_number_formatters_are_grouped_and_explicit() -> None:
    assert formatting.number(1234.5, decimals=1) == "1,234.5"
    assert formatting.percent(91.23, decimals=1) == "91.2%"
    assert formatting.ratio(0.9123, decimals=1) == "91.2%"
    assert formatting.capacity_mbps(1000) == "1,000.0 Mbps"
    assert formatting.latency_ms(None) == "n/a"
    assert formatting.signed(2.5, decimals=1, unit=" pp") == "+2.5 pp"
    assert formatting.signed_int(-2) == "-2"


def test_number_formatters_isolate_values_in_arabic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "current_language", lambda: "ar", raising=False)
    assert formatting.percent(91.2) == "\u206891.2%\u2069"
    assert formatting.capacity_mbps(1000) == "\u20681,000.0 Mbps\u2069"
    assert formatting.latency_ms(None) == "غير متاح"
