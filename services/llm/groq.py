"""Groq provider using the OpenAI-compatible HTTP API.

The implementation uses only the standard library. Tests inject a transport
callable, so no test performs a real network request. Credentials are held in
memory for the request header only; they are never logged, traced, serialized,
or placed in an error message.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from config.limits import (
    LLM_RETRY_BASE_SECONDS,
    MAX_LLM_RATE_LIMIT_RETRIES,
    MAX_LLM_REPAIR_RETRIES,
    MAX_LLM_RESPONSE_TOKENS,
    MAX_LLM_RETRY_AFTER_SECONDS,
    MAX_LLM_TIMEOUT_SECONDS,
)
from config.settings import get_settings
from core.exceptions import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMMissingKeyError,
    LLMProviderError,
    LLMRateLimitError,
    LLMSchemaError,
    LLMTimeoutError,
)

from .budget import RequestBudget
from .models import LLMMessage, LLMResponse, LLMUsage, MessageRole
from .provider import LLMProvider
from .structured import (
    repair_instruction,
    schema_instruction,
    validate_structured,
)

Transport = Callable[[urllib.request.Request, float], "HTTPResult"]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class HTTPResult:
    """One transport-level HTTP response, including non-2xx statuses."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


def default_transport(request: urllib.request.Request, timeout: float) -> HTTPResult:
    """Perform one HTTP request with :mod:`urllib` (the deployment path)."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HTTPResult(
                status_code=int(response.status),
                headers=dict(response.headers),
                body=response.read(),
            )
    except urllib.error.HTTPError as error:
        return HTTPResult(
            status_code=int(error.code),
            headers=dict(error.headers or {}),
            body=error.read(),
        )


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """Return a bounded ``Retry-After`` value when the header is numeric."""
    value = next(
        (
            header_value
            for key, header_value in headers.items()
            if key.lower() == "retry-after"
        ),
        None,
    )
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, float(MAX_LLM_RETRY_AFTER_SECONDS))


class GroqProvider(LLMProvider):
    """Groq chat-completions provider with typed errors and bounded retries."""

    name = "groq"

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        budget: RequestBudget | None = None,
        transport: Transport | None = None,
        sleep: Sleep = time.sleep,
        max_rate_limit_retries: int = MAX_LLM_RATE_LIMIT_RETRIES,
        max_repair_retries: int = MAX_LLM_REPAIR_RETRIES,
        max_response_tokens: int = MAX_LLM_RESPONSE_TOKENS,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key.strip()
        self.model = (model or settings.GROQ_MODEL).strip()
        self.base_url = (base_url or settings.GROQ_BASE_URL).strip().rstrip("/")
        if not self.model:
            raise LLMProviderError("No Groq model is configured.")
        if not self.base_url:
            raise LLMProviderError("No Groq base URL is configured.")
        if max_rate_limit_retries < 0:
            raise ValueError("max_rate_limit_retries must be non-negative")
        if max_repair_retries < 0:
            raise ValueError("max_repair_retries must be non-negative")
        self.timeout = self._resolve_timeout(timeout)
        self.budget = budget
        self._transport = transport or default_transport
        self._sleep = sleep
        self.max_rate_limit_retries = max_rate_limit_retries
        self.max_repair_retries = max_repair_retries
        self.max_response_tokens = max_response_tokens

    @classmethod
    def from_settings(
        cls,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> GroqProvider:
        """Build a provider from settings or an explicit session key."""
        settings = get_settings()
        return cls(
            settings.GROQ_API_KEY if api_key is None else api_key,
            model=settings.GROQ_MODEL,
            base_url=settings.GROQ_BASE_URL,
            **kwargs,
        )

    @staticmethod
    def _resolve_timeout(timeout: float | None) -> float:
        value = 30.0 if timeout is None else float(timeout)
        if value <= 0:
            raise ValueError("timeout must be positive")
        return min(value, float(MAX_LLM_TIMEOUT_SECONDS))

    def complete(
        self,
        messages: Sequence[LLMMessage],
        schema: type[BaseModel] | None = None,
        *,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Return one response, validating structured output when requested."""
        if not self._api_key:
            raise LLMMissingKeyError(
                "A Groq API key is required for AI features. Core deterministic "
                "engineering works without one."
            )
        conversation = [
            message
            if isinstance(message, LLMMessage)
            else LLMMessage.model_validate(message)
            for message in messages
        ]
        if not conversation:
            raise LLMProviderError("At least one message is required.")
        if schema is not None:
            if not isinstance(schema, type) or not issubclass(schema, BaseModel):
                raise LLMProviderError("schema must be a Pydantic BaseModel type.")
            conversation = [
                LLMMessage(
                    role=MessageRole.system,
                    content=schema_instruction(schema),
                ),
                *conversation,
            ]

        request_timeout = self._resolve_timeout(timeout)
        for attempt in range(self.max_repair_retries + 1):
            response = self._chat(conversation, schema, request_timeout)
            if schema is None:
                return response.model_copy(update={"attempts": attempt + 1})
            try:
                parsed = validate_structured(response.text, schema)
            except LLMSchemaError as error:
                if attempt >= self.max_repair_retries:
                    raise LLMSchemaError(
                        f"Structured output failed after {attempt + 1} attempt(s): "
                        f"{error}"
                    ) from error
                conversation = [
                    *conversation,
                    LLMMessage(
                        role=MessageRole.assistant,
                        content=response.text,
                    ),
                    LLMMessage(
                        role=MessageRole.user,
                        content=repair_instruction(schema, str(error)),
                    ),
                ]
                continue
            return response.model_copy(
                update={
                    "structured": parsed.model_dump(mode="json"),
                    "attempts": attempt + 1,
                    "repair_attempts": attempt,
                }
            )
        raise LLMSchemaError("Structured output could not be validated.")

    def _chat(
        self,
        conversation: Sequence[LLMMessage],
        schema: type[BaseModel] | None,
        timeout: float,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in conversation
            ],
            "temperature": 0.0,
            "max_tokens": self._max_tokens(),
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        result = self._post_with_rate_limit(payload, timeout)
        return self._parse_envelope(result.body)

    def _max_tokens(self) -> int:
        if self.budget is None:
            return self.max_response_tokens
        return max(1, min(self.max_response_tokens, self.budget.remaining_tokens))

    def _post_with_rate_limit(
        self,
        payload: dict[str, Any],
        timeout: float,
    ) -> HTTPResult:
        for attempt in range(self.max_rate_limit_retries + 1):
            result = self._post(payload, timeout)
            if result.status_code != 429:
                return result
            if attempt >= self.max_rate_limit_retries:
                raise LLMRateLimitError(
                    "The LLM provider is rate limiting requests after "
                    f"{attempt + 1} attempt(s). Try again later."
                )
            self._sleep(self._backoff_seconds(result.headers, attempt))
        raise LLMRateLimitError("The LLM provider is rate limiting requests.")

    def _backoff_seconds(self, headers: Mapping[str, str], attempt: int) -> float:
        retry_after = _retry_after_seconds(headers)
        if retry_after is not None:
            return retry_after
        return min(
            LLM_RETRY_BASE_SECONDS * (2**attempt),
            float(MAX_LLM_RETRY_AFTER_SECONDS),
        )

    def _post(self, payload: dict[str, Any], timeout: float) -> HTTPResult:
        if self.budget is not None:
            self.budget.begin_call()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            result = self._transport(request, timeout)
        except TimeoutError as error:
            raise LLMTimeoutError(
                "The LLM provider did not respond before the timeout."
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise LLMTimeoutError(
                    "The LLM provider did not respond before the timeout."
                ) from error
            raise LLMProviderError(
                "The LLM provider could not be reached."
            ) from error
        except OSError as error:
            raise LLMProviderError(
                "The LLM provider could not be reached."
            ) from error

        if result.status_code in {401, 403}:
            raise LLMAuthenticationError(
                "The LLM provider rejected the API key. Check the configured key."
            )
        if result.status_code == 429:
            return result
        if result.status_code >= 500:
            raise LLMProviderError(
                f"The LLM provider is unavailable (HTTP {result.status_code})."
            )
        if result.status_code >= 400:
            raise LLMProviderError(
                f"The LLM request was rejected (HTTP {result.status_code})."
            )
        return result

    def _parse_envelope(self, body: bytes) -> LLMResponse:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LLMMalformedResponseError(
                "The LLM provider returned a response that is not valid JSON."
            ) from error
        if not isinstance(payload, dict):
            raise LLMMalformedResponseError(
                "The LLM provider returned an unexpected response shape."
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMMalformedResponseError(
                "The LLM provider response contained no choices."
            )
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise LLMMalformedResponseError(
                "The LLM provider response contained no assistant message."
            )
        usage_payload = payload.get("usage")
        usage = (
            LLMUsage.model_validate(usage_payload)
            if isinstance(usage_payload, dict)
            else LLMUsage()
        )
        if self.budget is not None:
            self.budget.record(usage)
        model = payload.get("model")
        return LLMResponse(
            text=content,
            model=model if isinstance(model, str) and model else self.model,
            usage=usage,
            finish_reason=(
                first.get("finish_reason")
                if isinstance(first.get("finish_reason"), str)
                else ""
            ),
        )


def provider_status(
    provider: GroqProvider,
    *,
    key_configured: bool,
    key_source: str = "none",
) -> dict[str, object]:
    """Return a non-secret provider summary for presentation layers."""
    return {
        "provider": provider.name,
        "model": provider.model,
        "base_url": provider.base_url,
        "key_configured": key_configured,
        "key_source": key_source,
    }


__all__ = ["GroqProvider", "HTTPResult", "default_transport", "provider_status"]
