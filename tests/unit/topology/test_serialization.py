"""Tests for ``network.topology.serialization``."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.exceptions import LimitsExceededError
from core.schemas.network import Topology
from network.topology.serialization import from_json, to_json

from .helpers import make_device, make_link


def test_json_round_trip_is_exact(mixed_topology: Topology) -> None:
    restored = from_json(to_json(mixed_topology))

    assert restored == mixed_topology
    assert to_json(restored) == to_json(mixed_topology)


def test_json_round_trip_preserves_endpoint_order(
    mixed_topology: Topology,
) -> None:
    restored = from_json(to_json(mixed_topology))

    undirected = next(link for link in restored.links if link.id == "l-undirected")
    assert undirected.endpoints == ("r2", "r1")


def test_json_round_trip_preserves_directed_flag(
    mixed_topology: Topology,
) -> None:
    restored = from_json(to_json(mixed_topology))

    flags = {link.id: link.directed for link in restored.links}
    assert flags == {"l-undirected": False, "l-directed": True}


def test_to_json_is_pretty_printed_by_default(mixed_topology: Topology) -> None:
    payload = to_json(mixed_topology)

    assert payload.startswith("{")
    assert "\n" in payload
    json.loads(payload)


def test_to_json_can_be_compact(mixed_topology: Topology) -> None:
    payload = to_json(mixed_topology, indent=None)

    assert "\n" not in payload
    assert json.loads(payload)["name"] == "Mixed test topology"


def test_from_json_rejects_malformed_json() -> None:
    with pytest.raises(ValidationError):
        from_json("{not json")


def test_from_json_rejects_dangling_endpoint() -> None:
    payload = json.dumps(
        {
            "name": "bad",
            "devices": [
                {"id": "a", "type": "router", "site": "s", "role": "core"}
            ],
            "links": [
                {
                    "id": "l",
                    "endpoints": ["a", "ghost"],
                    "capacity_mbps": 10.0,
                    "cost": 1.0,
                }
            ],
        }
    )

    with pytest.raises(ValidationError, match="unknown device 'ghost'"):
        from_json(payload)


def test_from_json_enforces_node_limit(
    mixed_topology: Topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("network.topology.operations.MAX_NODES", 2)

    with pytest.raises(LimitsExceededError):
        from_json(to_json(mixed_topology))


def test_to_json_enforces_edge_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = Topology(
        name="small",
        devices=[make_device("a"), make_device("b")],
        links=[make_link("l", "a", "b")],
    )
    monkeypatch.setattr("network.topology.operations.MAX_EDGES", 0)

    with pytest.raises(LimitsExceededError):
        to_json(topology)
