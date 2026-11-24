"""Tests for the optional Groq provider layer (no real network calls)."""

from __future__ import annotations

import json
import logging
import urllib.error

import pytest
from pydantic import BaseModel

from config.limits import MAX_LLM_REPAIR_RETRIES
from config.settings import get_settings
from core.exceptions import (
    LLMAuthenticationError,
    LLMBudgetExceededError,
    LLMForbiddenError,
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
    ProviderLimits,
    RequestBudget,
    provider_status,
)
from services.llm.testing import FakeProvider

KEY = "gsk-test-secret-key-that-must-never-appear"
EXPECTED_USER_AGENT = (
    "NetArchitect-AI/2.0 (+https://github.com/Mshabrawy-m/NetArchitect-AI)"
)
AUTH_MESSAGE = (
    "The LLM provider rejected the API key (HTTP 401). Check the configured key."
)
FORBIDDEN_MESSAGE = (
    "The LLM provider blocked the request (HTTP 403). "
    "Check the configured key or provider permissions."
)
FIXED_NOW = 1_700_000_123.0
FULL_LIMIT_HEADERS = {
    "x-ratelimit-limit-requests": "100",
    "x-ratelimit-limit-tokens": "10000",
    "x-ratelimit-remaining-requests": "42",
    "x-ratelimit-remaining-tokens": "7000",
    "x-ratelimit-reset-requests": "1800",
    "x-ratelimit-reset-tokens": "3600",
    "retry-after": "2",
}


class Payload(BaseModel):
    answer: int


