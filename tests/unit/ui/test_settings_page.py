"""AppTest coverage for the Phase 9c Settings page and structured form."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from agents import WorkflowState, WorkflowStopReason
from core.exceptions import LLMProviderError
from services.llm import LLMResponse, LLMUsage, RequestBudget
from tests.unit.simulation.helpers import diamond_twin
from ui import state
from ui.components.requirements_form import PLAN_STATE_KEY, RUN_BUTTON_KEY
from ui.pages import settings as settings_page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _settings_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception
    at.selectbox(key="page_nav").select("Settings").run()
    assert not at.exception
    return at


def _rendered_text(at: AppTest) -> str:
    """Collect everything the page displays, excluding input widget values."""
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


def _metric(at: AppTest, label: str) -> str:
    for metric in at.get("metric"):
        if metric.label == label:
            return metric.value
    raise AssertionError(f"metric {label!r} was not rendered")


def test_settings_page_without_a_key_explains_what_is_optional() -> None:
    at = _settings_page()

    assert _metric(at, "API key configured") == "No"
    assert _metric(at, "Key source") == "not configured"
    assert at.button(key=settings_page.TEST_BUTTON).disabled
    assert any("Add a key" in info.value for info in at.info)
    assert any("Never required" in markdown.value for markdown in at.markdown)
    assert at.code
    assert any(
        "Secrets and environment variables" in markdown.value
        for markdown in at.markdown
    )
    assert any("Read-only limits" in markdown.value for markdown in at.markdown)
    assert at.get("dataframe")
    assert at.button(key=RUN_BUTTON_KEY)


def test_settings_page_shows_key_presence_but_never_the_key() -> None:
    secret = "gsk-test-session-secret-do-not-render"
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state[state.LLM_SESSION_KEY] = secret
    at.run()
    at.selectbox(key="page_nav").select("Settings").run()

    assert not at.exception
    assert _metric(at, "API key configured") == "Yes"
    assert "session" in _metric(at, "Key source")
    assert not at.button(key=settings_page.TEST_BUTTON).disabled
    assert secret not in _rendered_text(at)
    assert at.session_state[state.LLM_SESSION_KEY] == secret
    for name, value in at.session_state.to_dict().items():
        if name == state.LLM_SESSION_KEY:
            continue
        assert secret not in str(value), f"session key {name!r} leaked the secret"


def test_settings_page_saves_and_clears_a_session_key() -> None:
    secret = "gsk-second-test-secret"
    at = _settings_page()

    at.text_input(key=settings_page.KEY_ENTRY_KEY).set_value(secret)
    at.button(key=settings_page.SAVE_KEY_BUTTON).click().run()

    assert not at.exception
    assert at.session_state[state.LLM_SESSION_KEY] == secret
    assert _metric(at, "API key configured") == "Yes"
    assert secret not in _rendered_text(at)

    at.button(key=settings_page.CLEAR_KEY_BUTTON).click().run()
    assert not at.exception
    assert state.LLM_SESSION_KEY not in at.session_state.to_dict()
    assert _metric(at, "API key configured") == "No"


def test_settings_page_shows_and_resets_the_session_budget() -> None:
    budget = RequestBudget()
    budget.used_calls = 3
    budget.used_tokens = 1_200
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state[state.LLM_BUDGET_KEY] = budget
    at.run()
    at.selectbox(key="page_nav").select("Settings").run()

    assert _metric(at, "Requests used") == f"3/{budget.max_calls}"
    assert _metric(at, "Tokens used") == f"1200/{budget.max_tokens}"
    assert _metric(at, "Requests remaining") == str(budget.max_calls - 3)

    at.button(key="llm_budget_reset").click().run()
    assert _metric(at, "Requests used") == f"0/{budget.max_calls}"
    assert _metric(at, "Requests remaining") == str(budget.max_calls)


def test_settings_page_test_connection_reports_provider_failure(
    monkeypatch,
) -> None:
    class UnavailableProvider:
        def complete(self, messages, schema=None, *, timeout=None):
            raise LLMProviderError("Groq is unreachable in this test.")

    def fake_builder(api_key: str, budget: RequestBudget) -> UnavailableProvider:
        assert api_key == "gsk-test-key"
        return UnavailableProvider()

    monkeypatch.setattr(settings_page, "_build_provider", fake_builder)

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state[state.LLM_SESSION_KEY] = "gsk-test-key"
    at.run()
    at.selectbox(key="page_nav").select("Settings").run()
    at.button(key=settings_page.TEST_BUTTON).click().run()

    assert not at.exception
    assert any("unreachable" in error.value for error in at.error)
    assert not any("gsk-test-key" in error.value for error in at.error)


def test_settings_page_test_connection_reports_success(monkeypatch) -> None:
    class FakeProvider:
        def complete(self, messages, schema=None, *, timeout=None):
            return LLMResponse(
                text="OK",
                model="llama-test",
                usage=LLMUsage(total_tokens=7),
            )

    def fake_builder(api_key: str, budget: RequestBudget) -> FakeProvider:
        return FakeProvider()

    monkeypatch.setattr(settings_page, "_build_provider", fake_builder)

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state[state.LLM_SESSION_KEY] = "gsk-test-key"
    at.run()
    at.selectbox(key="page_nav").select("Settings").run()
    at.button(key=settings_page.TEST_BUTTON).click().run()

    assert not at.exception
    assert any("llama-test" in success.value for success in at.success)
    assert any("7 token" in success.value for success in at.success)


def test_settings_page_runs_the_deterministic_plan_from_the_form() -> None:
    baseline = diamond_twin()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = baseline
    at.run()
    at.selectbox(key="page_nav").select("Settings").run()

    at.button(key=RUN_BUTTON_KEY).click().run()

    assert not at.exception
    plan_state = at.session_state[PLAN_STATE_KEY]
    assert isinstance(plan_state, WorkflowState)
    assert plan_state.stop_reason is WorkflowStopReason.completed
    assert plan_state.succeeded()
    assert len(plan_state.tasks) == 11
    assert plan_state.steps == 11
    assert plan_state.working_twin is not None
    assert "baseline_twin" not in plan_state.to_dict()
    assert at.session_state[state.TWIN_KEY] == baseline
    assert any(
        "Structured design plan completed" in markdown.value
        for markdown in at.markdown
    )
    assert at.download_button(key="download_structured_plan_trace")


def test_settings_page_reports_a_form_validation_error() -> None:
    at = _settings_page()

    at.text_input(key="req_dept_name_0").set_value("")
    at.text_input(key="req_dept_name_1").set_value("")
    at.button(key=RUN_BUTTON_KEY).click().run()

    assert not at.exception
    assert any("department" in error.value.lower() for error in at.error)
    assert PLAN_STATE_KEY not in at.session_state.to_dict()
