"""Tests for exact JSON round-trip and schema-version handling."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.exceptions import LimitsExceededError, SchemaError, TwinSchemaVersionError
from digital_twin import from_json, to_json

from .helpers import make_twin


def test_json_round_trip_is_exact() -> None:
    twin = make_twin()

    restored = from_json(to_json(twin))

    assert restored == twin
    assert to_json(restored) == to_json(twin)


def test_to_json_is_pretty_printed_by_default() -> None:
    payload = to_json(make_twin())

    assert payload.startswith("{")
    assert "\n" in payload
    assert json.loads(payload)["metadata"]["schema_version"] == 1


def test_to_json_can_be_compact() -> None:
    payload = to_json(make_twin(), indent=None)

    assert "\n" not in payload


def test_from_json_rejects_newer_schema_version() -> None:
    data = json.loads(to_json(make_twin()))
    data["metadata"]["schema_version"] = 2

    with pytest.raises(TwinSchemaVersionError, match="version 2 is not supported"):
        from_json(json.dumps(data))


def test_from_json_rejects_missing_schema_version() -> None:
    data = json.loads(to_json(make_twin()))
    del data["metadata"]["schema_version"]

    with pytest.raises(TwinSchemaVersionError, match="must be an integer"):
        from_json(json.dumps(data))


def test_from_json_rejects_missing_metadata() -> None:
    data = json.loads(to_json(make_twin()))
    del data["metadata"]

    with pytest.raises(TwinSchemaVersionError, match="missing the metadata"):
        from_json(json.dumps(data))


def test_from_json_rejects_malformed_payload() -> None:
    with pytest.raises(SchemaError, match="not valid JSON"):
        from_json("{not json")

    with pytest.raises(SchemaError, match="must be an object"):
        from_json("[]")


def test_from_json_rejects_unknown_fields() -> None:
    data = json.loads(to_json(make_twin()))
    data["unexpected"] = True

    with pytest.raises(ValidationError):
        from_json(json.dumps(data))


def test_to_json_enforces_demand_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("digital_twin.serialization.MAX_DEMANDS", 0)

    with pytest.raises(LimitsExceededError, match="limit is 0"):
        to_json(make_twin())
