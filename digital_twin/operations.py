"""Immutable-style operations on a digital twin.

Every function takes a twin and returns a new twin. The input object is never
mutated, so a baseline twin and a scenario copy can be compared safely.

Operational state uses the canonical convention that an entity without a state
entry is ``up``. Operations that mark entities up remove their entries.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from config.limits import MAX_DEMANDS
from core.exceptions import (
    DeviceNotFoundError,
    DuplicateIdError,
    LimitsExceededError,
    LinkNotFoundError,
)
from core.schemas.addressing import AddressingPlan, DhcpScope
from core.schemas.network import Topology
from core.schemas.requirements import Assumption
from core.schemas.routing import TrafficDemand
from network.topology import update_link
from network.vlan.plan import VlanPlanResult

from .models import (
    DeviceState,
    DigitalTwin,
    LinkState,
    OperationalState,
)


def _device_ids(topology: Topology) -> set[str]:
    return {device.id for device in topology.devices}


def _link_ids(topology: Topology) -> set[str]:
    return {link.id for link in topology.links}


def _require_devices(twin: DigitalTwin, device_ids: Iterable[str]) -> None:
    known = _device_ids(twin.topology)
    missing = sorted({device_id for device_id in device_ids} - known)
    if missing:
        raise DeviceNotFoundError(
            "Device(s) not present in the twin topology: " + ", ".join(missing)
        )


def _require_links(twin: DigitalTwin, link_ids: Iterable[str]) -> None:
    known = _link_ids(twin.topology)
    missing = sorted({link_id for link_id in link_ids} - known)
    if missing:
        raise LinkNotFoundError(
            "Link(s) not present in the twin topology: " + ", ".join(missing)
        )


def set_topology(twin: DigitalTwin, topology: Topology) -> DigitalTwin:
    """Return a twin with ``topology`` replaced.

    Addressing, VLAN, DHCP, demand, and state data are preserved. Any stored
    reference that no longer exists is reported by
    :func:`digital_twin.validation.validate_twin`; it is never pruned silently.
    """
    return twin.model_copy(
        deep=True,
        update={"topology": topology.model_copy(deep=True)},
    )


def set_device_state(
    twin: DigitalTwin,
    device_id: str,
    state: OperationalState,
) -> DigitalTwin:
    """Set one device's modeled state, returning a new twin."""
    _require_devices(twin, [device_id])
    remaining = [
        entry for entry in twin.device_states if entry.device_id != device_id
    ]
    if state is OperationalState.down:
        remaining.append(DeviceState(device_id=device_id, state=state))
    return twin.model_copy(update={"device_states": tuple(remaining)})


def set_link_state(
    twin: DigitalTwin,
    link_id: str,
    state: OperationalState,
) -> DigitalTwin:
    """Set one link's modeled state, returning a new twin."""
    _require_links(twin, [link_id])
    remaining = [entry for entry in twin.link_states if entry.link_id != link_id]
    if state is OperationalState.down:
        remaining.append(LinkState(link_id=link_id, state=state))
    return twin.model_copy(update={"link_states": tuple(remaining)})


def set_operational_states(
    twin: DigitalTwin,
    *,
    down_devices: Iterable[str] = (),
    down_links: Iterable[str] = (),
) -> DigitalTwin:
    """Replace the known-entity states with exactly the supplied down sets.

    Unknown ``down_*`` ids raise the typed not-found errors. Stored state
    entries that already reference removed entities are preserved so validation
    can continue to report them.
    """
    down_device_ids = sorted(set(down_devices))
    down_link_ids = sorted(set(down_links))
    _require_devices(twin, down_device_ids)
    _require_links(twin, down_link_ids)

    known_device_ids = _device_ids(twin.topology)
    known_link_ids = _link_ids(twin.topology)
    stale_devices = [
        entry
        for entry in twin.device_states
        if entry.device_id not in known_device_ids
    ]
    stale_links = [
        entry for entry in twin.link_states if entry.link_id not in known_link_ids
    ]
    device_states = tuple(
        stale_devices
        + [
            DeviceState(device_id=device_id, state=OperationalState.down)
            for device_id in down_device_ids
        ]
    )
    link_states = tuple(
        stale_links
        + [
            LinkState(link_id=link_id, state=OperationalState.down)
            for link_id in down_link_ids
        ]
    )
    return twin.model_copy(
        update={"device_states": device_states, "link_states": link_states}
    )


def apply_failure(
    twin: DigitalTwin,
    *,
    device_ids: Iterable[str] = (),
    link_ids: Iterable[str] = (),
) -> DigitalTwin:
    """Mark the supplied devices and links as down, returning a new twin."""
    device_updates = set(device_ids)
    link_updates = set(link_ids)
    _require_devices(twin, device_updates)
    _require_links(twin, link_updates)

    device_states = {
        entry.device_id: entry for entry in twin.device_states
    }
    for device_id in device_updates:
        device_states[device_id] = DeviceState(
            device_id=device_id, state=OperationalState.down
        )
    link_states = {entry.link_id: entry for entry in twin.link_states}
    for link_id in link_updates:
        link_states[link_id] = LinkState(
            link_id=link_id, state=OperationalState.down
        )
    return twin.model_copy(
        update={
            "device_states": tuple(device_states.values()),
            "link_states": tuple(link_states.values()),
        }
    )


