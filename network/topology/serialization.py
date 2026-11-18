"""JSON import/export for topologies with exact round-trip.

Round-trip contract::

    from_json(to_json(topology)) == topology
    to_json(from_json(to_json(topology))) == to_json(topology)

All parsing goes through Pydantic, so invalid JSON, unknown fields, bad
enum values, dangling endpoints, and duplicate ids are rejected with
``pydantic.ValidationError`` rather than silently coerced.
"""

from __future__ import annotations

from core.exceptions import MalformedInputError
from core.inputs import parse_json_text
from core.schemas.network import Topology

from .operations import enforce_limits


def to_json(topology: Topology, *, indent: int | None = 2) -> str:
    """Serialize ``topology`` to JSON text.

    ``indent`` is 2 by default for readable exports; pass ``None`` for a
    compact single-line payload. Link endpoint order is preserved.
    """
    enforce_limits(topology)
    return topology.model_dump_json(indent=indent)


def from_json(payload: str) -> Topology:
    """Parse and validate a topology from bounded, untrusted JSON text."""
    try:
        data = parse_json_text(payload, label="Topology JSON")
    except MalformedInputError:
        # Preserve the existing ValidationError contract for malformed syntax.
        topology = Topology.model_validate_json(payload)
    else:
        topology = Topology.model_validate(data)
    return enforce_limits(topology)
