"""Tests for exact JSON round-trip and schema-version handling."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.exceptions import LimitsExceededError, SchemaError, TwinSchemaVersionError
from digital_twin import (
    TWIN_SCHEMA_VERSION,
    from_json,
    to_json,
)
from security import derive_default_security_model, set_security_model
from simulation import twin_fingerprint

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
    assert json.loads(payload)["metadata"]["schema_version"] == TWIN_SCHEMA_VERSION


def test_to_json_can_be_compact() -> None:
    payload = to_json(make_twin(), indent=None)

    assert "\n" not in payload


def test_from_json_rejects_newer_schema_version() -> None:
    data = json.loads(to_json(make_twin()))
    data["metadata"]["schema_version"] = TWIN_SCHEMA_VERSION + 1

    with pytest.raises(TwinSchemaVersionError, match="version 3 is not supported"):
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


def test_legacy_twin_json_loads_with_none_security_and_unchanged_fingerprint() -> None:
    twin = make_twin()
    metadata = twin.metadata.model_copy(update={"schema_version": 1})
    legacy = twin.model_copy(update={"metadata": metadata})
    payload = to_json(legacy)

    assert "security" not in json.loads(payload)
    restored = from_json(payload)
    assert restored.security is None
    assert restored.metadata.schema_version == 1
    assert to_json(restored) == payload
    # Fingerprint recorded before the optional field was added (schema 1 twin).
    assert twin_fingerprint(restored) == (
        "4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c"
    )


def test_security_field_round_trips_at_the_new_schema_version() -> None:
    twin = make_twin()
    baseline_fingerprint = twin_fingerprint(twin)
    secured = set_security_model(twin, derive_default_security_model(twin))

    assert secured is not twin
    assert twin.security is None
    assert secured.metadata.schema_version == TWIN_SCHEMA_VERSION
    assert secured.security is not None

    restored = from_json(to_json(secured))
    assert restored == secured
    assert to_json(restored) == to_json(secured)
    assert twin_fingerprint(secured) != baseline_fingerprint


def test_to_json_enforces_demand_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("digital_twin.serialization.MAX_DEMANDS", 0)

    with pytest.raises(LimitsExceededError, match="limit is 0"):
        to_json(make_twin())
