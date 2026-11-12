"""Frozen digital-twin snapshots and structured diffs.

A snapshot owns a deep copy of the twin, so a scenario can never change the
baseline through a shared object reference. :class:`SnapshotStore` bounds the
number of retained snapshots and their combined JSON size.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from config.limits import MAX_SNAPSHOTS, MAX_TWIN_SNAPSHOT_BYTES
from core.exceptions import LimitsExceededError
from core.schemas.routing import TrafficDemand

from .models import (
    DigitalTwin,
    OperationalState,
    effective_device_state,
    effective_link_state,
)
from .serialization import json_size_bytes


class Snapshot(BaseModel):
    """A frozen, deep-copied record of one digital twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(
        min_length=1,
        description="Human-readable snapshot label supplied by the caller.",
    )
    captured_at: datetime = Field(
        description="Timezone-aware capture timestamp (ISO-8601).",
    )
    twin: DigitalTwin = Field(
        description="Deep-copied twin; never shares mutable state with the baseline.",
    )

    def size_bytes(self) -> int:
        """Return the compact UTF-8 JSON size of the captured twin."""
        return json_size_bytes(self.twin)


class StateChange(BaseModel):
    """One entity whose effective operational state changed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: str = Field(description="Device or link id.")
    before: OperationalState = Field(description="Effective state before the change.")
    after: OperationalState = Field(description="Effective state after the change.")


class CapacityChange(BaseModel):
    """One link whose capacity changed (megabits per second)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str = Field(description="Link id.")
    before_mbps: float = Field(description="Capacity before, in Mbps.")
    after_mbps: float = Field(description="Capacity after, in Mbps.")


class CostChange(BaseModel):
    """One link whose routing cost changed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str = Field(description="Link id.")
    before: float = Field(description="Routing cost before.")
    after: float = Field(description="Routing cost after.")


class DemandChange(BaseModel):
    """One named traffic demand whose definition changed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Traffic demand name.")
    before: TrafficDemand = Field(description="Demand before the change.")
    after: TrafficDemand = Field(description="Demand after the change.")


