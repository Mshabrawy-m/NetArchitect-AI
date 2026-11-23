"""Bounded per-session LLM request and token budget."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Literal

from config.limits import MAX_LLM_CALLS_PER_SESSION, MAX_LLM_TOKENS_PER_SESSION
from core.exceptions import LLMBudgetExceededError

from .models import LLMUsage, ProviderLimits

Clock = Callable[[], float]
UsageSource = Literal["reported", "estimated", "none"]


def _accumulate(current: LLMUsage, added: LLMUsage) -> LLMUsage:
    """Return a frozen usage total with the current source label."""
    return LLMUsage(
        prompt_tokens=current.prompt_tokens + added.prompt_tokens,
        completion_tokens=current.completion_tokens + added.completion_tokens,
        total_tokens=current.total_tokens + added.total_tokens,
        source=current.source,
    )


class RequestBudget:
    """Mutable per-session counter for LLM calls and tokens.

    Call :meth:`begin_call` immediately before every HTTP request (including
    rate-limit retries and schema repairs) and :meth:`record` with the usage
    reported by the provider. The budget is intentionally conservative: a call
    is counted even when it fails.
    """

    def __init__(
        self,
        *,
        max_calls: int = MAX_LLM_CALLS_PER_SESSION,
        max_tokens: int = MAX_LLM_TOKENS_PER_SESSION,
        clock: Clock = time.time,
    ) -> None:
        if max_calls < 1:
            raise ValueError(f"max_calls must be at least 1, got {max_calls}")
        if max_tokens < 1:
            raise ValueError(f"max_tokens must be at least 1, got {max_tokens}")
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.used_calls = 0
        self.used_tokens = 0
        self._clock = clock
        self.real_usage = LLMUsage()
        self.estimated_usage = LLMUsage(source="estimated")
        self.last_usage_source: UsageSource = "none"
        self.last_limits = ProviderLimits()
        self.last_call_at: float | None = None
        self.responses_observed = 0

    @property
    def remaining_calls(self) -> int:
        """Return the number of calls still allowed."""
        return max(0, self.max_calls - self.used_calls)

    @property
    def remaining_tokens(self) -> int:
        """Return the number of tokens still allowed."""
        return max(0, self.max_tokens - self.used_tokens)

    def ensure_available(self) -> None:
        """Raise a typed error when no further request may be made."""
        if self.used_calls >= self.max_calls:
            raise LLMBudgetExceededError(
                "LLM call budget exhausted: "
                f"{self.used_calls}/{self.max_calls} request(s) used this session."
            )
        if self.used_tokens >= self.max_tokens:
            raise LLMBudgetExceededError(
                "LLM token budget exhausted: "
                f"{self.used_tokens}/{self.max_tokens} token(s) used this session."
            )

    def begin_call(self) -> None:
        """Reserve one request against the call budget."""
        self.ensure_available()
        self.used_calls += 1

    def observe_response(
        self,
        headers: Mapping[str, str] | object,
        *,
        timestamp: float | None = None,
    ) -> ProviderLimits:
        """Capture the last response's header snapshot and response time."""
        self.last_limits = ProviderLimits.from_headers(headers)
        if timestamp is None:
            timestamp = self._clock()
        try:
            moment = float(timestamp)
        except (TypeError, ValueError):
            moment = self._clock()
        self.last_call_at = moment
        self.responses_observed += 1
        return self.last_limits

    def record(self, usage: LLMUsage) -> None:
        """Add real or clearly estimated tokens to the session total."""
        self.used_tokens = min(
            self.max_tokens,
            self.used_tokens + max(0, usage.total_tokens),
        )
        if usage.source == "estimated":
            self.estimated_usage = _accumulate(self.estimated_usage, usage)
        else:
            self.real_usage = _accumulate(self.real_usage, usage)
        self.last_usage_source = usage.source

    def reset(self) -> None:
        """Clear all counters and the last-response snapshot."""
        self.used_calls = 0
        self.used_tokens = 0
        self.real_usage = LLMUsage()
        self.estimated_usage = LLMUsage(source="estimated")
        self.last_usage_source = "none"
        self.last_limits = ProviderLimits()
        self.last_call_at = None
        self.responses_observed = 0

    def snapshot(self) -> dict[str, object]:
        """Return a serializable, secret-free budget and telemetry summary."""
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "used_calls": self.used_calls,
            "used_tokens": self.used_tokens,
            "remaining_calls": self.remaining_calls,
            "remaining_tokens": self.remaining_tokens,
            "real_tokens": self.real_usage.total_tokens,
            "real_prompt_tokens": self.real_usage.prompt_tokens,
            "real_completion_tokens": self.real_usage.completion_tokens,
            "estimated_tokens": self.estimated_usage.total_tokens,
            "last_usage_source": self.last_usage_source,
            "responses_observed": self.responses_observed,
            "last_call_at": self.last_call_at,
            "provider_limits": self.last_limits.model_dump(),
        }


__all__ = ["RequestBudget"]
