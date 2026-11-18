"""Settings page: optional LLM configuration and the structured plan runner.

The API key is optional. Core deterministic engineering and the structured
requirements form work without it. This page shows only whether a key is
configured and where it came from; it never displays, logs, serializes, or
echoes the key itself. A session-entered key lives in Streamlit session state
for this browser tab and is never persisted.
"""

from __future__ import annotations

import streamlit as st

from config.limits import (
    MAX_AGENT_REPLANS,
    MAX_AGENT_RETRIES,
    MAX_AGENT_RUNTIME_SECONDS,
    MAX_LLM_CALLS_PER_SESSION,
    MAX_LLM_RATE_LIMIT_RETRIES,
    MAX_LLM_REPAIR_RETRIES,
    MAX_LLM_RESPONSE_TOKENS,
    MAX_LLM_RETRY_AFTER_SECONDS,
    MAX_LLM_TIMEOUT_SECONDS,
    MAX_LLM_TOKENS_PER_SESSION,
    MAX_WORKFLOW_STEPS,
)
from config.settings import get_settings
from core.exceptions import NetArchitectError
from services.llm import GroqProvider, LLMMessage, MessageRole, RequestBudget
from ui import state
from ui.components import format_error, page_header
from ui.components.requirements_form import render_requirements_form

KEY_ENTRY_KEY = "llm_key_entry"
SAVE_KEY_BUTTON = "llm_key_save"
CLEAR_KEY_BUTTON = "llm_key_clear"
TEST_BUTTON = "llm_test_connection"

TEST_PROMPT = "Reply with the single word: OK"
TEST_TIMEOUT_SECONDS = 15.0


def _build_provider(api_key: str, budget: RequestBudget) -> GroqProvider:
    """Build a bounded provider for the one-request connection test.

    Kept as a module-level function so tests can substitute a fake provider and
    never contact the network.
    """
    return GroqProvider.from_settings(
        api_key=api_key,
        budget=budget,
        timeout=TEST_TIMEOUT_SECONDS,
        max_rate_limit_retries=0,
        max_repair_retries=0,
    )


def _save_session_key() -> None:
    state.set_llm_session_key(str(st.session_state.get(KEY_ENTRY_KEY, "")))


def _clear_session_key() -> None:
    state.clear_llm_session_key()
    st.session_state[KEY_ENTRY_KEY] = ""


def _render_key_status(settings_key: str, session_key: str) -> tuple[str, str]:
    """Render the yes/no key status and return the active key and its source."""
    if session_key:
        active, source = session_key, "session (this browser tab only)"
    elif settings_key:
        active, source = settings_key, "environment or Streamlit secrets"
    else:
        active, source = "", "not configured"
    columns = st.columns(3)
    columns[0].metric("API key configured", "Yes" if active else "No")
    columns[1].metric("Model", get_settings().GROQ_MODEL)
    columns[2].metric("Key source", source)
    st.caption(
        "The key itself is never displayed, logged, traced, or stored on disk. "
        "A session key is held only in this browser tab and disappears when the "
        "session ends."
    )
    return active, source


def _render_key_entry() -> None:
    st.text_input(
        "Session API key (optional)",
        type="password",
        key=KEY_ENTRY_KEY,
        help=(
            "Used only for this browser session. Prefer environment variables or "
            "Streamlit secrets for deployments."
        ),
    )
    save_column, clear_column = st.columns(2)
    save_column.button(
        "Use key for this session",
        key=SAVE_KEY_BUTTON,
        on_click=_save_session_key,
    )
    clear_column.button(
        "Clear session key",
        key=CLEAR_KEY_BUTTON,
        on_click=_clear_session_key,
    )


def _render_budget() -> None:
    budget = state.get_llm_budget()
    snapshot = budget.snapshot()
    st.markdown("**Session request budget**")
    columns = st.columns(3)
    columns[0].metric(
        "Requests used",
        f"{snapshot['used_calls']}/{snapshot['max_calls']}",
    )
    columns[1].metric(
        "Tokens used",
        f"{snapshot['used_tokens']}/{snapshot['max_tokens']}",
    )
    columns[2].metric("Requests remaining", snapshot["remaining_calls"])
    st.progress(
        min(1.0, snapshot["used_calls"] / max(1, snapshot["max_calls"])),
        text="Request budget used",
    )
    st.progress(
        min(1.0, snapshot["used_tokens"] / max(1, snapshot["max_tokens"])),
        text="Token budget used",
    )
    st.button(
        "Reset session budget",
        key="llm_budget_reset",
        on_click=state.reset_llm_budget,
    )


