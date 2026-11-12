"""Conversion between :class:`~core.schemas.network.Topology` and NetworkX.

Directedness model
------------------
``Link.directed`` is per-link, but a NetworkX graph is either directed or
undirected. To preserve per-link semantics without lossy coercion:

* The graph returned by :func:`to_networkx` is always a
  ``networkx.MultiDiGraph`` (parallel links and link ids as edge keys).
* A directed link becomes exactly one arc ``(source, target, key=link.id)``.
* An undirected link becomes two reciprocal arcs
  ``(a, b, key=link.id)`` and ``(b, a, key=link.id)``, each tagged
  ``directed=False``. This makes reachability through an undirected link
  symmetric for graph algorithms.
* Every arc also carries ``link_id``, ``endpoints``, ``capacity_mbps``,
  ``cost``, and ``directed`` so :func:`from_networkx` can reconstruct the
  original :class:`~core.schemas.network.Link` exactly, including the
  original endpoint order.
* Graph metadata records the topology name and its overall directedness
  (``"undirected"``, ``"directed"``, or ``"mixed"``).
"""

from __future__ import annotations

import networkx as nx

from core.exceptions import SchemaError
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology

UNDIRECTED = "undirected"
DIRECTED = "directed"
MIXED = "mixed"


def topology_directedness(topology: Topology) -> str:
    """Return ``"undirected"``, ``"directed"``, or ``"mixed"`` for the links.

    An empty topology is reported as ``"undirected"`` because it has no
    directed links; this keeps the metadata total and deterministic.
    """
    flags = {link.directed for link in topology.links}
    if not flags or flags == {False}:
        return UNDIRECTED
    if flags == {True}:
        return DIRECTED
    return MIXED


def to_networkx(topology: Topology) -> nx.MultiDiGraph:
    """Convert a topology into a ``MultiDiGraph`` (see module docstring).

    Node attributes mirror :class:`~core.schemas.network.Device` fields:
    ``type``, ``site``, and ``role`` stored as their string values. The node
    key is the device id.
    """
    graph = nx.MultiDiGraph()
    graph.graph["name"] = topology.name
    graph.graph["directedness"] = topology_directedness(topology)

    for device in topology.devices:
        graph.add_node(
            device.id,
            type=device.type.value,
            site=device.site,
            role=device.role.value,
        )

    for link in topology.links:
        source, target = link.endpoints
        attributes = {
            "link_id": link.id,
            "endpoints": link.endpoints,
            "capacity_mbps": link.capacity_mbps,
            "cost": link.cost,
            "directed": link.directed,
        }
        graph.add_edge(source, target, key=link.id, **attributes)
        if not link.directed:
            graph.add_edge(target, source, key=link.id, **attributes)

    return graph


def _edge_records(graph: nx.Graph) -> list[tuple[str, str, str, dict]]:
    """Normalize graph edges to ``(source, target, fallback_key, attrs)``."""
    records: list[tuple[str, str, str, dict]] = []
    if graph.is_multigraph():
        for source, target, key, attributes in graph.edges(keys=True, data=True):
            records.append((source, target, str(key), dict(attributes)))
    else:
        for index, (source, target, attributes) in enumerate(
            graph.edges(data=True)
        ):
            link_id = attributes.get("link_id")
            fallback = str(link_id) if link_id is not None else f"link-{index}"
            records.append((source, target, fallback, dict(attributes)))
    return records


def _device_from_node(graph: nx.Graph, node_id: str) -> Device:
    attributes = graph.nodes[node_id]
    missing = [name for name in ("type", "site", "role") if name not in attributes]
    if missing:
        raise SchemaError(
            f"Node {node_id!r} is missing required attributes: {', '.join(missing)}"
        )
    try:
        return Device(
            id=str(node_id),
            type=DeviceType(attributes["type"]),
            site=str(attributes["site"]),
            role=DeviceRole(attributes["role"]),
        )
    except ValueError as error:
        raise SchemaError(f"Node {node_id!r} has invalid attributes: {error}") from error


def from_networkx(
    graph: nx.Graph,
    *,
    name: str | None = None,
) -> Topology:
    """Rebuild a :class:`~core.schemas.network.Topology` from a NetworkX graph.

    Accepts the ``MultiDiGraph`` produced by :func:`to_networkx` as well as
    plain directed/undirected graphs. When ``name`` is omitted the graph's
    ``name`` metadata is used, falling back to ``"Imported topology"``.

    For mirrored undirected links, only the first arc encountered is used to
    rebuild the link (the original endpoint order is stored on the arc). All
    links must be uniquely identified by a ``link_id`` attribute or a unique
    multigraph edge key.
    """
    topology_name = name if name is not None else graph.graph.get(
        "name", "Imported topology"
    )
    devices = [_device_from_node(graph, node) for node in graph.nodes]

    links: dict[str, Link] = {}
    for source, target, fallback_key, attributes in _edge_records(graph):
        link_id = str(attributes.get("link_id", fallback_key))
        if link_id in links:
            continue
        directed = bool(attributes.get("directed", graph.is_directed()))
        endpoints = attributes.get("endpoints", (source, target))
        if (
            not isinstance(endpoints, (tuple, list))
            or len(endpoints) != 2
        ):
            raise SchemaError(
                f"Link {link_id!r} must have exactly two endpoints, got {endpoints!r}"
            )
        try:
            links[link_id] = Link(
                id=link_id,
                endpoints=tuple(endpoints),
                capacity_mbps=attributes["capacity_mbps"],
                cost=attributes["cost"],
                directed=directed,
            )
        except KeyError as error:
            raise SchemaError(
                f"Link {link_id!r} is missing required attribute {error.args[0]!r}"
            ) from error

    return Topology(
        name=topology_name,
        devices=devices,
        links=list(links.values()),
    )
