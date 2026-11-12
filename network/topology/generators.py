"""Deterministic topology generators.

Every generator is a pure function: the same arguments always produce the
same device ids, link ids, endpoint order, and attribute values. Generated
topologies use undirected links unless stated otherwise.

All generators enforce ``config.limits.MAX_NODES`` and ``MAX_EDGES`` *before*
building anything, so an oversized request fails immediately with
:class:`~core.exceptions.LimitsExceededError` instead of consuming memory.

Implemented families: star, ring, full mesh, and tree. Hierarchical campus,
spine-leaf, and hybrid generators are added in the next phase.
"""

from __future__ import annotations

from config.limits import MAX_EDGES, MAX_NODES
from core.exceptions import LimitsExceededError
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology

DEFAULT_SITE = "site-1"
DEFAULT_CAPACITY_MBPS = 1000.0
DEFAULT_COST = 1.0


def _check_counts(device_count: int, link_count: int, label: str) -> None:
    if device_count > MAX_NODES:
        raise LimitsExceededError(
            f"{label} needs {device_count} devices; the limit is {MAX_NODES}"
        )
    if link_count > MAX_EDGES:
        raise LimitsExceededError(
            f"{label} needs {link_count} links; the limit is {MAX_EDGES}"
        )


def _device(
    device_id: str,
    device_type: DeviceType,
    role: DeviceRole,
    site: str,
) -> Device:
    return Device(id=device_id, type=device_type, site=site, role=role)


def _link(
    link_id: str,
    first: str,
    second: str,
    capacity_mbps: float,
    cost: float,
) -> Link:
    return Link(
        id=link_id,
        endpoints=(first, second),
        capacity_mbps=capacity_mbps,
        cost=cost,
        directed=False,
    )


def generate_star(
    *,
    name: str = "Star topology",
    site: str = DEFAULT_SITE,
    spoke_count: int = 4,
    hub_id: str = "star-hub",
    id_prefix: str = "star",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Generate a star: one core switch with ``spoke_count`` host spokes.

    Devices: 1 hub switch (role ``core``) + ``spoke_count`` hosts (role
    ``access``). Links: ``spoke_count`` undirected hub-to-spoke links.
    """
    if spoke_count < 1:
        raise ValueError(f"spoke_count must be at least 1, got {spoke_count}")
    device_count = spoke_count + 1
    _check_counts(device_count, spoke_count, "Star topology")

    devices = [
        _device(hub_id, DeviceType.switch, DeviceRole.core, site),
    ]
    links: list[Link] = []
    for index in range(spoke_count):
        spoke_id = f"{id_prefix}-spoke-{index:02d}"
        devices.append(
            _device(spoke_id, DeviceType.host, DeviceRole.access, site)
        )
        links.append(
            _link(
                f"{id_prefix}-link-{index:02d}",
                hub_id,
                spoke_id,
                link_capacity_mbps,
                link_cost,
            )
        )
    return Topology(name=name, devices=devices, links=links)


def generate_ring(
    *,
    name: str = "Ring topology",
    site: str = DEFAULT_SITE,
    node_count: int = 4,
    id_prefix: str = "ring",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Generate a ring of routers closed back to the first node.

    Devices: ``node_count`` routers (role ``core``). Links: ``node_count``
    undirected links (the last link closes the loop). Requires at least three
    nodes so the graph is a true ring, not a duplicate parallel link.
    """
    if node_count < 3:
        raise ValueError(f"node_count must be at least 3, got {node_count}")
    _check_counts(node_count, node_count, "Ring topology")

    device_ids = [
        f"{id_prefix}-node-{index:02d}" for index in range(node_count)
    ]
    devices = [
        _device(device_id, DeviceType.router, DeviceRole.core, site)
        for device_id in device_ids
    ]
    links = [
        _link(
            f"{id_prefix}-link-{index:02d}",
            device_ids[index],
            device_ids[(index + 1) % node_count],
            link_capacity_mbps,
            link_cost,
        )
        for index in range(node_count)
    ]
    return Topology(name=name, devices=devices, links=links)


def generate_mesh(
    *,
    name: str = "Full mesh topology",
    site: str = DEFAULT_SITE,
    node_count: int = 4,
    id_prefix: str = "mesh",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Generate a full mesh (every pair of routers linked once).

    Devices: ``node_count`` routers (role ``core``). Links: the complete graph
    ``node_count * (node_count - 1) / 2``. The edge bound is enforced before
    generation, so large requests are rejected rather than truncated.
    """
    if node_count < 2:
        raise ValueError(f"node_count must be at least 2, got {node_count}")
    link_count = node_count * (node_count - 1) // 2
    _check_counts(node_count, link_count, "Full mesh topology")

    device_ids = [
        f"{id_prefix}-node-{index:02d}" for index in range(node_count)
    ]
    devices = [
        _device(device_id, DeviceType.router, DeviceRole.core, site)
        for device_id in device_ids
    ]
    links: list[Link] = []
    for first in range(node_count):
        for second in range(first + 1, node_count):
            links.append(
                _link(
                    f"{id_prefix}-link-{first:02d}-{second:02d}",
                    device_ids[first],
                    device_ids[second],
                    link_capacity_mbps,
                    link_cost,
                )
            )
    return Topology(name=name, devices=devices, links=links)


def generate_tree(
    *,
    name: str = "Tree topology",
    site: str = DEFAULT_SITE,
    depth: int = 2,
    branching_factor: int = 2,
    id_prefix: str = "tree",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Generate a balanced tree with the given depth and branching factor.

    ``depth=0`` is a single root. Each device at level ``level`` has
    ``branching_factor`` children until ``depth`` is reached.

    Devices: root router (role ``core``), intermediate levels switches (role
    ``distribution``), leaves switches (role ``access``). Links: parent-to-child
    undirected links, ``device_count - 1`` in total.
    """
    if depth < 0:
        raise ValueError(f"depth must be non-negative, got {depth}")
    if branching_factor < 1:
        raise ValueError(
            f"branching_factor must be at least 1, got {branching_factor}"
        )

    level_sizes: list[int] = []
    device_count = 0
    for level in range(depth + 1):
        level_size = branching_factor**level
        device_count += level_size
        if device_count > MAX_NODES:
            raise LimitsExceededError(
                f"Tree topology with depth {depth} and branching factor "
                f"{branching_factor} exceeds the limit of {MAX_NODES} devices"
            )
        level_sizes.append(level_size)
    _check_counts(
        device_count,
        device_count - 1,
        f"Tree topology with depth {depth} and branching factor {branching_factor}",
    )

    def node_id(level: int, index: int) -> str:
        return f"{id_prefix}-l{level}-n{index:02d}"

    devices: list[Device] = []
    for level, level_size in enumerate(level_sizes):
        for index in range(level_size):
            if level == 0:
                device_type = DeviceType.router
                role = DeviceRole.core
            else:
                device_type = DeviceType.switch
                role = DeviceRole.access if level == depth else DeviceRole.distribution
            devices.append(
                _device(node_id(level, index), device_type, role, site)
            )

    links: list[Link] = []
    for level in range(1, depth + 1):
        for index in range(level_sizes[level]):
            parent_index = index // branching_factor
            links.append(
                _link(
                    f"{id_prefix}-link-l{level}-n{index:02d}",
                    node_id(level - 1, parent_index),
                    node_id(level, index),
                    link_capacity_mbps,
                    link_cost,
                )
            )
    return Topology(name=name, devices=devices, links=links)
