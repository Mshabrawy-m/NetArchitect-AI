"""Phase 15c deployment artifact and in-app limitation tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config import settings as settings_module

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = ROOT / "app.py"


def _rendered_text(at: AppTest) -> str:
    parts: list[str] = []
    for kind in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "info",
        "warning",
        "error",
        "success",
    ):
        parts.extend(str(item.value) for item in at.get(kind))
    for metric in at.get("metric"):
        parts.append(f"{metric.label} {metric.value}")
    return "\n".join(parts)


def test_streamlit_deployment_config_is_headless_and_bounded() -> None:
    path = ROOT / ".streamlit" / "config.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    assert config["server"]["headless"] is True
    assert config["server"]["maxUploadSize"] == 2
    assert config["browser"]["gatherUsageStats"] is False
    assert config["theme"]["base"] == "light"


def test_ci_workflow_pins_the_same_commands_and_no_secrets() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    text = path.read_text(encoding="utf-8")
    for fragment in (
        'python-version: ["3.11", "3.12"]',
        "python -m pip install -r requirements-dev.txt",
        "python -m ruff check .",
        "python -m pytest -q",
        "python -m pytest -q -m smoke",
    ):
        assert fragment in text
    assert "secrets." not in text
    assert "GROQ_API_KEY" not in text


def test_deployment_docs_and_secret_placeholder_are_present() -> None:
    limits = (ROOT / "docs" / "RUNTIME_LIMITS.md").read_text(encoding="utf-8")
    assert "Streamlit upload widget" in limits
    assert "2 MB" in limits
    assert not (ROOT / ".streamlit" / "secrets.toml").exists()
    assert (ROOT / ".streamlit" / "secrets.toml.example").exists()


@pytest.mark.smoke
def test_settings_page_states_release_limitations_with_no_api_key(monkeypatch) -> None:
    for key in settings_module._SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_module, "_read_streamlit_secrets", dict)
    settings_module.get_settings.cache_clear()
    try:
        at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
        assert not at.exception
        at.selectbox(key="page_nav").select("Settings").run()
        assert not at.exception
        text = _rendered_text(at)
        assert "Release limitations" in text
        assert "does not connect to devices" in text
        assert "Modeled, not measured" in text
        assert "Session-only state" in text
        assert "not verified here" in text
        assert "API key configured No" in text
    finally:
        settings_module.get_settings.cache_clear()


def test_about_menu_states_design_time_scope() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    assert "design-time" in source
    assert "No device access, live scanning," in source
    assert "v1.0.0-rc1" in source
