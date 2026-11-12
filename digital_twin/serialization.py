"""JSON serialization for digital twins with exact round-trip.

Round-trip contract::

    from_json(to_json(twin)) == twin
    to_json(from_json(to_json(twin))) == to_json(twin)

The ``metadata.schema_version`` field is checked before model validation so an
unknown or newer payload fails with :class:`TwinSchemaVersionError` and an
actionable message rather than an opaque field error.
"""

from __future__ import annotations

import json

from config.limits import MAX_DEMANDS
from core.exceptions import LimitsExceededError, SchemaError, TwinSchemaVersionError
from network.topology import enforce_limits

from .models import TWIN_SCHEMA_VERSION, DigitalTwin


def _enforce_twin_limits(twin: DigitalTwin) -> None:
    enforce_limits(twin.topology)
    if len(twin.demands) > MAX_DEMANDS:
        raise LimitsExceededError(
            f"Twin has {len(twin.demands)} demands; the limit is {MAX_DEMANDS}"
        )


def to_json(twin: DigitalTwin, *, indent: int | None = 2) -> str:
    """Serialize ``twin`` to JSON text after checking resource limits."""
    _enforce_twin_limits(twin)
    return twin.model_dump_json(indent=indent)


def json_size_bytes(twin: DigitalTwin) -> int:
    """Return the compact UTF-8 JSON size of a twin in bytes."""
    return len(to_json(twin, indent=None).encode("utf-8"))


def from_json(payload: str) -> DigitalTwin:
    """Parse a twin from JSON text and check its schema version first."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SchemaError(f"Twin JSON is not valid JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise SchemaError("Twin JSON payload must be an object.")

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise TwinSchemaVersionError(
            "Twin JSON is missing the metadata object that carries schema_version."
        )
    version = metadata.get("schema_version")
    if not isinstance(version, int):
        raise TwinSchemaVersionError(
            "Twin JSON metadata.schema_version must be an integer."
        )
    if version != TWIN_SCHEMA_VERSION:
        raise TwinSchemaVersionError(
            f"Twin schema version {version} is not supported; this build "
            f"supports version {TWIN_SCHEMA_VERSION}."
        )

    twin = DigitalTwin.model_validate(data)
    _enforce_twin_limits(twin)
    return twin
