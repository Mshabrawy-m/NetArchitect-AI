"""JSON serialization for digital twins with exact round-trip.

Round-trip contract::

    from_json(to_json(twin)) == twin
    to_json(from_json(to_json(twin))) == to_json(twin)

The ``metadata.schema_version`` field is checked before model validation so an
unknown or newer payload fails with :class:`TwinSchemaVersionError` and an
actionable message rather than an opaque field error.
"""

from __future__ import annotations

from config.limits import MAX_DEMANDS
from core.exceptions import (
    LimitsExceededError,
    MalformedInputError,
    SchemaError,
    TwinSchemaVersionError,
)
from core.inputs import parse_json_text
from network.topology import enforce_limits

from .models import SUPPORTED_TWIN_SCHEMA_VERSIONS, DigitalTwin


def _enforce_twin_limits(twin: DigitalTwin) -> None:
    enforce_limits(twin.topology)
    if len(twin.demands) > MAX_DEMANDS:
        raise LimitsExceededError(
            f"Twin has {len(twin.demands)} demands; the limit is {MAX_DEMANDS}"
        )


def _serialization_exclude(twin: DigitalTwin) -> set[str] | None:
    """Return default-only additive fields that legacy bytes must omit."""
    exclude: set[str] = set()
    if twin.security is None:
        exclude.add("security")
    if not twin.shared_risk_groups:
        exclude.add("shared_risk_groups")
    if not twin.ha_groups:
        exclude.add("ha_groups")
    if twin.ipv6_plan is None:
        exclude.add("ipv6_plan")
    if twin.nat_plan is None:
        exclude.add("nat_plan")
    if twin.ospf_design is None:
        exclude.add("ospf_design")
    return exclude or None


def canonical_payload(twin: DigitalTwin) -> dict[str, object]:
    """Return the canonical mapping used for fingerprints.

    Default-only additive fields (``security``, ``shared_risk_groups``,
    ``ha_groups``, ``ipv6_plan``, ``nat_plan``, and ``ospf_design``) are omitted
    so twins created before those fields were added have exactly the same
    fingerprint bytes as before.
    """
    return twin.model_dump(mode="json", exclude=_serialization_exclude(twin))


def to_json(twin: DigitalTwin, *, indent: int | None = 2) -> str:
    """Serialize ``twin`` to JSON text after checking resource limits."""
    _enforce_twin_limits(twin)
    return twin.model_dump_json(indent=indent, exclude=_serialization_exclude(twin))


def json_size_bytes(twin: DigitalTwin) -> int:
    """Return the compact UTF-8 JSON size of a twin in bytes."""
    return len(to_json(twin, indent=None).encode("utf-8"))


def from_json(payload: str) -> DigitalTwin:
    """Parse a twin from JSON text and check its schema version first."""
    try:
        data = parse_json_text(payload, label="Twin JSON")
    except MalformedInputError as error:
        raise SchemaError(f"Twin JSON is not valid JSON: {error}") from error
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
