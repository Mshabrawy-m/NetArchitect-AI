"""C5 coverage: bounded response cache, key ingredients, and prompt trace."""

from __future__ import annotations

import pytest

from config.limits import MAX_COPILOT_CACHE_ENTRIES, MAX_COPILOT_TRACE_ENTRIES
from services.copilot import (
    AIExplanationDraft,
    CacheKey,
    CopilotCache,
    PromptTrace,
    ScenarioInterpretation,
    build_key,
)


def _key(**changes: object) -> CacheKey:
    values = {
        "model": "fake-model",
        "prompt_id": "copilot.explain",
        "prompt_version": "1",
        "schema_name": "AIExplanationDraft",
        "payload": {"text": "hello"},
        **changes,
    }
    return build_key(**values)


def test_cache_key_hash_includes_every_required_ingredient() -> None:
    baseline = _key().value()
    assert baseline != _key(model="other-model").value()
    assert baseline != _key(prompt_version="2").value()
    assert baseline != _key(prompt_id="copilot.other").value()
    assert baseline != _key(schema_name="OtherSchema").value()
    assert baseline != _key(payload={"text": "different"}).value()
    assert _key().value() == baseline


def test_cache_is_bounded_lru_and_schema_checked() -> None:
    cache = CopilotCache(max_entries=2)
    first = AIExplanationDraft(text="one")
    second = AIExplanationDraft(text="two")
    third = AIExplanationDraft(text="three")
    key_one = _key(payload={"text": "one"})
    key_two = _key(payload={"text": "two"})
    key_three = _key(payload={"text": "three"})

    cache.put(key_one, first)
    cache.put(key_two, second)
    assert cache.get(key_one, AIExplanationDraft) == first
    cache.put(key_three, third)

    assert cache.get(key_two, AIExplanationDraft) is None  # LRU eviction
    assert cache.get(key_one, AIExplanationDraft) == first
    assert cache.get(key_three, AIExplanationDraft) == third
    assert cache.get(key_one, ScenarioInterpretation) is None  # schema mismatch
    assert cache.snapshot() == {
        "hits": 3,
        "misses": 2,
        "entries": 2,
        "max_entries": 2,
    }
    described = cache.describe()
    assert len(described) == 2
    assert all(len(row["key"]) == 12 for row in described)
    assert all(row["model"] == "AIExplanationDraft" for row in described)

    cache.clear()
    assert cache.snapshot() == {
        "hits": 0,
        "misses": 0,
        "entries": 0,
        "max_entries": 2,
    }


def test_cache_rejects_non_pydantic_values_and_invalid_bounds() -> None:
    cache = CopilotCache()
    with pytest.raises(TypeError):
        cache.put(_key(), "not a model")
    with pytest.raises(ValueError, match="at least 1"):
        CopilotCache(max_entries=0)
    assert cache.max_entries == MAX_COPILOT_CACHE_ENTRIES


def test_prompt_trace_is_bounded_and_never_stores_secrets() -> None:
    trace = PromptTrace(max_entries=2)
    for index in range(5):
        trace.add(
            prompt_id="copilot.explain",
            prompt_version=str(index),
            schema_name="AIExplanationDraft",
            model="fake-model",
            cache_hit=index > 0,
        )

    assert [row["Version"] for row in trace.rows()] == ["3", "4"]
    assert [row["Cache hit"] for row in trace.rows()] == ["yes", "yes"]
    assert trace.max_entries == 2
    assert PromptTrace().max_entries == MAX_COPILOT_TRACE_ENTRIES
    payload = str(trace.records)
    assert "gsk-" not in payload
    assert "hello" not in payload
