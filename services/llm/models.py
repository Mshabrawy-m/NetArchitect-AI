"""Typed request/response models for the optional LLM provider layer.

The models carry no credentials. A provider must never put an API key into a
message, response, error, or trace.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    """Token accounting reported by the provider (zero when omitted)."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


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
    key_source: Literal["session", "environment", "secrets", "none"] = "none"


__all__ = [
    "LLMMessage",
    "LLMResponse",
    "LLMUsage",
    "MessageRole",
    "ProviderStatus",
]