def _render_test_connection(active_key: str) -> None:
    st.markdown("**Connection test**")
    st.caption(
        "Bounded test: one request, a "
        f"{TEST_TIMEOUT_SECONDS:.0f}-second timeout, no rate-limit retries, and "
        "no structured-output repairs. The request counts against the session "
        "budget above."
    )
    if not active_key:
        st.info("Add a key for this session or configure one to enable the test.")
    if st.button(
        "Test connection",
        key=TEST_BUTTON,
        disabled=not bool(active_key),
    ):
        try:
            provider = _build_provider(active_key, state.get_llm_budget())
            response = provider.complete(
                [LLMMessage(role=MessageRole.user, content=TEST_PROMPT)],
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except NetArchitectError as error:
            st.error(format_error(error))
        except ValueError as error:
            st.error(format_error(error))
        else:
            st.success(
                f"Connected. Provider reported model {response.model}; "
                f"{response.usage.total_tokens} token(s) used."
            )


def _render_limits() -> None:
    st.markdown("**Read-only limits**")
    st.caption(
        "These bounds are compiled into the application. Change them in "
        "`config/limits.py`; this page never overrides them."
    )
    rows = [
        ("LLM calls per session", MAX_LLM_CALLS_PER_SESSION),
        ("LLM tokens per session", MAX_LLM_TOKENS_PER_SESSION),
        ("LLM repair attempts", MAX_LLM_REPAIR_RETRIES),
        ("LLM rate-limit retries", MAX_LLM_RATE_LIMIT_RETRIES),
        ("LLM request timeout (s)", MAX_LLM_TIMEOUT_SECONDS),
        ("LLM backoff cap (s)", MAX_LLM_RETRY_AFTER_SECONDS),
        ("LLM response tokens", MAX_LLM_RESPONSE_TOKENS),
        ("Agent attempts per task", MAX_AGENT_RETRIES),
        ("Workflow steps", MAX_WORKFLOW_STEPS),
        ("Workflow runtime (s)", MAX_AGENT_RUNTIME_SECONDS),
        ("Workflow re-plans", MAX_AGENT_REPLANS),
    ]
    st.dataframe(
        [{"limit": name, "value": value} for name, value in rows],
        hide_index=True,
        width="stretch",
    )


def _render_documentation() -> None:
    st.markdown("**Deployment configuration**")
    st.write(
        "Secrets and environment variables are read once by "
        "`config.settings.get_settings()`. Precedence is Streamlit secrets, then "
        "environment variables, then the documented defaults."
    )
    st.code(
        '# .streamlit/secrets.toml (never commit the real file)\n'
        'GROQ_API_KEY = "your-key-here"\n'
        'GROQ_MODEL = "llama-3.3-70b-versatile"\n'
        'GROQ_BASE_URL = "https://api.groq.com/openai/v1"\n',
        language="toml",
    )
    st.caption(
        "Equivalent environment variables: GROQ_API_KEY, GROQ_MODEL, "
        "GROQ_BASE_URL. The documented model name is a default only; Groq "
        "retires models, so set GROQ_MODEL explicitly for a deployment."
    )
    st.warning(
        "Keys pasted into this page live only in Streamlit session state for "
        "this browser tab. They are not written to snapshots, traces, logs, "
        "downloads, or the repository."
    )


def render() -> None:
    """Render the Settings page."""
    page_header(
        "Settings",
        "Optional AI configuration, read-only safety limits, and a deterministic "
        "structured design runner that needs no API key.",
    )

    settings = get_settings()
    settings_key = settings.GROQ_API_KEY.strip()
    session_key = state.get_llm_session_key()

    st.header("AI provider (optional)")
    active_key, _ = _render_key_status(settings_key, session_key)
    _render_key_entry()
    _render_budget()
    _render_test_connection(active_key)

    st.subheader("What needs an API key")
    st.markdown(
        "- Natural-language requirement interpretation and clarification.\n"
        "- Plain-language explanations of plans and recommendations.\n"
        "- Generated report prose and agent narrative.\n"
    )
    st.markdown(
        "**Never required:** topology design, IP/VLAN planning, routing, "
        "analysis, the digital twin, simulation, optimization, and the "
        "deterministic structured plan below. Those are pure engineering "
        "engines and do not import the provider layer."
    )

    _render_limits()
    _render_documentation()

    st.divider()
    render_requirements_form()


__all__ = [
    "CLEAR_KEY_BUTTON",
    "KEY_ENTRY_KEY",
    "SAVE_KEY_BUTTON",
    "TEST_BUTTON",
    "TEST_PROMPT",
    "TEST_TIMEOUT_SECONDS",
    "render",
]
