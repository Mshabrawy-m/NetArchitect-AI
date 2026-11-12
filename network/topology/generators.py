"""Deterministic topology generators.

Every generator is a pure function: the same arguments always produce the
same device ids, link ids, endpoint order, and attribute values. Generated
topologies use undirected links unless stated otherwise.

All generators enforce ``config.limits.MAX_NODES`` and ``MAX_EDGES`` *before*
building anything, so an oversized request fails immediately with
:class:`~core.exceptions.LimitsExceededError` instead of consuming memory.

Implemented families: star, ring, full mesh, tree, hierarchical campus,
spine-leaf, and hybrid. Generators are added incrementally; every one is
compositional and deterministic.
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


def generate_hierarchical_campus(
    *,
    name: str = "Hierarchical campus",
    site: str = DEFAULT_SITE,
    distribution_count: int = 2,
    access_per_distribution: int = 4,
    redundant_uplinks: bool = False,
    id_prefix: str = "campus",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Generate a three-tier campus: core -> distribution -> access.

    The core layer holds one router normally, or two routers when
    ``redundant_uplinks`` is enabled. Redundant mode dual-homes every
    distribution switch to both core routers and every access switch to two
    distribution switches (primary plus the next one in ring order), so
    ``distribution_count`` must be at least 2.

    Counts (``D`` distribution switches, ``A`` access switches per
    distribution)::

        devices = (2 if redundant else 1) + D + D * A
        links   = (2 if redundant else 1) * D + (2 if redundant else 1) * D * A

    All links are undirected. Device roles are ``core``, ``distribution``,
    and ``access``; types are routers at the core and switches below it.
    """
    if distribution_count < 1:
        raise ValueError(
            f"distribution_count must be at least 1, got {distribution_count}"
        )
    if access_per_distribution < 1:
        raise ValueError(
            "access_per_distribution must be at least 1, "
            f"got {access_per_distribution}"
        )
    if redundant_uplinks and distribution_count < 2:
        raise ValueError(
            "redundant_uplinks requires distribution_count of at least 2"
        )

    core_count = 2 if redundant_uplinks else 1
    access_count = distribution_count * access_per_distribution
    device_count = core_count + distribution_count + access_count
    uplink_factor = 2 if redundant_uplinks else 1
    link_count = uplink_factor * distribution_count + uplink_factor * access_count
    _check_counts(device_count, link_count, "Hierarchical campus")

    core_ids = [f"{id_prefix}-core-{index + 1:02d}" for index in range(core_count)]
    dist_ids = [
        f"{id_prefix}-dist-{index + 1:02d}" for index in range(distribution_count)
    ]

    devices: list[Device] = [
        _device(device_id, DeviceType.router, DeviceRole.core, site)
        for device_id in core_ids
    ]
    devices.extend(
        _device(device_id, DeviceType.switch, DeviceRole.distribution, site)
        for device_id in dist_ids
    )

    links: list[Link] = []
    for dist_index, dist_id in enumerate(dist_ids):
        core_targets = core_ids if redundant_uplinks else core_ids[:1]
        for core_index, core_id in enumerate(core_targets):
            links.append(
                _link(
                    f"{id_prefix}-link-core-{core_index + 1:02d}-dist-"
                    f"{dist_index + 1:02d}",
                    core_id,
                    dist_id,
                    link_capacity_mbps,
                    link_cost,
                )
            )

    for dist_index, dist_id in enumerate(dist_ids):
        parent_ids = (
            [dist_id, dist_ids[(dist_index + 1) % distribution_count]]
            if redundant_uplinks
            else [dist_id]
        )
        for access_index in range(access_per_distribution):
            access_id = (
                f"{id_prefix}-acc-{dist_index + 1:02d}-{access_index + 1:02d}"
            )
            devices.append(
                _device(access_id, DeviceType.switch, DeviceRole.access, site)
            )
            for parent in parent_ids:
                links.append(
                    _link(
                        f"{id_prefix}-link-dist-{parent.split('-')[-1]}-"
                        f"acc-{dist_index + 1:02d}-{access_index + 1:02d}",
                        parent,
                        access_id,
                        link_capacity_mbps,
                        link_cost,
                    )
                )

    return Topology(name=name, devices=devices, links=links)