class TwinDiff(BaseModel):
    """Structured difference between two digital twins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    devices_added: tuple[str, ...] = Field(default_factory=tuple)
    devices_removed: tuple[str, ...] = Field(default_factory=tuple)
    links_added: tuple[str, ...] = Field(default_factory=tuple)
    links_removed: tuple[str, ...] = Field(default_factory=tuple)
    device_state_changes: tuple[StateChange, ...] = Field(default_factory=tuple)
    link_state_changes: tuple[StateChange, ...] = Field(default_factory=tuple)
    capacity_changes: tuple[CapacityChange, ...] = Field(default_factory=tuple)
    cost_changes: tuple[CostChange, ...] = Field(default_factory=tuple)
    demands_added: tuple[str, ...] = Field(default_factory=tuple)
    demands_removed: tuple[str, ...] = Field(default_factory=tuple)
    demand_changes: tuple[DemandChange, ...] = Field(default_factory=tuple)
    addressing_changed: bool = Field(
        default=False,
        description="Whether the addressing plan differs.",
    )
    vlan_plan_changed: bool = Field(
        default=False,
        description="Whether the department-to-VLAN plan differs.",
    )
    dhcp_scopes_changed: bool = Field(
        default=False,
        description="Whether the DHCP scopes differ.",
    )
    assumptions_changed: bool = Field(
        default=False,
        description="Whether the scenario assumptions differ.",
    )

    @property
    def has_changes(self) -> bool:
        """Return whether any tracked part of the twin differs."""
        return any(
            (
                self.devices_added,
                self.devices_removed,
                self.links_added,
                self.links_removed,
                self.device_state_changes,
                self.link_state_changes,
                self.capacity_changes,
                self.cost_changes,
                self.demands_added,
                self.demands_removed,
                self.demand_changes,
                self.addressing_changed,
                self.vlan_plan_changed,
                self.dhcp_scopes_changed,
                self.assumptions_changed,
            )
        )

    def summary(self) -> str:
        """Return a short deterministic description of the difference."""
        if not self.has_changes:
            return "No differences."
        parts: list[str] = []
        if self.devices_added or self.devices_removed:
            parts.append(
                f"devices +{len(self.devices_added)}/-{len(self.devices_removed)}"
            )
        if self.links_added or self.links_removed:
            parts.append(f"links +{len(self.links_added)}/-{len(self.links_removed)}")
        if self.device_state_changes or self.link_state_changes:
            parts.append(
                "state changes "
                f"{len(self.device_state_changes) + len(self.link_state_changes)}"
            )
        if self.capacity_changes:
            parts.append(f"capacity changes {len(self.capacity_changes)}")
        if self.cost_changes:
            parts.append(f"cost changes {len(self.cost_changes)}")
        if self.demands_added or self.demands_removed or self.demand_changes:
            parts.append(
                "demands "
                f"+{len(self.demands_added)}/-{len(self.demands_removed)}"
                f"/~{len(self.demand_changes)}"
            )
        if self.addressing_changed:
            parts.append("addressing changed")
        if self.vlan_plan_changed:
            parts.append("VLAN plan changed")
        if self.dhcp_scopes_changed:
            parts.append("DHCP scopes changed")
        if self.assumptions_changed:
            parts.append("assumptions changed")
        return "; ".join(parts) + "."


def create_snapshot(
    twin: DigitalTwin,
    label: str,
    *,
    captured_at: datetime | None = None,
) -> Snapshot:
    """Return a frozen snapshot containing a deep copy of ``twin``.

    ``captured_at`` is supplied by tests and callers that need determinism; it
    defaults to the current UTC time.
    """
    timestamp = captured_at or datetime.now(UTC)
    return Snapshot(
        label=label,
        captured_at=timestamp,
        twin=twin.model_copy(deep=True),
    )


def diff_twins(before: DigitalTwin, after: DigitalTwin) -> TwinDiff:
    """Return a structured device/link/state/capacity/demand diff."""
    before_devices = {device.id: device for device in before.topology.devices}
    after_devices = {device.id: device for device in after.topology.devices}
    before_links = {link.id: link for link in before.topology.links}
    after_links = {link.id: link for link in after.topology.links}

    common_devices = sorted(set(before_devices) & set(after_devices))
    common_links = sorted(set(before_links) & set(after_links))

    device_state_changes = tuple(
        StateChange(
            entity_id=device_id,
            before=effective_device_state(before, device_id),
            after=effective_device_state(after, device_id),
        )
        for device_id in common_devices
        if effective_device_state(before, device_id)
        != effective_device_state(after, device_id)
    )
    link_state_changes = tuple(
        StateChange(
            entity_id=link_id,
            before=effective_link_state(before, link_id),
            after=effective_link_state(after, link_id),
        )
        for link_id in common_links
        if effective_link_state(before, link_id)
        != effective_link_state(after, link_id)
    )
    capacity_changes = tuple(
        CapacityChange(
            link_id=link_id,
            before_mbps=before_links[link_id].capacity_mbps,
            after_mbps=after_links[link_id].capacity_mbps,
        )
        for link_id in common_links
        if before_links[link_id].capacity_mbps
        != after_links[link_id].capacity_mbps
    )
    cost_changes = tuple(
        CostChange(
            link_id=link_id,
            before=before_links[link_id].cost,
            after=after_links[link_id].cost,
        )
        for link_id in common_links
        if before_links[link_id].cost != after_links[link_id].cost
    )

    before_demands = {demand.name: demand for demand in before.demands}
    after_demands = {demand.name: demand for demand in after.demands}
    common_demands = sorted(set(before_demands) & set(after_demands))
    demand_changes = tuple(
        DemandChange(
            name=name,
            before=before_demands[name],
            after=after_demands[name],
        )
        for name in common_demands
        if before_demands[name] != after_demands[name]
    )

    return TwinDiff(
        devices_added=tuple(sorted(set(after_devices) - set(before_devices))),
        devices_removed=tuple(sorted(set(before_devices) - set(after_devices))),
        links_added=tuple(sorted(set(after_links) - set(before_links))),
        links_removed=tuple(sorted(set(before_links) - set(after_links))),
        device_state_changes=device_state_changes,
        link_state_changes=link_state_changes,
        capacity_changes=capacity_changes,
        cost_changes=cost_changes,
        demands_added=tuple(sorted(set(after_demands) - set(before_demands))),
        demands_removed=tuple(sorted(set(before_demands) - set(after_demands))),
        demand_changes=demand_changes,
        addressing_changed=before.addressing != after.addressing,
        vlan_plan_changed=before.vlan_plan != after.vlan_plan,
        dhcp_scopes_changed=before.dhcp_scopes != after.dhcp_scopes,
        assumptions_changed=before.assumptions != after.assumptions,
    )


class SnapshotStore:
    """A bounded, ordered collection of snapshots for one twin."""

    def __init__(
        self,
        *,
        max_snapshots: int = MAX_SNAPSHOTS,
        max_total_bytes: int = MAX_TWIN_SNAPSHOT_BYTES,
    ) -> None:
        self.max_snapshots = max_snapshots
        self.max_total_bytes = max_total_bytes
        self._snapshots: list[Snapshot] = []

    @property
    def snapshots(self) -> tuple[Snapshot, ...]:
        """Return the retained snapshots in creation order."""
        return tuple(self._snapshots)

    @property
    def total_bytes(self) -> int:
        """Return the combined serialized size of all retained snapshots."""
        return sum(snapshot.size_bytes() for snapshot in self._snapshots)

    def add(self, snapshot: Snapshot) -> None:
        """Append a snapshot, enforcing the count and size bounds."""
        if len(self._snapshots) + 1 > self.max_snapshots:
            raise LimitsExceededError(
                f"Cannot retain snapshot {snapshot.label!r}: the limit is "
                f"{self.max_snapshots} snapshots"
            )
        projected = self.total_bytes + snapshot.size_bytes()
        if projected > self.max_total_bytes:
            raise LimitsExceededError(
                f"Cannot retain snapshot {snapshot.label!r}: snapshot storage would "
                f"use {projected} bytes, above the {self.max_total_bytes}-byte limit"
            )
        self._snapshots.append(snapshot)

    def remove(self, index: int) -> Snapshot:
        """Remove and return the snapshot at ``index``."""
        if index < 0 or index >= len(self._snapshots):
            raise IndexError(
                f"Snapshot index {index} is outside 0..{len(self._snapshots) - 1}"
            )
        return self._snapshots.pop(index)

    def clear(self) -> None:
        """Remove every retained snapshot."""
        self._snapshots.clear()
