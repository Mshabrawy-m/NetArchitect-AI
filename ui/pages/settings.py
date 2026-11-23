"""Settings page: optional LLM configuration and the structured plan runner.

The API key is optional. Core deterministic engineering and the structured
requirements form work without it. This page shows only whether a key is
configured and where it came from; it never displays, logs, serializes, or
echoes the key itself. The key is read only from Streamlit secrets or
environment variables through ``config.settings``.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from ui import i18n, state
from ui.components import format_error, page_header
from ui.components.feedback import working
from ui.components.requirements_form import render_requirements_form

TEST_BUTTON = "llm_test_connection"

TEST_PROMPT = "Reply with the single word: OK"
TEST_TIMEOUT_SECONDS = 15.0


def _render_language() -> None:
    """Render the session-only interface language control."""
    st.segmented_control(
        i18n.t("settings.language.label"),
        options=tuple(i18n.LANGUAGES),
        format_func=lambda code: i18n.LANGUAGES[code],
        default=i18n.DEFAULT_LANGUAGE,
        required=True,
        key=i18n.LANGUAGE_KEY,
        help=i18n.t("settings.language.help"),
        persist_state="session",
    )


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


def _render_key_status(settings_key: str, key_source: str) -> str:
    """Render the non-secret key status and return the configured key."""
    source_labels = {
        "secrets": i18n.t("settings.key_source_secrets"),
        "environment": i18n.t("settings.key_source_environment"),
        "none": i18n.t("settings.key_source_none"),
    }
    source = source_labels.get(key_source, source_labels["none"])
    columns = st.columns(3)
    columns[0].metric(
        i18n.t("settings.key_configured"),
        i18n.t("common.yes") if settings_key else i18n.t("common.no"),
    )
    columns[1].metric(i18n.t("settings.model"), i18n.ltr(get_settings().GROQ_MODEL))
    columns[2].metric(i18n.t("settings.key_source"), source)
    st.caption(i18n.t("settings.key_privacy"))
    return settings_key


def _reported(value: object) -> str:
    """Render one provider field without inventing a missing value."""
    return i18n.t("settings.not_reported") if value is None else i18n.ltr(str(value))


def _last_call_time(value: object) -> str:
    """Render an injected response timestamp as UTC, if available."""
    if value is None:
        return i18n.t("settings.not_reported")
    try:
        moment = datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return i18n.t("settings.not_reported")
    return i18n.ltr(moment.strftime("%Y-%m-%d %H:%M:%S UTC"))


def _render_budget() -> None:
    budget = state.get_llm_budget()
    snapshot = budget.snapshot()
    limits = snapshot["provider_limits"]
    if not isinstance(limits, dict):
        limits = {}

    st.markdown(f"**{i18n.t('settings.app_safeguard')}**")
    st.caption(i18n.t("settings.app_safeguard_caption"))
    columns = st.columns(4)
    columns[0].metric(
        i18n.t("settings.requests_used"),
        f"{snapshot['used_calls']}/{snapshot['max_calls']}",
    )
    columns[1].metric(
        i18n.t("settings.tokens_used"),
        f"{snapshot['used_tokens']}/{snapshot['max_tokens']}",
    )
    columns[2].metric(
        i18n.t("settings.requests_remaining"), snapshot["remaining_calls"]
    )
    columns[3].metric(
        i18n.t("settings.tokens_remaining"), snapshot["remaining_tokens"]
    )
    st.progress(
        min(1.0, snapshot["used_calls"] / max(1, snapshot["max_calls"])),
        text=i18n.t("settings.request_budget_used"),
    )
    st.progress(
        min(1.0, snapshot["used_tokens"] / max(1, snapshot["max_tokens"])),
        text=i18n.t("settings.token_budget_used"),
    )
    st.button(
        i18n.t("settings.budget_reset"),
        key="llm_budget_reset",
        on_click=state.reset_llm_budget,
    )

    st.markdown(f"**{i18n.t('settings.provider_limits_title')}**")
    st.caption(i18n.t("settings.provider_limits_caption"))
    if snapshot["last_call_at"] is None:
        st.info(i18n.t("settings.provider_limits_empty"))
    provider_columns = st.columns(5)
    provider_columns[0].metric(
        i18n.t("settings.provider_remaining_requests"),
        _reported(limits.get("remaining_requests")),
    )
    provider_columns[1].metric(
        i18n.t("settings.provider_remaining_tokens"),
        _reported(limits.get("remaining_tokens")),
    )
    provider_columns[2].metric(
        i18n.t("settings.provider_reset_requests"),
        _reported(limits.get("reset_requests")),
    )
    provider_columns[3].metric(
        i18n.t("settings.provider_reset_tokens"),
        _reported(limits.get("reset_tokens")),
    )
    provider_columns[4].metric(
        i18n.t("settings.provider_retry_after"),
        _reported(limits.get("retry_after")),
    )

    source = snapshot["last_usage_source"]
    source_label = (
        i18n.t("settings.usage_reported")
        if source == "reported"
        else i18n.t("settings.usage_estimated")
        if source == "estimated"
        else i18n.t("settings.not_reported")
    )
    total_columns = st.columns(4)
    total_columns[0].metric(
        i18n.t("settings.real_tokens_used"), snapshot["real_tokens"]
    )
    total_columns[1].metric(
        i18n.t("settings.estimated_tokens_used"), snapshot["estimated_tokens"]
    )
    total_columns[2].metric(
        i18n.t("settings.last_call_time"), _last_call_time(snapshot["last_call_at"])
    )
    total_columns[3].metric(i18n.t("settings.last_usage_source"), source_label)


def _render_cache_and_trace() -> None:
    """Show bounded cache counters and non-secret prompt trace metadata."""
    cache = state.get_copilot_cache().snapshot()
    st.markdown(f"**{i18n.t('settings.cache_title')}**")
    st.caption(i18n.t("settings.cache_caption"))
    columns = st.columns(3)
    columns[0].metric(i18n.t("settings.cache_hits"), cache["hits"])
    columns[1].metric(i18n.t("settings.cache_misses"), cache["misses"])
    columns[2].metric(
        i18n.t("settings.cache_entries"),
        f"{cache['entries']}/{cache['max_entries']}",
    )
    st.button(
        i18n.t("settings.cache_reset"),
        key="copilot_cache_reset",
        on_click=state.reset_copilot_cache,
    )

    st.markdown(f"**{i18n.t('settings.trace_title')}**")
    st.caption(i18n.t("settings.trace_caption"))
    rows = state.peek_copilot_trace().rows()
    if rows:
        st.dataframe(list(rows), hide_index=True, width="stretch")
    else:
        st.info(i18n.t("settings.trace_empty"))


def _render_test_connection(active_key: str) -> None:
    st.markdown(f"**{i18n.t('settings.connection')}**")
    st.caption(
        i18n.t("settings.connection_caption", seconds=f"{TEST_TIMEOUT_SECONDS:.0f}")
    )
    if not active_key:
        st.info(i18n.t("settings.connection_add_key"))
    if st.button(
        i18n.t("settings.connection_button"),
        key=TEST_BUTTON,
        disabled=not bool(active_key),
    ):
        try:
            with working(i18n.t("loading.connection")):
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
            usage_source = (
                i18n.t("settings.usage_estimated")
                if response.usage.source == "estimated"
                else i18n.t("settings.usage_reported")
            )
            st.success(
                i18n.t(
                    "settings.connection_success",
                    model=i18n.ltr(response.model),
                    tokens=response.usage.total_tokens,
                    usage_source=usage_source,
                )
            )


def _render_limits() -> None:
    st.markdown(f"**{i18n.t('settings.limits')}**")
    st.caption(i18n.t("settings.limits_caption"))
    rows = [
        (i18n.t("settings.limit.llm_calls"), MAX_LLM_CALLS_PER_SESSION),
        (i18n.t("settings.limit.llm_tokens"), MAX_LLM_TOKENS_PER_SESSION),
        (i18n.t("settings.limit.llm_repairs"), MAX_LLM_REPAIR_RETRIES),
        (i18n.t("settings.limit.llm_retries"), MAX_LLM_RATE_LIMIT_RETRIES),
        (i18n.t("settings.limit.llm_timeout"), MAX_LLM_TIMEOUT_SECONDS),
        (i18n.t("settings.limit.llm_backoff"), MAX_LLM_RETRY_AFTER_SECONDS),
        (
            i18n.t("settings.limit.llm_response_tokens"),
            MAX_LLM_RESPONSE_TOKENS,
        ),
        (i18n.t("settings.limit.agent_attempts"), MAX_AGENT_RETRIES),
        (i18n.t("settings.limit.workflow_steps"), MAX_WORKFLOW_STEPS),
        (i18n.t("settings.limit.workflow_runtime"), MAX_AGENT_RUNTIME_SECONDS),
        (i18n.t("settings.limit.workflow_replans"), MAX_AGENT_REPLANS),
    ]
    st.dataframe(
        [{"limit": name, "value": value} for name, value in rows],
        hide_index=True,
        width="stretch",
    )


def _render_documentation() -> None:
    st.markdown(f"**{i18n.t('settings.deployment')}**")
    st.write(i18n.t("settings.deployment_body"))
    st.code(
        '# .streamlit/secrets.toml (never commit the real file)\n'
        'GROQ_API_KEY = "your-key-here"\n'
        'GROQ_MODEL = "llama-3.3-70b-versatile"\n'
        'GROQ_BASE_URL = "https://api.groq.com/openai/v1"\n',
        language="toml",
    )
    st.caption(i18n.t("settings.deployment_caption"))
    st.warning(i18n.t("settings.deployment_warning"))


def _render_limitations() -> None:
    """State the release scope and verification limits in the app itself."""
    st.markdown(f"**{i18n.t('settings.limitations')}**")
    st.warning(i18n.t("settings.limitations_warning"))
    st.markdown(i18n.t("settings.limitations_body"))


def render() -> None:
    """Render the Settings page."""
    page_header(i18n.t("page.settings"), i18n.t("page.settings.description"))
    _render_language()

    settings = get_settings()
    settings_key = settings.GROQ_API_KEY.strip()

    st.header(i18n.t("settings.provider"))
    active_key = _render_key_status(settings_key, settings.GROQ_KEY_SOURCE)
    _render_test_connection(active_key)
    _render_budget()
    _render_cache_and_trace()

    st.subheader(i18n.t("settings.needs_key"))
    st.markdown(i18n.t("settings.needs_key_list"))
    st.markdown(i18n.t("settings.never_required"))

    _render_limits()
    _render_documentation()
    _render_limitations()

    st.divider()
    render_requirements_form()


__all__ = [
    "TEST_BUTTON",
    "TEST_PROMPT",
    "TEST_TIMEOUT_SECONDS",
    "render",
]
