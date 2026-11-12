"""Tests for frozen snapshots, deep-copy isolation, diffs, and store bounds."""

from __future__ import annotations

import pytest

from core.exceptions import LimitsExceededError
from core.schemas.routing import TrafficDemand
from digital_twin import (
    OperationalState,
    SnapshotStore,
    add_demand,
    apply_failure,
    create_snapshot,
    diff_twins,
    set_addressing_plan,
    set_link_capacity,
    set_link_cost,
    set_link_state,
    set_topology,
)

from .helpers import CREATED_AT, make_twin


def test_create_snapshot_deep_copies_the_twin() -> None:
    baseline = make_twin()
    snapshot = create_snapshot(baseline, "baseline", captured_at=CREATED_AT)

    baseline.topology.devices[0].site = "mutated-after-snapshot"

    assert snapshot.twin.topology.devices[0].site == "hq"
    assert snapshot.label == "baseline"
    assert snapshot.captured_at == CREATED_AT


def test_scenario_changes_never_alter_the_baseline_or_snapshot() -> None:
    baseline = make_twin()
    before = baseline.model_copy(deep=True)
    snapshot = create_snapshot(baseline, "baseline", captured_at=CREATED_AT)

    scenario = apply_failure(baseline, device_ids=["r1"], link_ids=["l2"])

    assert baseline == before
    assert snapshot.twin == before
    assert scenario != before
    assert snapshot.twin.device_states == ()


def test_diff_of_identical_twins_is_empty() -> None:
    twin = make_twin()

    diff = diff_twins(twin, twin)

    assert diff.has_changes is False
    assert diff.summary() == "No differences."


def test_diff_reports_states_capacities_costs_and_demands() -> None:
    baseline = make_twin()
    scenario = apply_failure(baseline, device_ids=["r1"], link_ids=["l1"])
    scenario = set_link_capacity(scenario, "l2", 250.0)
    scenario = set_link_cost(scenario, "l2", 9.0)
    scenario = add_demand(
        scenario,
        TrafficDemand(
            name="backup",
            source="r2",
            destination="sw1",
            bandwidth_mbps=10.0,
        ),
    )

    diff = diff_twins(baseline, scenario)

    assert [change.entity_id for change in diff.device_state_changes] == ["r1"]
    assert diff.device_state_changes[0].after is OperationalState.down
    assert [change.entity_id for change in diff.link_state_changes] == ["l1"]
    assert [change.link_id for change in diff.capacity_changes] == ["l2"]
    assert diff.capacity_changes[0].before_mbps == 100.0
    assert diff.capacity_changes[0].after_mbps == 250.0
    assert [change.link_id for change in diff.cost_changes] == ["l2"]
    assert diff.demands_added == ("backup",)
    assert "state changes 2" in diff.summary()


def test_diff_reports_device_and_link_additions_and_removals() -> None:
    baseline = make_twin()
    topology = baseline.topology.model_copy(deep=True)
    topology.devices = [device for device in topology.devices if device.id != "sw1"]
    topology.links = [link for link in topology.links if "sw1" not in link.endpoints]
    reduced = set_topology(baseline, topology)

    removed = diff_twins(baseline, reduced)
    added = diff_twins(reduced, baseline)

    assert removed.devices_removed == ("sw1",)
    assert removed.links_removed == ("l2",)
    assert added.devices_added == ("sw1",)
    assert added.links_added == ("l2",)


def test_diff_reports_addressing_changes() -> None:
    baseline = make_twin()
    changed = set_addressing_plan(baseline, None)

    diff = diff_twins(baseline, changed)

    assert diff.addressing_changed is True
    assert diff.has_changes is True


def test_explicit_up_entry_does_not_show_as_a_state_change() -> None:
    baseline = make_twin()
    scenario = set_link_state(
        baseline,
        "l2",
        OperationalState.up,
    )

    diff = diff_twins(baseline, scenario)

    assert diff.link_state_changes == ()


def test_snapshot_store_enforces_count_limit() -> None:
    store = SnapshotStore(max_snapshots=1)
    twin = make_twin()
    store.add(create_snapshot(twin, "one", captured_at=CREATED_AT))

    with pytest.raises(LimitsExceededError, match="1 snapshots"):
        store.add(create_snapshot(twin, "two", captured_at=CREATED_AT))


def test_snapshot_store_enforces_total_byte_limit() -> None:
    store = SnapshotStore(max_total_bytes=1)

    with pytest.raises(LimitsExceededError, match="byte limit"):
        store.add(create_snapshot(make_twin(), "too big", captured_at=CREATED_AT))


def test_snapshot_store_remove_and_clear() -> None:
    store = SnapshotStore()
    twin = make_twin()
    first = create_snapshot(twin, "one", captured_at=CREATED_AT)
    store.add(first)
    store.add(create_snapshot(twin, "two", captured_at=CREATED_AT))

    assert store.remove(0) == first
    assert [snapshot.label for snapshot in store.snapshots] == ["two"]
    store.clear()
    assert store.snapshots == ()
