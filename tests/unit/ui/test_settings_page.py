"""AppTest coverage for the Phase 9c Settings page and structured form."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents import WorkflowState, WorkflowStopReason
from config.settings import get_settings
from core.exceptions import LLMProviderError
from services.copilot import AIExplanationDraft, CopilotCache, PromptTrace, build_key
from services.llm import LLMMessage, LLMResponse, LLMUsage, MessageRole, RequestBudget
from services.llm.testing import FakeProvider
from tests.unit.simulation.helpers import diamond_twin
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.components.requirements_form import PLAN_STATE_KEY, RUN_BUTTON_KEY
from ui.pages import settings as settings_page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


@pytest.fixture
def configured_key(monkeypatch, request):
    """Set the sole supported key source and clear the cached settings."""

    def _set(secret: str) -> None:
        monkeypatch.setenv("GROQ_API_KEY", secret)
        get_settings.cache_clear()

    request.addfinalizer(get_settings.cache_clear)
    return _set


def test_streamlit_config_disables_the_file_watcher() -> None:
    config_path = APP_PATH.parent / ".streamlit" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert config["server"]["fileWatcherType"] == "none"


def _settings_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception
    open_page(at, "Settings")
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
    assert any("Configure a key" in info.value for info in at.info)
    assert any("Never required" in markdown.value for markdown in at.markdown)
    assert at.code
    assert any(
        "Secrets and environment variables" in markdown.value
        for markdown in at.markdown
    )
    assert any("Read-only limits" in markdown.value for markdown in at.markdown)
    assert "Provider rate limits (from last response)" in _rendered_text(at)
    assert "not reported" in _rendered_text(at)
    assert any(
        "Connection test" in info.value for info in at.info
    ) or any(
        "Connection test" in caption.value for caption in at.caption
    )
    assert at.get("dataframe")
    assert at.button(key=RUN_BUTTON_KEY)


def test_settings_page_shows_key_presence_but_never_the_key(configured_key) -> None:
    secret = "gsk-test-environment-secret-do-not-render"
    configured_key(secret)
    at = _settings_page()

    assert _metric(at, "API key configured") == "Yes"
    assert _metric(at, "Key source") == "environment variable"
    assert not at.button(key=settings_page.TEST_BUTTON).disabled
    assert secret not in _rendered_text(at)
    for name, value in at.session_state.to_dict().items():
        assert secret not in str(value), f"session value {name!r} leaked the key"


def test_settings_page_has_no_session_key_input_widget() -> None:
    at = _settings_page()

    key_widgets = [
        widget
        for widget in at.text_input
        if "key" in f"{widget.label} {widget.key or ''}".lower()
    ]

    assert key_widgets == []
    assert not hasattr(settings_page, "KEY_ENTRY_KEY")


def test_configured_key_is_never_written_to_session_state(configured_key) -> None:
    secret = "gsk-not-in-session"
    configured_key(secret)
    at = _settings_page()

    assert secret not in str(at.session_state.to_dict())


def test_settings_page_shows_and_resets_the_session_budget() -> None:
    budget = RequestBudget()
    budget.used_calls = 3
    budget.used_tokens = 1_200
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state[state.LLM_BUDGET_KEY] = budget
    at.run()
    open_page(at, "Settings")

    assert _metric(at, "Requests used") == f"3/{budget.max_calls}"
    assert _metric(at, "Tokens used") == f"1200/{budget.max_tokens}"
    assert _metric(at, "Requests remaining") == str(budget.max_calls - 3)
    assert _metric(at, "Tokens remaining") == str(budget.max_tokens - 1_200)

    at.button(key="llm_budget_reset").click().run()
    assert _metric(at, "Requests used") == f"0/{budget.max_calls}"
    assert _metric(at, "Requests remaining") == str(budget.max_calls)
    assert _metric(at, "Tokens remaining") == str(budget.max_tokens)


def test_settings_page_shows_and_clears_cache_hits_and_prompt_trace() -> None:
    cache = CopilotCache(max_entries=3)
    key = build_key(
        model="fake-model",
        prompt_id="copilot.explain",
        prompt_version="1",
        schema_name="AIExplanationDraft",
        payload={"text": "hello"},
    )
    cache.put(key, AIExplanationDraft(text="one"))
    assert cache.get(key, AIExplanationDraft) is not None

    trace = PromptTrace()
    trace.add(
        prompt_id="copilot.explain",
        prompt_version="1",
        schema_name="AIExplanationDraft",
        model="fake-model",
        cache_hit=True,
    )
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state[state.COPILOT_CACHE_KEY] = cache
    at.session_state[state.COPILOT_TRACE_KEY] = trace
    at.run()
    open_page(at, "Settings")

    assert not at.exception
    assert _metric(at, "Cache hits") == "1"
    assert _metric(at, "Cache misses") == "0"
    assert _metric(at, "Cached entries") == "1/3"
    trace_frames = [
        frame.value
        for frame in at.get("dataframe")
        if "Prompt" in getattr(frame.value, "columns", [])
    ]
    assert trace_frames
    assert "copilot.explain" in trace_frames[0].to_string()
    assert at.button(key="copilot_cache_reset")

    at.button(key="copilot_cache_reset").click().run()

    assert not at.exception
    assert _metric(at, "Cache hits") == "0"
    assert _metric(at, "Cached entries") == "0/3"


def test_settings_page_test_connection_reports_provider_failure(
    monkeypatch,
    configured_key,
) -> None:
    class UnavailableProvider:
        def complete(self, messages, schema=None, *, timeout=None):
            raise LLMProviderError("Groq is unreachable in this test.")

    def fake_builder(api_key: str, budget: RequestBudget) -> UnavailableProvider:
        assert api_key == "gsk-test-key"
        return UnavailableProvider()

    monkeypatch.setattr(settings_page, "_build_provider", fake_builder)
    configured_key("gsk-test-key")

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    open_page(at, "Settings")
    at.button(key=settings_page.TEST_BUTTON).click().run()

    assert not at.exception
    assert any("unreachable" in error.value for error in at.error)
    assert not any("gsk-test-key" in error.value for error in at.error)
    assert "gsk-test-key" not in str(at.session_state.to_dict())


def test_first_click_connection_test_from_empty_state(monkeypatch, configured_key) -> None:
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
    configured_key("gsk-test-key")

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    open_page(at, "Settings")
    assert not at.button(key=settings_page.TEST_BUTTON).disabled
    assert all(
        "key" not in f"{widget.label} {widget.key or ''}".lower()
        for widget in at.text_input
    )

    at.button(key=settings_page.TEST_BUTTON).click().run()

    assert not at.exception
    assert any("llama-test" in success.value for success in at.success)
    assert any("7 token" in success.value for success in at.success)
    assert "gsk-test-key" not in str(at.session_state.to_dict())


def test_settings_page_shows_provider_limits_after_a_call(
    monkeypatch,
    configured_key,
) -> None:
    fixed_now = 1_700_000_123.0
    headers = {
        "x-ratelimit-remaining-requests": "42",
        "x-ratelimit-remaining-tokens": "7000",
        "x-ratelimit-reset-requests": "1800",
        "x-ratelimit-reset-tokens": "3600",
        "retry-after": "2",
    }

    def fake_builder(api_key: str, budget: RequestBudget) -> FakeProvider:
        assert api_key == "gsk-limits-test-key"
        return FakeProvider(
            ["OK"],
            budget=budget,
            headers=headers,
            usage=LLMUsage(prompt_tokens=11, completion_tokens=4, total_tokens=15),
            clock=lambda: fixed_now,
        )

    monkeypatch.setattr(settings_page, "_build_provider", fake_builder)
    configured_key("gsk-limits-test-key")
    at = _settings_page()

    assert "not reported" in _rendered_text(at)

    at.button(key=settings_page.TEST_BUTTON).click().run()

    assert not at.exception
    rendered = _rendered_text(at)
    assert "App safeguard" in rendered
    assert "Provider rate limits (from last response)" in rendered
    assert "not account billing or monthly usage" in rendered
    assert _metric(at, "Provider remaining Requests") == "42"
    assert _metric(at, "Provider remaining tokens") == "7000"
    assert _metric(at, "Provider reset (Requests)") == "1800.0"
    assert _metric(at, "Provider reset (tokens)") == "3600.0"
    assert _metric(at, "Provider Retry-After") == "2.0"
    assert _metric(at, "Real tokens used this session") == "15"
    assert _metric(at, "Last usage source") == "provider-reported"
    assert "UTC" in _metric(at, "Last call time")


def test_cache_hit_does_not_change_llm_counters() -> None:
    budget = RequestBudget()
    provider = FakeProvider(
        ["OK"],
        budget=budget,
        headers={"x-ratelimit-remaining-requests": "9"},
        usage=LLMUsage(total_tokens=8),
    )
    cache = CopilotCache(max_entries=2)
    key = build_key(
        model="fake-model",
        prompt_id="copilot.explain",
        prompt_version="1",
        schema_name="AIExplanationDraft",
        payload={"text": "hello"},
    )
    response = provider.complete(
        [LLMMessage(role=MessageRole.user, content="hello")]
    )
    cache.put(key, response)
    after_first_call = budget.snapshot()

    assert cache.get(key, LLMResponse) is not None
    assert budget.snapshot() == after_first_call


def test_settings_page_runs_the_deterministic_plan_from_the_form() -> None:
    baseline = diamond_twin()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = baseline
    at.run()
    open_page(at, "Settings")

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
