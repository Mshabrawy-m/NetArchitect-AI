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

from .models import SUPPORTED_TWIN_SCHEMA_VERSIONS, DigitalTwin


def _enforce_twin_limits(twin: DigitalTwin) -> None:
    enforce_limits(twin.topology)
    if len(twin.demands) > MAX_DEMANDS:
        raise LimitsExceededError(
            f"Twin has {len(twin.demands)} demands; the limit is {MAX_DEMANDS}"
        )


def canonical_payload(twin: DigitalTwin) -> dict[str, object]:
    """Return the canonical mapping used for fingerprints.

    ``security=None`` is omitted so twins created before Phase 14 have exactly
    the same fingerprint bytes as before the optional field was added.
    """
    exclude = {"security"} if twin.security is None else None
    return twin.model_dump(mode="json", exclude=exclude)


def to_json(twin: DigitalTwin, *, indent: int | None = 2) -> str:
    """Serialize ``twin`` to JSON text after checking resource limits."""
    _enforce_twin_limits(twin)
    exclude = {"security"} if twin.security is None else None
    return twin.model_dump_json(indent=indent, exclude=exclude)


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
    if version not in SUPPORTED_TWIN_SCHEMA_VERSIONS:
        supported = ", ".join(str(item) for item in SUPPORTED_TWIN_SCHEMA_VERSIONS)
        raise TwinSchemaVersionError(
            f"Twin schema version {version} is not supported; this build "
            f"supports versions {supported}."
        )

    twin = DigitalTwin.model_validate(data)
    _enforce_twin_limits(twin)
    return twin
