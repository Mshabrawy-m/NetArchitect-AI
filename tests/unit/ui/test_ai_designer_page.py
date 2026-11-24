"""AppTest coverage for the Phase 10d AI Network Designer page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents import WorkflowState
from config.settings import get_settings
from core.exceptions import (
    LLMAuthenticationError,
    LLMForbiddenError,
    LLMProviderError,
)
from services.llm.testing import FakeProvider
from tests.unit.simulation.helpers import diamond_twin
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.pages import ai_designer

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


@pytest.fixture
def configured_key(monkeypatch, request):
    """Set the sole supported key source and clear the cached settings."""

    def _set(secret: str) -> None:
        monkeypatch.setenv("GROQ_API_KEY", secret)
        get_settings.cache_clear()

    request.addfinalizer(get_settings.cache_clear)
    return _set


def extraction(**overrides: object) -> str:
    payload: dict[str, object] = {
        "organization_name": "",
        "site_name": "",
        "departments": [],
        "total_user_count": None,
        "constraints": [],
        "design_goals": [],
        "assumptions": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def designer_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    assert not at.exception
    open_page(at, "AI Network Designer")
    assert not at.exception
    return at


def rendered_text(at: AppTest) -> str:
    parts: list[str] = []
    for kind in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "code",
        "text",
        "info",
        "success",
        "error",
        "warning",
    ):
        for element in at.get(kind):
            parts.append(str(getattr(element, "value", "")))
    for metric in at.get("metric"):
        parts.append(f"{metric.label} {metric.value}")
    return "\n".join(parts)


def metric(at: AppTest, label: str) -> str:
    for item in at.get("metric"):
        if item.label == label:
            return item.value
    raise AssertionError(f"metric {label!r} was not rendered")


def test_without_a_key_only_the_form_is_shown() -> None:
    at = designer_page()

    assert any(
        "No API key is configured" in info.value for info in at.info
    )
    assert all(
        area.key != ai_designer.FREE_TEXT_KEY for area in at.text_area
    )
    assert all(
        button.key != ai_designer.INTERPRET_BUTTON for button in at.button
    )
    assert any(area.key == ai_designer.ORG_NAME_KEY for area in at.text_input)
    assert any(button.key == ai_designer.RUN_BUTTON for button in at.button)


def test_form_run_completes_without_a_key_and_keeps_the_baseline() -> None:
    baseline = diamond_twin()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = baseline
    at.run()
    open_page(at, "AI Network Designer")

    at.button(key=ai_designer.RUN_BUTTON).click().run()

    assert not at.exception
    assert any(
        "Workflow completed" in success.value for success in at.success
    )
    assert metric(at, "Steps") == "11"
    assert metric(at, "Verdict") == "APPROVED"
    plan_state = at.session_state[ai_designer.PLAN_STATE_KEY]
    assert isinstance(plan_state, WorkflowState)
    assert plan_state.stop_reason.value == "completed"
    assert at.session_state[state.TWIN_KEY] is baseline
    assert not at.session_state.to_dict().get(state.SNAPSHOTS_KEY)


def test_free_text_interpretation_keeps_facts_and_assumptions_separate(
    monkeypatch,
    configured_key,
) -> None:
    payload = extraction(
        organization_name="Acme",
        site_name="Headquarters",
        departments=[
            {"name": "Engineering", "user_count": 25},
            {"name": "Facilities", "user_count": None},
        ],
        total_user_count=25,
    )
    monkeypatch.setattr(
        ai_designer,
        "_build_provider",
        lambda api_key: FakeProvider([payload]),
    )
    configured_key("gsk-designer-test-key")
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "AI Network Designer")

    at.text_area(key=ai_designer.FREE_TEXT_KEY).set_value(
        "Acme has one site, Headquarters. Engineering has 25 users. "
        "Facilities is also on site."
    )
    at.button(key=ai_designer.INTERPRET_BUTTON).click().run()

    assert not at.exception
    assert metric(at, "Status") == "parsed"
    assert metric(at, "Model used") == "Yes"
    text = rendered_text(at)
    assert "User-provided facts" in text
    assert "System assumptions (not user facts)" in text
    assert "Missing information" in text
    assert "Clarification questions" in text
    output = at.session_state[ai_designer.UNDERSTANDING_KEY]
    assert output.facts is not None
    assert output.facts.total_user_count == 25
    assert any("Facilities" in item.description for item in output.assumptions)


def test_provider_failure_is_shown_without_crashing(monkeypatch, configured_key) -> None:
    monkeypatch.setattr(
        ai_designer,
        "_build_provider",
        lambda api_key: FakeProvider([LLMProviderError("provider is down")]),
    )
    configured_key("gsk-designer-test-key")
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "AI Network Designer")

    at.text_area(key=ai_designer.FREE_TEXT_KEY).set_value("A small office.")
    at.button(key=ai_designer.INTERPRET_BUTTON).click().run()

    assert not at.exception
    output = at.session_state[ai_designer.UNDERSTANDING_KEY]
    assert output.status.value == "failed"
    assert any("provider is down" in error.value for error in at.error)


@pytest.mark.parametrize(
    ("provider_error", "status"),
    (
        (
            LLMAuthenticationError(
                "The LLM provider rejected the API key. Check the configured key."
            ),
            401,
        ),
        (
            LLMForbiddenError(
                "The LLM provider blocked the request. Check provider permissions."
            ),
            403,
        ),
    ),
)
def test_provider_error_status_is_shown_in_interpretation(
    monkeypatch,
    configured_key,
    provider_error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(
        ai_designer,
        "_build_provider",
        lambda api_key: FakeProvider([provider_error]),
    )
    configured_key("gsk-designer-status-key")
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "AI Network Designer")

    at.text_area(key=ai_designer.FREE_TEXT_KEY).set_value("A small office.")
    at.button(key=ai_designer.INTERPRET_BUTTON).click().run()

    assert not at.exception
    output = at.session_state[ai_designer.UNDERSTANDING_KEY]
    assert output.status.value == "failed"
    assert f"HTTP {status}" in output.error
    assert any(f"HTTP {status}" in shown.value for shown in at.error)
    assert "gsk-designer-status-key" not in rendered_text(at)


def test_interpreted_requirements_drive_the_workflow(
    monkeypatch,
    configured_key,
) -> None:
    payload = extraction(
        organization_name="Interpreted Org",
        site_name="Remote",
        departments=[
            {"name": "Engineering", "user_count": 25},
            {"name": "Sales", "user_count": 12},
        ],
        total_user_count=37,
    )
    monkeypatch.setattr(
        ai_designer,
        "_build_provider",
        lambda api_key: FakeProvider([payload]),
    )
    configured_key("gsk-designer-test-key")
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "AI Network Designer")

    at.text_area(key=ai_designer.FREE_TEXT_KEY).set_value(
        "Interpreted Org has one site, Remote. Engineering has 25 users and "
        "Sales has 12 users. The total is 37 users."
    )
    at.button(key=ai_designer.INTERPRET_BUTTON).click().run()
    at.button(key=ai_designer.RUN_BUTTON).click().run()

    assert not at.exception
    plan_state = at.session_state[ai_designer.PLAN_STATE_KEY]
    requirements = plan_state.results["requirements"].requirements
    assert requirements.user_provided.organization.name == "Interpreted Org"
    assert requirements.user_provided.total_user_count == 37


def test_apply_creates_a_new_snapshot_and_never_replaces_the_baseline() -> None:
    baseline = diamond_twin()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = baseline
    at.run()
    open_page(at, "AI Network Designer")
    at.button(key=ai_designer.RUN_BUTTON).click().run()

    at.text_input(key=ai_designer.SNAPSHOT_LABEL_KEY).set_value("AI design test")
    at.button(key=ai_designer.APPLY_BUTTON).click().run()

    assert not at.exception
    store = at.session_state[state.SNAPSHOTS_KEY]
    assert len(store.snapshots) == 1
    assert store.snapshots[0].label == "AI design test"
    assert at.session_state[state.TWIN_KEY] is baseline
    assert any("Baseline unchanged" in success.value for success in at.success)


def test_configured_key_is_never_rendered_or_written_to_the_trace(
    monkeypatch,
    configured_key,
) -> None:
    secret = "gsk-designer-secret-must-not-leak"
    payload = extraction(
        organization_name="Acme",
        departments=[{"name": "Engineering", "user_count": 25}],
        total_user_count=25,
    )
    monkeypatch.setattr(
        ai_designer,
        "_build_provider",
        lambda api_key: FakeProvider([payload]),
    )
    configured_key(secret)
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "AI Network Designer")
    at.text_area(key=ai_designer.FREE_TEXT_KEY).set_value(
        "Acme. Engineering has 25 users. The total is 25 users."
    )
    at.button(key=ai_designer.INTERPRET_BUTTON).click().run()
    at.button(key=ai_designer.RUN_BUTTON).click().run()

    assert not at.exception
    assert secret not in rendered_text(at)
    plan_state = at.session_state[ai_designer.PLAN_STATE_KEY]
    assert secret not in plan_state.trace.to_json()
    for name, value in at.session_state.to_dict().items():
        assert secret not in str(value), f"session value {name!r} leaked the key"
