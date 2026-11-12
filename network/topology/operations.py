"""Pure topology editing operations.

Every operation takes a :class:`~core.schemas.network.Topology` and returns a
new, fully validated topology. The input object is never mutated, so callers
can keep previous versions for undo, comparison, or scenario snapshots.

Invalid edits fail with a typed error from :mod:`core.exceptions` rather than
a generic validation traceback:

* duplicate ids -> :class:`~core.exceptions.DuplicateIdError`
* unknown device/link -> :class:`~core.exceptions.DeviceNotFoundError` /
  :class:`~core.exceptions.LinkNotFoundError`
* dangling link endpoint -> :class:`~core.exceptions.MissingEndpointError`
* exceeded ``config.limits`` -> :class:`~core.exceptions.LimitsExceededError`
"""

from __future__ import annotations

from config.limits import MAX_EDGES, MAX_NODES
from core.exceptions import (
    DeviceNotFoundError,
    DuplicateIdError,
    LimitsExceededError,
    LinkNotFoundError,
    MissingEndpointError,
)
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology


def _revalidated(topology: Topology) -> Topology:
    """Re-run model validation on a mutated copy before returning it."""
    return Topology.model_validate(topology.model_dump())


def _device_index(topology: Topology, device_id: str) -> int:
    for index, device in enumerate(topology.devices):
        if device.id == device_id:
            return index
    raise DeviceNotFoundError(f"Device {device_id!r} does not exist in the topology")


def _link_index(topology: Topology, link_id: str) -> int:
    for index, link in enumerate(topology.links):
        if link.id == link_id:
            return index
    raise LinkNotFoundError(f"Link {link_id!r} does not exist in the topology")


def _existing_device_ids(topology: Topology) -> set[str]:
    return {device.id for device in topology.devices}


def _require_endpoints(topology: Topology, link: Link) -> None:
    device_ids = _existing_device_ids(topology)
    missing = [endpoint for endpoint in link.endpoints if endpoint not in device_ids]
    if missing:
        joined = ", ".join(repr(endpoint) for endpoint in missing)
        raise MissingEndpointError(
            f"Link {link.id!r} references unknown device(s): {joined}"
        )


def enforce_limits(topology: Topology) -> Topology:
    """Return the topology unchanged after checking resource limits.

    Raises :class:`~core.exceptions.LimitsExceededError` if the device or link
    count exceeds ``MAX_NODES`` or ``MAX_EDGES``. Generators and import paths
    use this to keep every entry point bounded.
    """
    if len(topology.devices) > MAX_NODES:
        raise LimitsExceededError(
            f"Topology has {len(topology.devices)} devices; the limit is {MAX_NODES}"
        )
    if len(topology.links) > MAX_EDGES:
        raise LimitsExceededError(
            f"Topology has {len(topology.links)} links; the limit is {MAX_EDGES}"
        )
    return topology


def add_device(topology: Topology, device: Device) -> Topology:
    """Return a copy of ``topology`` with ``device`` appended."""
    enforce_limits(topology)
    if len(topology.devices) + 1 > MAX_NODES:
        raise LimitsExceededError(
            f"Cannot add device {device.id!r}: the limit is {MAX_NODES} devices"
        )
    if any(existing.id == device.id for existing in topology.devices):
        raise DuplicateIdError(f"Device id {device.id!r} already exists")

    updated = topology.model_copy(deep=True)
    updated.devices.append(device)
    return _revalidated(updated)


def remove_device(topology: Topology, device_id: str) -> Topology:
    """Return a copy without ``device_id`` and without its attached links."""
    index = _device_index(topology, device_id)

    updated = topology.model_copy(deep=True)
    del updated.devices[index]
    updated.links = [
        link for link in updated.links if device_id not in link.endpoints
    ]
    return _revalidated(updated)


def update_device(
    topology: Topology,
    device_id: str,
    *,
    type: DeviceType | None = None,
    site: str | None = None,
    role: DeviceRole | None = None,
) -> Topology:
    """Return a copy with ``device_id`` attributes replaced.

    Only provided (non-``None``) fields change. Renaming a device is not
    supported because it would require rewriting every attached link; remove
    and re-add the device instead.
    """
    index = _device_index(topology, device_id)
    changes: dict[str, object] = {}
    if type is not None:
        changes["type"] = type
    if site is not None:
        changes["site"] = site
    if role is not None:
        changes["role"] = role

    updated = topology.model_copy(deep=True)
    updated.devices[index] = updated.devices[index].model_copy(update=changes)
    return _revalidated(updated)


def add_link(topology: Topology, link: Link) -> Topology:
    """Return a copy of ``topology`` with ``link`` appended."""
    enforce_limits(topology)
    if len(topology.links) + 1 > MAX_EDGES:
        raise LimitsExceededError(
            f"Cannot add link {link.id!r}: the limit is {MAX_EDGES} links"
        )
    if any(existing.id == link.id for existing in topology.links):
        raise DuplicateIdError(f"Link id {link.id!r} already exists")
    _require_endpoints(topology, link)

    updated = topology.model_copy(deep=True)
    updated.links.append(link)
    return _revalidated(updated)


def remove_link(topology: Topology, link_id: str) -> Topology:
    """Return a copy without ``link_id``. Devices are never removed."""
    index = _link_index(topology, link_id)

    updated = topology.model_copy(deep=True)
    del updated.links[index]
    return _revalidated(updated)


def update_link(
    topology: Topology,
    link_id: str,
    *,
    endpoints: tuple[str, str] | None = None,
    capacity_mbps: float | None = None,
    cost: float | None = None,
    directed: bool | None = None,
) -> Topology:
    """Return a copy with ``link_id`` attributes replaced.

    Only provided (non-``None``) fields change. New endpoints must reference
    existing devices. Link ids are immutable.
    """
    index = _link_index(topology, link_id)
    changes: dict[str, object] = {}
    if endpoints is not None:
        changes["endpoints"] = endpoints
    if capacity_mbps is not None:
        changes["capacity_mbps"] = capacity_mbps
    if cost is not None:
        changes["cost"] = cost
    if directed is not None:
        changes["directed"] = directed

    candidate = topology.links[index].model_copy(update=changes)
    _require_endpoints(topology, candidate)

    updated = topology.model_copy(deep=True)
    updated.links[index] = candidate
    return _revalidated(updated)
