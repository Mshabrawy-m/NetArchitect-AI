"""Tests for the optional Groq provider layer (no real network calls)."""

from __future__ import annotations

import json
import logging
import urllib.error

import pytest
from pydantic import BaseModel

from config.limits import MAX_LLM_REPAIR_RETRIES
from core.exceptions import (
    LLMAuthenticationError,
    LLMBudgetExceededError,
    LLMMalformedResponseError,
    LLMMissingKeyError,
    LLMProviderError,
    LLMRateLimitError,
    LLMSchemaError,
    LLMTimeoutError,
)
from services.llm import (
    GroqProvider,
    HTTPResult,
    LLMMessage,
    MessageRole,
    RequestBudget,
    provider_status,
)
from services.llm.testing import FakeProvider

KEY = "gsk-test-secret-key-that-must-never-appear"


class Payload(BaseModel):
    answer: int


def _envelope(
    content: str,
    *,
    model: str = "test-model",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> bytes:
    return json.dumps(
        {
            "model": model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    ).encode("utf-8")


class ScriptedTransport:
    """Return scripted HTTP results/exceptions and record requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError("No scripted transport response left")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _provider(transport, **kwargs) -> GroqProvider:
    return GroqProvider(
        KEY,
        model="test-model",
        base_url="https://groq.example.invalid/openai/v1",
        transport=transport,
        sleep=kwargs.pop("sleep", lambda _seconds: None),
        **kwargs,
    )


def _messages() -> list[LLMMessage]:
    return [LLMMessage(role=MessageRole.user, content="hello")]


def test_success_returns_typed_response_and_usage() -> None:
    transport = ScriptedTransport([HTTPResult(200, {}, _envelope("Hello there"))])
    budget = RequestBudget(max_calls=5, max_tokens=1_000)
    provider = _provider(transport, budget=budget)

    response = provider.complete(_messages(), timeout=5)

    assert response.text == "Hello there"
    assert response.model == "test-model"
    assert response.usage.total_tokens == 15
    assert response.structured is None
    assert budget.used_calls == 1
    assert budget.used_tokens == 15
    request = transport.requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "test-model"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert "response_format" not in payload
    assert transport.timeouts == [5.0]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == f"Bearer {KEY}"
    assert headers["content-type"] == "application/json"


def test_missing_key_raises_before_any_request() -> None:
    transport = ScriptedTransport([])
    provider = GroqProvider(
        "",
        model="test-model",
        base_url="https://groq.example.invalid/openai/v1",
        transport=transport,
    )

    with pytest.raises(LLMMissingKeyError, match="API key is required"):
        provider.complete(_messages())

    assert transport.requests == []


def test_timeout_maps_to_a_typed_error() -> None:
    transport = ScriptedTransport([TimeoutError("slow")])
    provider = _provider(transport)

    with pytest.raises(LLMTimeoutError, match="timeout"):
        provider.complete(_messages())


def test_rate_limit_honors_retry_after_and_then_succeeds() -> None:
    transport = ScriptedTransport(
        [
            HTTPResult(429, {"Retry-After": "2"}, b"{}"),
            HTTPResult(200, {}, _envelope("ok")),
        ]
    )
    sleeps: list[float] = []
    budget = RequestBudget(max_calls=5, max_tokens=1_000)
    provider = _provider(transport, sleep=sleeps.append, budget=budget)

    response = provider.complete(_messages())

    assert response.text == "ok"
    assert sleeps == [2.0]
    assert budget.used_calls == 2


def test_rate_limit_retries_are_capped() -> None:
    transport = ScriptedTransport(
        [HTTPResult(429, {"Retry-After": "999"}, b"{}")] * 3
    )
    sleeps: list[float] = []
    provider = _provider(
        transport,
        sleep=sleeps.append,
        max_rate_limit_retries=2,
    )

    with pytest.raises(LLMRateLimitError, match="rate limiting"):
        provider.complete(_messages())

    assert len(transport.requests) == 3
    assert len(sleeps) == 2
    assert all(value <= 30 for value in sleeps)


def test_provider_outage_and_network_errors_are_typed() -> None:
    outage = _provider(ScriptedTransport([HTTPResult(503, {}, b"")]))
    with pytest.raises(LLMProviderError, match="unavailable"):
        outage.complete(_messages())

    network = _provider(
        ScriptedTransport(
            [urllib.error.URLError(ConnectionRefusedError("refused"))]
        )
    )
    with pytest.raises(LLMProviderError, match="could not be reached"):
        network.complete(_messages())

    auth = _provider(ScriptedTransport([HTTPResult(401, {}, b"")]))
    with pytest.raises(LLMAuthenticationError, match="rejected the API key"):
        auth.complete(_messages())


def test_malformed_response_envelopes_are_typed() -> None:
    not_json = _provider(ScriptedTransport([HTTPResult(200, {}, b"not json")]))
    with pytest.raises(LLMMalformedResponseError, match="not valid JSON"):
        not_json.complete(_messages())

    no_choices = _provider(
        ScriptedTransport([HTTPResult(200, {}, b'{"choices": []}')])
    )
    with pytest.raises(LLMMalformedResponseError, match="no choices"):
        no_choices.complete(_messages())

    no_message = _provider(
        ScriptedTransport([HTTPResult(200, {}, b'{"choices": [{}]}')])
    )
    with pytest.raises(LLMMalformedResponseError, match="no assistant message"):
        no_message.complete(_messages())


def test_schema_invalid_output_is_repaired_once() -> None:
    transport = ScriptedTransport(
        [
            HTTPResult(200, {}, _envelope('{"answer": "wrong"}')),
            HTTPResult(200, {}, _envelope('{"answer": 7}')),
        ]
    )
    provider = _provider(transport)

    response = provider.complete(_messages(), Payload)

    assert response.structured == {"answer": 7}
    assert response.attempts == 2
    assert response.repair_attempts == 1
    assert len(transport.requests) == 2
    first_payload = json.loads(transport.requests[0].data.decode("utf-8"))
    assert first_payload["response_format"] == {"type": "json_object"}
    assert first_payload["messages"][0]["role"] == "system"
    assert "Payload" in first_payload["messages"][0]["content"]
    second_payload = json.loads(transport.requests[1].data.decode("utf-8"))
    assert second_payload["messages"][-2]["content"] == '{"answer": "wrong"}'
    assert "schema validation" in second_payload["messages"][-1]["content"]


def test_schema_invalid_output_fails_after_the_repair_cap() -> None:
    transport = ScriptedTransport(
        [HTTPResult(200, {}, _envelope('{"answer": "wrong"}'))]
        * (MAX_LLM_REPAIR_RETRIES + 1)
    )
    provider = _provider(transport)

    with pytest.raises(LLMSchemaError, match="Payload"):
        provider.complete(_messages(), Payload)

    assert len(transport.requests) == MAX_LLM_REPAIR_RETRIES + 1


def test_malformed_json_content_is_repaired() -> None:
    transport = ScriptedTransport(
        [
            HTTPResult(200, {}, _envelope("not json at all")),
            HTTPResult(200, {}, _envelope('```json\n{"answer": 3}\n```')),
        ]
    )
    provider = _provider(transport)

    response = provider.complete(_messages(), Payload)

    assert response.structured == {"answer": 3}
    assert response.attempts == 2


def test_call_budget_is_enforced() -> None:
    transport = ScriptedTransport(
        [HTTPResult(200, {}, _envelope("one")), HTTPResult(200, {}, _envelope("two"))]
    )
    budget = RequestBudget(max_calls=1, max_tokens=1_000)
    provider = _provider(transport, budget=budget)

    provider.complete(_messages())
    with pytest.raises(LLMBudgetExceededError, match="call budget"):
        provider.complete(_messages())

    assert len(transport.requests) == 1


def test_token_budget_is_enforced_after_usage_is_recorded() -> None:
    transport = ScriptedTransport(
        [HTTPResult(200, {}, _envelope("one")), HTTPResult(200, {}, _envelope("two"))]
    )
    budget = RequestBudget(max_calls=5, max_tokens=15)
    provider = _provider(transport, budget=budget)

    provider.complete(_messages())
    with pytest.raises(LLMBudgetExceededError, match="token budget"):
        provider.complete(_messages())


def test_secret_never_appears_in_errors_logs_or_status(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    outcomes = [
        HTTPResult(401, {}, b""),
        HTTPResult(503, {}, b""),
        HTTPResult(200, {}, b"not json"),
    ]
    for outcome in outcomes:
        provider = _provider(ScriptedTransport([outcome]))
        with pytest.raises(Exception) as error:
            provider.complete(_messages())
        assert KEY not in str(error.value)
        assert KEY not in repr(error.value)

    provider = _provider(
        ScriptedTransport([HTTPResult(200, {}, _envelope('{"answer": "bad"}'))] * 3)
    )
    with pytest.raises(LLMSchemaError) as schema_error:
        provider.complete(_messages(), Payload)
    assert KEY not in str(schema_error.value)

    status = provider_status(provider, key_configured=True)
    assert KEY not in json.dumps(status)
    assert KEY not in caplog.text


def test_per_request_timeout_is_bounded() -> None:
    transport = ScriptedTransport([HTTPResult(200, {}, _envelope("ok"))])
    provider = _provider(transport)

    provider.complete(_messages(), timeout=10_000)

    assert transport.timeouts == [30.0]


def test_fake_provider_scripts_success_errors_and_exhaustion() -> None:
    provider = FakeProvider(
        [
            '{"answer": 1}',
            LLMTimeoutError("scripted timeout"),
        ]
    )
    first = provider.complete(_messages(), Payload)
    assert first.structured == {"answer": 1}
    with pytest.raises(LLMTimeoutError, match="scripted timeout"):
        provider.complete(_messages(), Payload)
    with pytest.raises(LLMProviderError, match="no replies left"):
        provider.complete(_messages())
    assert provider.calls[0].schema == "Payload"
