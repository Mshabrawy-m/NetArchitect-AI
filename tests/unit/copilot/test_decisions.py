"""C4 coverage: bounded, timestamped, deterministic design decisions."""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from config.limits import MAX_COPILOT_DECISIONS
from services.copilot import DecisionKind, DecisionLog, DecisionRecord
from services.llm.testing import FakeProvider


def _add(log: DecisionLog, index: int) -> DecisionRecord:
    return log.add(
        kind=DecisionKind.suggestion_accepted,
        subject_id=f"suggestion:{index}",
        title=f"Applied suggestion {index}",
        page="Optimization Center",
        source_fingerprint="a" * 64,
        result_fingerprint="b" * 64,
        details=(("metric", "served_demand_ratio"),),
    )


def test_decision_record_is_frozen_and_timestamped() -> None:
    log = DecisionLog()
    record = _add(log, 1)
    assert record.created_at.tzinfo is UTC
    assert record.kind is DecisionKind.suggestion_accepted
    assert record.details == (("metric", "served_demand_ratio"),)
    with pytest.raises(ValidationError):
        record.title = "changed"
    with pytest.raises(ValidationError):
        DecisionRecord(
            kind=DecisionKind.snapshot_saved,
            subject_id="x",
            title="x",
            page="x",
            api_key="secret",
        )


def test_log_is_bounded() -> None:
    log = DecisionLog(max_entries=2)
    for index in range(5):
        _add(log, index)
    assert [item.subject_id for item in log.records] == [
        "suggestion:3",
        "suggestion:4",
    ]
    assert len(log.rows()) == 2
    assert log.max_entries == 2
    assert DecisionLog().max_entries == MAX_COPILOT_DECISIONS

    with pytest.raises(ValueError, match="at least 1"):
        DecisionLog(max_entries=0)


def test_canonical_json_round_trip_keeps_provenance() -> None:
    log = DecisionLog()
    record = _add(log, 1)
    payload = log.to_json()
    assert "api_key" not in payload
    assert record.kind.value in payload

    restored = DecisionLog.from_json(payload)
    assert restored.records == log.records
    assert restored.to_json() == payload
    assert DecisionLog.from_json("").records == ()


def test_from_json_rejects_a_non_list_payload() -> None:
    with pytest.raises(TypeError):
        DecisionLog.from_json('{"kind": "suggestion_accepted"}')


def test_decision_logging_never_calls_an_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.llm import LLMProvider

    def _must_not_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("decision logging called an LLM provider")

    monkeypatch.setattr(LLMProvider, "complete", _must_not_call)
    provider = FakeProvider(["unused"])
    assert provider.calls == []
    log = DecisionLog()
    assert _add(log, 1).subject_id == "suggestion:1"
