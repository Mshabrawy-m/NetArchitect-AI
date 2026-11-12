"""Tests for the thin twin-to-engine adapters."""

from __future__ import annotations

import pytest

from digital_twin import (
    DeviceState,
    OperationalState,
    analysis_arguments,
    apply_failure,
    failed_entities,
    routing_arguments,
    validate_engine_twin,
)
from network.analysis import analyze_topology
from network.routing import shortest_path

from .helpers import make_twin


def test_failed_entities_extracts_known_failures() -> None:
    twin = apply_failure(make_twin(), device_ids=["r2"], link_ids=["l2"])

    selection = failed_entities(twin)

    assert selection.devices == ("r2",)
    assert selection.links == ("l2",)
    assert selection.stale_devices == ()
    assert selection.has_failures is True
    assert selection.as_kwargs() == {
        "failed_devices": ("r2",),
        "failed_links": ("l2",),
    }


def test_stale_state_is_kept_out_of_engine_arguments() -> None:
    twin = make_twin(
        device_states=(
            DeviceState(device_id="removed", state=OperationalState.down),
        )
    )

    selection = failed_entities(twin)

    assert selection.devices == ()
    assert selection.stale_devices == ("removed",)
    assert selection.as_kwargs() == {
        "failed_devices": (),
        "failed_links": (),
    }


def test_routing_engine_accepts_twin_arguments() -> None:
    twin = make_twin()

    baseline = shortest_path(
        **routing_arguments(twin),
        source="r1",
        destination="sw1",
    )
    failed = shortest_path(
        **routing_arguments(apply_failure(twin, device_ids=["r2"])),
        source="r1",
        destination="sw1",
    )

    assert baseline.reachable is True
    assert failed.reachable is False


def test_analysis_engine_accepts_twin_arguments() -> None:
    twin = make_twin()

    baseline = analyze_topology(**analysis_arguments(twin))
    failed = analyze_topology(
        **analysis_arguments(apply_failure(twin, device_ids=["r2"]))
    )

    assert baseline.components.component_count == 1
    assert failed.components.component_count == 2


def test_validate_engine_twin_refuses_stale_state() -> None:
    twin = make_twin(
        device_states=(
            DeviceState(device_id="removed", state=OperationalState.down),
        )
    )

    with pytest.raises(ValueError, match="stale operational state"):
        validate_engine_twin(twin)


def test_validate_engine_twin_accepts_a_consistent_twin() -> None:
    validate_engine_twin(make_twin())
