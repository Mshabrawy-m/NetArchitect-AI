"""Bounded JSON, fingerprint, and legacy-v1 twin invariants."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.exceptions import TwinSchemaVersionError
from digital_twin import from_json, to_json
from simulation import twin_fingerprint
from tests.property.config import BOUNDED
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def _reverse_object_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _reverse_object_keys(item)
            for key, item in reversed(list(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_object_keys(item) for item in value]
    return value


@BOUNDED
@given(
    bandwidth=st.integers(1, 1000),
    directed=st.booleans(),
    schema_version=st.sampled_from((1, 2)),
)
def test_twin_json_roundtrip_and_fingerprint_are_stable(
    bandwidth: int, directed: bool, schema_version: int
) -> None:
    topology = make_topology(
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", directed=directed),
            make_link("bc", "b", "c", directed=directed),
        ],
    )
    twin = make_twin(topology, (make_demand("a-to-c", "a", "c", float(bandwidth)),))
    twin = twin.model_copy(
        update={
            "metadata": twin.metadata.model_copy(update={"schema_version": schema_version})
        }
    )

    payload = to_json(twin, indent=2)
    assert '"security"' not in payload

    restored = from_json(payload)
    assert restored == twin
    assert to_json(restored, indent=2) == payload
    assert twin_fingerprint(restored) == twin_fingerprint(twin)

    reordered = json.dumps(_reverse_object_keys(json.loads(payload)))
    assert twin_fingerprint(from_json(reordered)) == twin_fingerprint(twin)

    changed = twin.model_copy(
        update={
            "demands": (
                twin.demands[0].model_copy(update={"bandwidth_mbps": float(bandwidth + 1)}),
            )
        }
    )
    assert twin_fingerprint(changed) != twin_fingerprint(twin)

    unsupported = json.loads(payload)
    unsupported["metadata"]["schema_version"] = 99
    with pytest.raises(TwinSchemaVersionError):
        from_json(json.dumps(unsupported))
