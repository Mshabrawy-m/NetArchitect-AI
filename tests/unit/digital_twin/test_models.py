"""Tests for frozen digital-twin models and effective state defaults."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from digital_twin import (
    DeviceState,
    DigitalTwin,
    LinkState,
    OperationalState,
    effective_device_state,
    effective_link_state,
)

from .helpers import make_twin


def test_twin_is_frozen() -> None:
    twin = make_twin()

    with pytest.raises(ValidationError):
        twin.metadata = twin.metadata  # type: ignore[misc]


def test_metadata_requires_name_and_created_at() -> None:
    with pytest.raises(ValidationError):
        DigitalTwin.model_validate(
            {
                "metadata": {"name": ""},
                "topology": {"name": "empty"},
            }
        )


def test_missing_state_means_up() -> None:
    twin = make_twin()

    assert effective_device_state(twin, "r1") is OperationalState.up
    assert effective_link_state(twin, "l1") is OperationalState.up


def test_explicit_down_state_is_reported() -> None:
    twin = make_twin(
        device_states=(DeviceState(device_id="r1", state=OperationalState.down),),
        link_states=(LinkState(link_id="l2", state=OperationalState.down),),
    )

    assert effective_device_state(twin, "r1") is OperationalState.down
    assert effective_link_state(twin, "l2") is OperationalState.down