def _envelope(
    content: str,
    *,
    model: str = "test-model",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    include_usage: bool = True,
) -> bytes:
    payload: dict[str, object] = {
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if include_usage:
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return json.dumps(payload).encode("utf-8")


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
        clock=kwargs.pop("clock", lambda: 1_700_000_000.0),
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
    assert headers["user-agent"] == EXPECTED_USER_AGENT


def test_all_rate_limit_headers_and_reported_usage_are_captured() -> None:
    transport = ScriptedTransport(
        [HTTPResult(200, FULL_LIMIT_HEADERS, _envelope("Hello"))]
    )
    budget = RequestBudget(max_calls=5, max_tokens=1_000)
    provider = _provider(transport, budget=budget, clock=lambda: FIXED_NOW)

    response = provider.complete(_messages())

    assert response.usage.source == "reported"
    assert response.usage.total_tokens == 15
    snapshot = budget.snapshot()
    assert snapshot["used_calls"] == 1
    assert snapshot["responses_observed"] == 1
    assert snapshot["real_tokens"] == 15
    assert snapshot["estimated_tokens"] == 0
    assert snapshot["last_usage_source"] == "reported"
    assert snapshot["last_call_at"] == FIXED_NOW
    assert snapshot["provider_limits"] == ProviderLimits(
        limit_requests=100,
        limit_tokens=10_000,
        remaining_requests=42,
        remaining_tokens=7_000,
        reset_requests=1_800.0,
        reset_tokens=3_600.0,
        retry_after=2.0,
    ).model_dump()


def test_partial_and_malformed_headers_are_never_guessed() -> None:
    headers = {
        "X-RateLimit-Remaining-Requests": "7",
        "x-ratelimit-reset_tokens": "900",
        "x-ratelimit-remaining-tokens": "oops",
        "x-ratelimit-reset-requests": "",
        "Retry-After": "-1",
        "Authorization": "Bearer should-not-be-captured",
    }
    parsed = ProviderLimits.from_headers(headers)

    assert parsed.remaining_requests == 7
    assert parsed.reset_tokens == 900.0
    assert parsed.remaining_tokens is None
    assert parsed.reset_requests is None
    assert parsed.retry_after is None
    assert parsed.limit_requests is None
    assert parsed.limit_tokens is None
    assert "should-not-be-captured" not in json.dumps(parsed.model_dump())


def test_missing_and_malformed_usage_falls_back_to_labeled_estimate() -> None:
    missing = ScriptedTransport(
        [HTTPResult(200, {}, _envelope("Hi", include_usage=False))]
    )
    malformed_body = _envelope("Hi", include_usage=False).replace(
        b'"choices"',
        b'"usage": {"total_tokens": "oops"}, "choices"',
        1,
    )
    malformed = ScriptedTransport([HTTPResult(200, {}, malformed_body)])
    for transport in (missing, malformed):
        budget = RequestBudget(max_calls=5, max_tokens=1_000)
        provider = _provider(transport, budget=budget)

        response = provider.complete(_messages())

        assert response.usage.source == "estimated"
        assert response.usage.total_tokens == 3
        assert response.usage.prompt_tokens == 2
        assert response.usage.completion_tokens == 1
        snapshot = budget.snapshot()
        assert snapshot["real_tokens"] == 0
        assert snapshot["estimated_tokens"] == 3
        assert snapshot["last_usage_source"] == "estimated"
        assert snapshot["used_tokens"] == 3
        assert snapshot["provider_limits"] == ProviderLimits().model_dump()


def test_every_http_response_refreshes_the_last_snapshot() -> None:
    transport = ScriptedTransport(
        [
            HTTPResult(429, {"x-ratelimit-remaining-requests": "1"}, b"{}"),
            HTTPResult(200, {"x-ratelimit-remaining-requests": "9"}, _envelope("ok")),
        ]
    )
    budget = RequestBudget(max_calls=5, max_tokens=1_000)
    provider = _provider(
        transport,
        budget=budget,
        clock=lambda: FIXED_NOW,
        max_rate_limit_retries=1,
    )

    provider.complete(_messages())

    snapshot = budget.snapshot()
    assert snapshot["used_calls"] == 2
    assert snapshot["responses_observed"] == 2
    assert snapshot["last_call_at"] == FIXED_NOW
    assert snapshot["provider_limits"]["remaining_requests"] == 9


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
    assert all(
        {key.lower(): value for key, value in request.header_items()}["user-agent"]
        == EXPECTED_USER_AGENT
        for request in transport.requests
    )


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


def test_401_and_403_are_distinct_typed_errors_with_status_and_no_secret(
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    captured: list[Exception] = []
    outcomes = (
        (401, LLMAuthenticationError, AUTH_MESSAGE),
        (403, LLMForbiddenError, FORBIDDEN_MESSAGE),
    )
    for status, expected_type, expected_message in outcomes:
        transport = ScriptedTransport(
            [HTTPResult(status, {}, json.dumps({"error": KEY}).encode("utf-8"))]
        )
        provider = _provider(transport)

        with pytest.raises(expected_type) as caught:
            provider.complete(_messages())

        error = caught.value
        captured.append(error)
        assert str(error) == expected_message
        assert f"HTTP {status}" in str(error)
        assert KEY not in str(error)
        assert KEY not in repr(error)
        assert '"error"' not in str(error)
        assert '"messages"' not in str(error)
        headers = {
            key.lower(): value for key, value in transport.requests[0].header_items()
        }
        assert headers["user-agent"] == EXPECTED_USER_AGENT

    assert type(captured[0]) is not type(captured[1])
    assert str(captured[0]) != str(captured[1])
    assert KEY not in caplog.text


def test_fake_provider_scripts_distinct_authentication_errors() -> None:
    provider = FakeProvider(
        [
            LLMAuthenticationError(AUTH_MESSAGE),
            LLMForbiddenError(FORBIDDEN_MESSAGE),
        ]
    )

    with pytest.raises(LLMAuthenticationError, match=r"HTTP 401") as auth:
        provider.complete(_messages())
    with pytest.raises(LLMForbiddenError, match=r"HTTP 403") as forbidden:
        provider.complete(_messages())

    assert str(auth.value) == AUTH_MESSAGE
    assert str(forbidden.value) == FORBIDDEN_MESSAGE
    assert type(auth.value) is not type(forbidden.value)
    assert KEY not in str(auth.value)
    assert KEY not in str(forbidden.value)


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
        HTTPResult(403, {}, b""),
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


def test_configured_key_never_appears_in_telemetry(monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    get_settings.cache_clear()
    try:
        budget = RequestBudget(max_calls=5, max_tokens=1_000)
        provider = _provider(
            ScriptedTransport([HTTPResult(200, FULL_LIMIT_HEADERS, _envelope("ok"))]),
            budget=budget,
        )
        provider.complete(_messages())
        status = provider_status(
            provider,
            key_configured=True,
            key_source=get_settings().GROQ_KEY_SOURCE,
        )
        dump = json.dumps(
            {
                "key_source": get_settings().GROQ_KEY_SOURCE,
                "budget": budget.snapshot(),
                "status": status,
            }
        )
        assert get_settings().GROQ_KEY_SOURCE == "environment"
        assert KEY not in dump
        assert KEY not in caplog.text
    finally:
        get_settings.cache_clear()


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