def generate_spine_leaf(
    *,
    name: str = "Spine-leaf fabric",
    site: str = DEFAULT_SITE,
    spines: int = 2,
    leaves: int = 4,
    full_mesh: bool = True,
    id_prefix: str = "fabric",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Generate a two-tier spine-leaf fabric.

    With ``full_mesh=True`` (the canonical design) every leaf connects to
    every spine, giving ``spines * leaves`` links. With ``full_mesh=False``
    each leaf dual-homes to a rotating pair of adjacent spines, giving
    ``leaves * min(spines, 2)`` links; this keeps the fabric connected without
    building the complete bipartite mesh. Spines are switches with role
    ``core``; leaves are switches with role ``access``. All links are
    undirected.
    """
    if spines < 1:
        raise ValueError(f"spines must be at least 1, got {spines}")
    if leaves < 1:
        raise ValueError(f"leaves must be at least 1, got {leaves}")

    device_count = spines + leaves
    uplinks_per_leaf = spines if full_mesh else min(spines, 2)
    link_count = leaves * uplinks_per_leaf
    _check_counts(device_count, link_count, "Spine-leaf fabric")

    spine_ids = [f"{id_prefix}-spine-{index + 1:02d}" for index in range(spines)]
    leaf_ids = [f"{id_prefix}-leaf-{index + 1:02d}" for index in range(leaves)]

    devices = [
        _device(device_id, DeviceType.switch, DeviceRole.core, site)
        for device_id in spine_ids
    ]
    devices.extend(
        _device(device_id, DeviceType.switch, DeviceRole.access, site)
        for device_id in leaf_ids
    )

    links: list[Link] = []
    for leaf_index, leaf_id in enumerate(leaf_ids):
        if full_mesh:
            targets = list(enumerate(spine_ids))
        else:
            first = leaf_index % spines
            if spines == 1:
                targets = [(0, spine_ids[0])]
            else:
                targets = [
                    (first, spine_ids[first]),
                    ((first + 1) % spines, spine_ids[(first + 1) % spines]),
                ]
        for spine_index, spine_id in targets:
            links.append(
                _link(
                    f"{id_prefix}-link-leaf-{leaf_index + 1:02d}-"
                    f"spine-{spine_index + 1:02d}",
                    leaf_id,
                    spine_id,
                    link_capacity_mbps,
                    link_cost,
                )
            )

    return Topology(name=name, devices=devices, links=links)


def generate_hybrid(
    *,
    name: str = "Hybrid topology",
    site: str = DEFAULT_SITE,
    core_nodes: int = 4,
    access_per_core: int = 3,
    id_prefix: str = "hybrid",
    link_capacity_mbps: float = DEFAULT_CAPACITY_MBPS,
    link_cost: float = DEFAULT_COST,
) -> Topology:
    """Compose a core ring with one access star per ring node.

    Composition rules:

    * The core sub-topology is :func:`generate_ring` with ``core_nodes``
      routers (ids ``<prefix>-ring-node-NN``).
    * Each ring node gets a :func:`generate_star` cluster. The star hub is
      re-roled to ``distribution`` and named ``<prefix>-dist-NN``; spokes are
      hosts named ``<prefix>-edge-NN-spoke-MM``.
    * The two sub-topologies are joined by one undirected uplink from each ring
      node to its cluster hub (``<prefix>-link-uplink-NN``).

    Counts::

        devices = core_nodes * (2 + access_per_core)
        links   = core_nodes * (access_per_core + 2)

    ``core_nodes`` must be at least 3 (ring requirement) and
    ``access_per_core`` at least 1.
    """
    if core_nodes < 3:
        raise ValueError(f"core_nodes must be at least 3, got {core_nodes}")
    if access_per_core < 1:
        raise ValueError(
            f"access_per_core must be at least 1, got {access_per_core}"
        )

    device_count = core_nodes * (2 + access_per_core)
    link_count = core_nodes * (access_per_core + 2)
    _check_counts(device_count, link_count, "Hybrid topology")

    ring = generate_ring(
        name=f"{name} - core ring",
        site=site,
        node_count=core_nodes,
        id_prefix=f"{id_prefix}-ring",
        link_capacity_mbps=link_capacity_mbps,
        link_cost=link_cost,
    )

    devices: list[Device] = list(ring.devices)
    links: list[Link] = list(ring.links)

    for index, ring_node in enumerate(ring.devices):
        star = generate_star(
            name=f"{name} - access cluster {index + 1:02d}",
            site=site,
            spoke_count=access_per_core,
            hub_id=f"{id_prefix}-dist-{index + 1:02d}",
            id_prefix=f"{id_prefix}-edge-{index + 1:02d}",
            link_capacity_mbps=link_capacity_mbps,
            link_cost=link_cost,
        )
        hub = star.devices[0].model_copy(update={"role": DeviceRole.distribution})
        devices.append(hub)
        devices.extend(star.devices[1:])
        links.extend(star.links)
        links.append(
            _link(
                f"{id_prefix}-link-uplink-{index + 1:02d}",
                ring_node.id,
                hub.id,
                link_capacity_mbps,
                link_cost,
            )
        )

    return Topology(name=name, devices=devices, links=links)
