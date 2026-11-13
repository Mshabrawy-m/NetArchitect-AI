"""Bounded per-session LLM request and token budget."""

from __future__ import annotations

from config.limits import MAX_LLM_CALLS_PER_SESSION, MAX_LLM_TOKENS_PER_SESSION
from core.exceptions import LLMBudgetExceededError

from .models import LLMUsage


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
    ) -> None:
        if max_calls < 1:
            raise ValueError(f"max_calls must be at least 1, got {max_calls}")
        if max_tokens < 1:
            raise ValueError(f"max_tokens must be at least 1, got {max_tokens}")
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.used_calls = 0
        self.used_tokens = 0

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

    def record(self, usage: LLMUsage) -> None:
        """Add provider-reported token usage to the session total."""
        self.used_tokens = min(
            self.max_tokens,
            self.used_tokens + max(0, usage.total_tokens),
        )

    def reset(self) -> None:
        """Clear both counters."""
        self.used_calls = 0
        self.used_tokens = 0

    def snapshot(self) -> dict[str, int]:
        """Return a serializable, secret-free budget summary."""
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "used_calls": self.used_calls,
            "used_tokens": self.used_tokens,
            "remaining_calls": self.remaining_calls,
            "remaining_tokens": self.remaining_tokens,
        }


__all__ = ["RequestBudget"]
