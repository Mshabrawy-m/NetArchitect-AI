"""Tests for immutable digital-twin operations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.exceptions import (
    DeviceNotFoundError,
    DuplicateIdError,
    LimitsExceededError,
    LinkNotFoundError,
)
from core.schemas.routing import TrafficDemand
from digital_twin import (
    DeviceState,
    OperationalState,
    add_demand,
    apply_failure,
    effective_device_state,
    effective_link_state,
    remove_demand,
    restore_entities,
    set_demands,
    set_link_capacity,
    set_link_cost,
    set_operational_states,
    set_topology,
    validate_twin,
)

from .helpers import make_twin


def test_apply_failure_returns_a_new_twin_and_leaves_baseline_unchanged() -> None:
    baseline = make_twin()
    before = baseline.model_copy(deep=True)

    scenario = apply_failure(baseline, device_ids=["r1"], link_ids=["l2"])

    assert baseline == before
    assert scenario is not baseline
    assert effective_device_state(scenario, "r1") is OperationalState.down
    assert effective_link_state(scenario, "l2") is OperationalState.down
    assert effective_device_state(baseline, "r1") is OperationalState.up
    assert effective_link_state(baseline, "l2") is OperationalState.up


def test_restore_entities_removes_down_entries() -> None:
    scenario = apply_failure(make_twin(), device_ids=["r1"], link_ids=["l2"])

    restored = restore_entities(scenario, device_ids=["r1"], link_ids=["l2"])

    assert restored.device_states == ()
    assert restored.link_states == ()


def test_set_link_capacity_replaces_only_the_link() -> None:
    baseline = make_twin()

    updated = set_link_capacity(baseline, "l2", 250.0)

    assert baseline.topology.links[1].capacity_mbps == 100.0
    assert updated.topology.links[1].capacity_mbps == 250.0
    assert updated.topology.devices == baseline.topology.devices


def test_set_link_capacity_rejects_nonpositive_values() -> None:
    with pytest.raises(ValidationError):
        set_link_capacity(make_twin(), "l2", 0.0)


def test_set_link_cost_replaces_only_the_cost() -> None:
    updated = set_link_cost(make_twin(), "l1", 7.5)

    assert updated.topology.links[0].cost == 7.5
    assert updated.topology.links[0].capacity_mbps == 1000.0


def test_unknown_entities_raise_typed_errors() -> None:
    twin = make_twin()

    with pytest.raises(DeviceNotFoundError):
        apply_failure(twin, device_ids=["missing"])
    with pytest.raises(LinkNotFoundError):
        apply_failure(twin, link_ids=["missing"])
    with pytest.raises(LinkNotFoundError):
        set_link_capacity(twin, "missing", 10.0)


def test_add_and_remove_demand() -> None:
    twin = make_twin(demands=())
    demand = TrafficDemand(
        name="backup",
        source="r2",
        destination="sw1",
        bandwidth_mbps=25.0,
    )

    added = add_demand(twin, demand)
    removed = remove_demand(added, "backup")

    assert added.demands == (demand,)
    assert removed.demands == ()


def test_add_duplicate_demand_name_is_rejected() -> None:
    twin = make_twin()

    with pytest.raises(DuplicateIdError):
        add_demand(
            twin,
            TrafficDemand(
                name="client-to-server",
                source="r1",
                destination="r2",
                bandwidth_mbps=1.0,
            ),
        )


def test_add_demand_enforces_the_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("digital_twin.operations.MAX_DEMANDS", 1)

    with pytest.raises(LimitsExceededError):
        add_demand(
            make_twin(),
            TrafficDemand(
                name="extra",
                source="r1",
                destination="r2",
                bandwidth_mbps=1.0,
            ),
        )


def test_set_demands_rejects_duplicate_names_and_unknown_devices() -> None:
    twin = make_twin(demands=())

    with pytest.raises(DuplicateIdError):
        set_demands(
            twin,
            [
                TrafficDemand(
                    name="a", source="r1", destination="r2", bandwidth_mbps=1.0
                ),
                TrafficDemand(
                    name="a", source="r1", destination="sw1", bandwidth_mbps=1.0
                ),
            ],
        )

    with pytest.raises(DeviceNotFoundError):
        set_demands(
            twin,
            [
                TrafficDemand(
                    name="a", source="r1", destination="ghost", bandwidth_mbps=1.0
                )
            ],
        )


def test_set_operational_states_preserves_stale_state_for_validation() -> None:
    twin = make_twin(
        device_states=(DeviceState(device_id="removed", state=OperationalState.down),)
    )

    updated = set_operational_states(twin, down_devices=["r1"])

    assert {entry.device_id for entry in updated.device_states} == {"r1", "removed"}
    assert "twin_unknown_device_state" in {
        finding.code for finding in validate_twin(updated).findings
    }


def test_set_topology_preserves_dependent_parts_and_reports_stale_state() -> None:
    twin = make_twin()
    topology = twin.topology.model_copy(deep=True)
    topology.devices = [device for device in topology.devices if device.id != "r1"]
    topology.links = [link for link in topology.links if "r1" not in link.endpoints]

    updated = set_topology(twin, topology)

    assert updated.addressing == twin.addressing
    assert updated.dhcp_scopes == twin.dhcp_scopes
    assert updated.demands == twin.demands
    codes = {finding.code for finding in validate_twin(updated).findings}
    assert "twin_demand_unknown_device" in codes