def restore_entities(
    twin: DigitalTwin,
    *,
    device_ids: Iterable[str] = (),
    link_ids: Iterable[str] = (),
) -> DigitalTwin:
    """Mark the supplied devices and links as up, returning a new twin."""
    device_restores = set(device_ids)
    link_restores = set(link_ids)
    _require_devices(twin, device_restores)
    _require_links(twin, link_restores)
    device_states = tuple(
        entry
        for entry in twin.device_states
        if entry.device_id not in device_restores
    )
    link_states = tuple(
        entry for entry in twin.link_states if entry.link_id not in link_restores
    )
    return twin.model_copy(
        update={"device_states": device_states, "link_states": link_states}
    )


def set_link_capacity(
    twin: DigitalTwin,
    link_id: str,
    capacity_mbps: float,
) -> DigitalTwin:
    """Return a twin with one link's capacity replaced (megabits per second)."""
    _require_links(twin, [link_id])
    topology = update_link(
        twin.topology,
        link_id,
        capacity_mbps=capacity_mbps,
    )
    return set_topology(twin, topology)


def set_link_cost(twin: DigitalTwin, link_id: str, cost: float) -> DigitalTwin:
    """Return a twin with one link's routing cost replaced."""
    _require_links(twin, [link_id])
    topology = update_link(twin.topology, link_id, cost=cost)
    return set_topology(twin, topology)


def add_demand(twin: DigitalTwin, demand: TrafficDemand) -> DigitalTwin:
    """Return a twin with one traffic demand appended."""
    if len(twin.demands) + 1 > MAX_DEMANDS:
        raise LimitsExceededError(
            f"Cannot add demand {demand.name!r}: the limit is {MAX_DEMANDS}"
        )
    if any(existing.name == demand.name for existing in twin.demands):
        raise DuplicateIdError(f"Demand name {demand.name!r} already exists")
    _require_devices(twin, [demand.source, demand.destination])
    return twin.model_copy(update={"demands": (*twin.demands, demand)})


def remove_demand(twin: DigitalTwin, name: str) -> DigitalTwin:
    """Return a twin without the named traffic demand."""
    remaining = tuple(demand for demand in twin.demands if demand.name != name)
    if len(remaining) == len(twin.demands):
        raise ValueError(f"Demand {name!r} does not exist in the twin")
    return twin.model_copy(update={"demands": remaining})


def set_demands(
    twin: DigitalTwin,
    demands: Sequence[TrafficDemand],
) -> DigitalTwin:
    """Replace all traffic demands after validating names and endpoints."""
    if len(demands) > MAX_DEMANDS:
        raise LimitsExceededError(
            f"The twin would have {len(demands)} demands; the limit is {MAX_DEMANDS}"
        )
    names: set[str] = set()
    for demand in demands:
        if demand.name in names:
            raise DuplicateIdError(f"Demand name {demand.name!r} already exists")
        names.add(demand.name)
        _require_devices(twin, [demand.source, demand.destination])
    return twin.model_copy(update={"demands": tuple(demands)})


def set_addressing_plan(
    twin: DigitalTwin,
    addressing: AddressingPlan | None,
) -> DigitalTwin:
    """Return a twin with the IP addressing plan replaced (or cleared)."""
    return twin.model_copy(update={"addressing": addressing})


def set_vlan_plan(
    twin: DigitalTwin,
    vlan_plan: VlanPlanResult | None,
) -> DigitalTwin:
    """Return a twin with the department-to-VLAN plan replaced (or cleared)."""
    return twin.model_copy(update={"vlan_plan": vlan_plan})


def set_dhcp_scopes(
    twin: DigitalTwin,
    scopes: Sequence[DhcpScope],
) -> DigitalTwin:
    """Return a twin with the DHCP scopes replaced."""
    return twin.model_copy(update={"dhcp_scopes": tuple(scopes)})


def set_assumptions(
    twin: DigitalTwin,
    assumptions: Sequence[Assumption],
) -> DigitalTwin:
    """Return a twin with the scenario assumptions replaced."""
    return twin.model_copy(update={"assumptions": tuple(assumptions)})


def add_assumption(twin: DigitalTwin, assumption: Assumption) -> DigitalTwin:
    """Return a twin with one scenario assumption appended."""
    if any(existing.id == assumption.id for existing in twin.assumptions):
        raise DuplicateIdError(f"Assumption id {assumption.id!r} already exists")
    return twin.model_copy(
        update={"assumptions": (*twin.assumptions, assumption)}
    )
