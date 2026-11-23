"""Typed request/response models for the optional LLM provider layer.

The models carry no credentials. A provider must never put an API key into a
message, response, error, or trace.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_MAX_REPORTED_VALUE = 1_000_000_000
_MAX_HEADER_LENGTH = 64


def _nonnegative_int(value: object) -> int | None:
    """Parse a bounded non-negative integer without raising."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number < 0 or number > _MAX_REPORTED_VALUE:
        return None
    return number


def _nonnegative_float(value: object) -> float | None:
    """Parse a bounded, finite non-negative number without raising."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > _MAX_REPORTED_VALUE:
        return None
    return number


class MessageRole(str, Enum):
    """OpenAI-compatible chat roles supported by the provider layer."""

    system = "system"
    user = "user"
    assistant = "assistant"


class LLMMessage(BaseModel):
    """One chat message sent to or returned by a provider."""

    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str = Field(description="Message text; never contains credentials.")


class LLMUsage(BaseModel):
    """Token accounting with an explicit reported/estimated provenance label."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    source: Literal["reported", "estimated"] = "reported"

    @classmethod
    def from_payload(cls, payload: object) -> LLMUsage | None:
        """Parse a provider ``usage`` object; return ``None`` if unusable."""
        if not isinstance(payload, Mapping):
            return None
        prompt = _nonnegative_int(payload.get("prompt_tokens"))
        completion = _nonnegative_int(payload.get("completion_tokens"))
        total = _nonnegative_int(payload.get("total_tokens"))
        if prompt is None and completion is None and total is None:
            return None
        if total is None:
            total = (prompt or 0) + (completion or 0)
        return cls(
            prompt_tokens=prompt or 0,
            completion_tokens=completion or 0,
            total_tokens=min(total, _MAX_REPORTED_VALUE),
            source="reported",
        )

    @classmethod
    def estimate(cls, prompt_chars: int, completion_chars: int) -> LLMUsage:
        """Return a clearly labeled ~4-characters-per-token local estimate."""
        prompt = (
            max(1, (max(0, prompt_chars) + 3) // 4) if prompt_chars > 0 else 0
        )
        completion = (
            max(1, (max(0, completion_chars) + 3) // 4)
            if completion_chars > 0
            else 0
        )
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            source="estimated",
        )


class ProviderLimits(BaseModel):
    """Defensive, secret-free snapshot of provider rate-limit headers."""

    model_config = ConfigDict(frozen=True)

    limit_requests: int | None = None
    limit_tokens: int | None = None
    remaining_requests: int | None = None
    remaining_tokens: int | None = None
    reset_requests: float | None = None
    reset_tokens: float | None = None
    retry_after: float | None = None

    @classmethod
    def from_headers(cls, headers: object) -> ProviderLimits:
        """Parse known headers case-insensitively; ignore everything else."""
        if not isinstance(headers, Mapping):
            return cls()

        normalized: dict[str, str] = {}
        for raw_name, raw_value in headers.items():
            if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                continue
            name = raw_name.strip().lower().replace("_", "-")
            value = raw_value.strip()
            if name not in normalized and 0 < len(value) <= _MAX_HEADER_LENGTH:
                normalized[name] = value

        aliases: dict[str, tuple[str, ...]] = {
            "limit_requests": (
                "x-ratelimit-limit-requests",
                "ratelimit-limit-requests",
                "x-ratelimit-requests-limit",
            ),
            "limit_tokens": (
                "x-ratelimit-limit-tokens",
                "ratelimit-limit-tokens",
                "x-ratelimit-tokens-limit",
            ),
            "remaining_requests": (
                "x-ratelimit-remaining-requests",
                "ratelimit-remaining-requests",
            ),
            "remaining_tokens": (
                "x-ratelimit-remaining-tokens",
                "ratelimit-remaining-tokens",
            ),
            "reset_requests": (
                "x-ratelimit-reset-requests",
                "ratelimit-reset-requests",
            ),
            "reset_tokens": (
                "x-ratelimit-reset-tokens",
                "ratelimit-reset-tokens",
            ),
            "retry_after": ("retry-after", "x-ratelimit-retry-after"),
        }

        def first(names: tuple[str, ...]) -> str | None:
            return next((normalized[name] for name in names if name in normalized), None)

        value = first(aliases["limit_requests"])
        limit_requests = _nonnegative_int(value) if value is not None else None
        value = first(aliases["limit_tokens"])
        limit_tokens = _nonnegative_int(value) if value is not None else None
        value = first(aliases["remaining_requests"])
        remaining_requests = _nonnegative_int(value) if value is not None else None
        value = first(aliases["remaining_tokens"])
        remaining_tokens = _nonnegative_int(value) if value is not None else None
        value = first(aliases["reset_requests"])
        reset_requests = _nonnegative_float(value) if value is not None else None
        value = first(aliases["reset_tokens"])
        reset_tokens = _nonnegative_float(value) if value is not None else None
        value = first(aliases["retry_after"])
        retry_after = _nonnegative_float(value) if value is not None else None

        return cls(
            limit_requests=limit_requests,
            limit_tokens=limit_tokens,
            remaining_requests=remaining_requests,
            remaining_tokens=remaining_tokens,
            reset_requests=reset_requests,
            reset_tokens=reset_tokens,
            retry_after=retry_after,
        )


class LLMResponse(BaseModel):
    """A typed provider response.

    ``structured`` is present only when the caller supplied a schema. It holds
    the *validated* model dump, so callers never consume unvalidated JSON.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(description="Raw assistant text.")
    model: str = Field(description="Model name reported by the provider.")
    usage: LLMUsage = Field(default_factory=LLMUsage)
    structured: dict[str, Any] | None = Field(
        default=None,
        description="Validated structured payload when a schema was supplied.",
    )
    finish_reason: str = Field(default="")
    attempts: int = Field(default=1, ge=1)
    repair_attempts: int = Field(default=0, ge=0)


class ProviderStatus(BaseModel):
    """Non-secret provider status for the Settings page."""

    model_config = ConfigDict(frozen=True)

    provider: str = "groq"
    model: str
    base_url: str
    key_configured: bool
    key_source: Literal["environment", "secrets", "none"] = "none"


__all__ = [
    "LLMMessage",
    "LLMResponse",
    "LLMUsage",
    "MessageRole",
    "ProviderLimits",
    "ProviderStatus",
]
