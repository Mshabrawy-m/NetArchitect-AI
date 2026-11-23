"""Shared presentation helpers for bounded copilot explanations."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st
from pydantic import ValidationError

from config.limits import MAX_COPILOT_CACHE_ENTRIES
from config.settings import get_settings
from core.exceptions import NetArchitectError
from services.copilot import ExplanationRequest, ExplanationResult, explain
from services.llm import GroqProvider
from ui import state
from ui.components import format_error

EXPLANATION_STATE_KEY = "copilot_explanation_results"


def _provider():
    """Build a bounded provider only when a session or configured key exists."""
    key = get_settings().GROQ_API_KEY.strip()
    if not key:
        return None
    return GroqProvider.from_settings(
        api_key=key,
        budget=state.get_llm_budget(),
    )


def _store(key: str, result: ExplanationResult) -> None:
    stored = dict(state.session_get(EXPLANATION_STATE_KEY, {}))
    stored[key] = result
    while len(stored) > MAX_COPILOT_CACHE_ENTRIES:
        oldest = next(iter(stored))
        stored.pop(oldest)
    state.session_set(EXPLANATION_STATE_KEY, stored)


def render_explanation(result: ExplanationResult) -> None:
    """Render the deterministic explanation and any audited advisory prose."""
    st.caption("Deterministic explanation")
    st.markdown(result.deterministic_text)
    if result.ai_text:
        st.caption("AI-generated (advisory only; numeric and scope audited)")
        st.markdown(result.ai_text)
    if result.ai_rejection:
        st.caption(result.ai_rejection)
    st.caption(
        f"Prompt {result.prompt_id} v{result.prompt_version}"
        + (" · cache hit" if result.cache_hit else "")
    )


def why_button(
    key: str,
    build_request: Callable[[], ExplanationRequest],
    *,
    label: str = "Why?",
) -> ExplanationResult | None:
    """Show a bounded explanation for one already-computed engineering result."""
    if st.button(label, key=key, help="Explain this computed result"):
        try:
            result = explain(
                build_request(),
                provider=_provider(),
                cache=state.get_copilot_cache(),
                trace=state.get_copilot_trace(),
            )
        except (NetArchitectError, ValidationError, ValueError) as error:
            st.error(format_error(error), title="Explanation failed")
            return None
        _store(key, result)

    stored = state.session_get(EXPLANATION_STATE_KEY, {})
    result = stored.get(key) if isinstance(stored, dict) else None
    if isinstance(result, ExplanationResult):
        render_explanation(result)
        return result
    return None


__all__ = ["EXPLANATION_STATE_KEY", "render_explanation", "why_button"]
