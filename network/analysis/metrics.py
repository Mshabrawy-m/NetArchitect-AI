"""Documented structural metrics for a network topology.

Every value here is a topology-derived indicator, not a real-world
measurement. The definitions are exported in :data:`METRIC_DEFINITIONS` so the
interface can present the same wording the engine uses.
"""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx
from pydantic import BaseModel, Field

from core.schemas.network import Topology

from .graph import build_structural_graph

METRIC_DEFINITIONS: dict[str, str] = {
    "degree_centrality": (
        "Fraction of other devices directly connected to this device in the "
        "undirected physical projection. Parallel links count once and link "
        "direction is ignored."
    ),
    "betweenness_centrality": (
        "Fraction of all shortest device-to-device paths that pass through "
        "this device, using link cost as distance on the undirected "
        "projection. It describes position in the topology, not traffic "
        "volume or utilization."
    ),
    "connected_components": (
        "Maximal groups of devices reachable from each other through any "
        "link, ignoring link direction. A one-component topology is "
        "physically connected."
    ),
    "diameter": (
        "Largest shortest-path hop count inside a connected component, "
        "measured in links rather than cost. A disconnected topology has no "
        "single overall diameter; per-component values are reported and the "
        "overall value is None."
    ),
    "articulation_point": (
        "Device whose removal increases the number of connected components, "
        "meaning it separates at least two groups of devices."
    ),
    "bridge": (
        "Physical link whose removal increases the number of connected "
        "components. A pair joined by parallel links is not a bridge."
    ),
    "node_disjoint_paths": (
        "Maximum number of paths between two devices that share no "
        "intermediate device. Directed links are honored."
    ),
    "edge_disjoint_paths": (
        "Maximum number of paths between two devices that share no physical "
        "link. Directed links are honored, and an undirected link can carry "
        "at most one of the counted paths."
    ),
    "spof": (
        "Single point of failure: one device or one physical link whose "
        "individual removal increases the number of connected components."
    ),
}


class CentralityMetric(BaseModel):
    """Centrality values for one device."""

    device_id: str
    degree: int = Field(ge=0, description="Number of distinct adjacent devices.")
    degree_centrality: float = Field(
        ge=0.0,
        le=1.0,
        description="Degree divided by the number of other devices.",
    )
    betweenness_centrality: float = Field(
        ge=0.0,
        le=1.0,
        description="Normalized weighted betweenness on the undirected projection.",
    )


class CentralityReport(BaseModel):
    """Centrality results, ordered by device id."""

    metrics: list[CentralityMetric] = Field(default_factory=list)


class ComponentAnalysis(BaseModel):
    """Connected-component summary of the physical projection."""

    components: list[list[str]] = Field(default_factory=list)
    component_count: int = Field(default=0, ge=0)
    largest_component_size: int = Field(default=0, ge=0)
    is_connected: bool = False
    isolated_device_ids: list[str] = Field(default_factory=list)


class ComponentDiameter(BaseModel):
    """Hop-based diameter of one connected component."""

    device_ids: list[str] = Field(default_factory=list)
    diameter: int = Field(ge=0)


class DiameterReport(BaseModel):
    """Overall and per-component hop diameter.

    ``overall_diameter`` is ``None`` when the topology is disconnected or
    empty. A connected single device has diameter 0.
    """

    overall_diameter: int | None = Field(default=None, ge=0)
    per_component: list[ComponentDiameter] = Field(default_factory=list)


class CriticalNode(BaseModel):
    """A device whose removal increases the component count."""

    device_id: str
    components_after_removal: int = Field(ge=0)
    isolated_device_ids: list[str] = Field(default_factory=list)


class CriticalNodesReport(BaseModel):
    """Articulation points of the physical projection."""

    nodes: list[CriticalNode] = Field(default_factory=list)


class CriticalLink(BaseModel):
    """A physical link whose removal increases the component count."""

    link_id: str
    endpoints: list[str] = Field(default_factory=list)
    components_after_removal: int = Field(ge=0)
    isolated_device_ids: list[str] = Field(default_factory=list)


class CriticalLinksReport(BaseModel):
    """Bridges of the physical projection."""

    links: list[CriticalLink] = Field(default_factory=list)


def _removal_impact(
    graph: nx.Graph,
    *,
    node: str | None = None,
    edge: tuple[str, str] | None = None,
) -> tuple[int, list[str]]:
    """Return component count and newly isolated devices after one removal."""
    remaining = graph.copy()
    if node is not None:
        remaining.remove_node(node)
    elif edge is not None:
        remaining.remove_edge(*edge)
    count = (
        nx.number_connected_components(remaining)
        if remaining.number_of_nodes()
        else 0
    )
    isolated = sorted(
        device_id
        for device_id in remaining.nodes
        if remaining.degree[device_id] == 0 and graph.degree[device_id] > 0
    )
    return count, isolated


def _centrality_from_graph(graph: nx.Graph) -> CentralityReport:
    degree = nx.degree_centrality(graph) if graph.number_of_nodes() else {}
    betweenness = (
        nx.betweenness_centrality(graph, weight="cost", normalized=True)
        if graph.number_of_nodes()
        else {}
    )
    return CentralityReport(
        metrics=[
            CentralityMetric(
                device_id=device_id,
                degree=int(graph.degree[device_id]),
                degree_centrality=float(degree.get(device_id, 0.0)),
                betweenness_centrality=float(betweenness.get(device_id, 0.0)),
            )
            for device_id in sorted(graph.nodes)
        ]
    )


def _components_from_graph(graph: nx.Graph) -> ComponentAnalysis:
    components = [sorted(component) for component in nx.connected_components(graph)]
    components.sort(key=lambda component: component[0] if component else "")
    isolated = sorted(
        device_id
        for device_id, degree in graph.degree()
        if degree == 0
    )
    return ComponentAnalysis(
        components=components,
        component_count=len(components),
        largest_component_size=max((len(item) for item in components), default=0),
        is_connected=graph.number_of_nodes() > 0 and len(components) == 1,
        isolated_device_ids=isolated,
    )


def _diameter_from_graph(graph: nx.Graph) -> DiameterReport:
    per_component: list[ComponentDiameter] = []
    for component in nx.connected_components(graph):
        device_ids = sorted(component)
        diameter = 0 if len(device_ids) == 1 else nx.diameter(
            graph.subgraph(device_ids)
        )
        per_component.append(
            ComponentDiameter(device_ids=device_ids, diameter=int(diameter))
        )
    per_component.sort(key=lambda item: item.device_ids[0] if item.device_ids else "")
    overall = (
        per_component[0].diameter if len(per_component) == 1 else None
    )
    return DiameterReport(
        overall_diameter=overall,
        per_component=per_component,
    )


def _critical_nodes_from_graph(graph: nx.Graph) -> CriticalNodesReport:
    nodes: list[CriticalNode] = []
    for device_id in sorted(nx.articulation_points(graph)):
        components, isolated = _removal_impact(graph, node=device_id)
        nodes.append(
            CriticalNode(
                device_id=device_id,
                components_after_removal=components,
                isolated_device_ids=isolated,
            )
        )
    return CriticalNodesReport(nodes=nodes)


def _critical_links_from_graph(graph: nx.Graph) -> CriticalLinksReport:
    links: list[CriticalLink] = []
    bridge_pairs = sorted(
        nx.bridges(graph),
        key=lambda pair: tuple(sorted(pair)),
    )
    for first, second in bridge_pairs:
        link_ids = graph[first][second]["link_ids"]
        # Parallel links provide an alternate path, so only a single physical
        # link between the pair is a single-link failure point.
        if len(link_ids) != 1:
            continue
        components, isolated = _removal_impact(
            graph,
            edge=(first, second),
        )
        links.append(
            CriticalLink(
                link_id=str(link_ids[0]),
                endpoints=sorted([first, second]),
                components_after_removal=components,
                isolated_device_ids=isolated,
            )
        )
    links.sort(key=lambda link: link.link_id)
    return CriticalLinksReport(links=links)


def centrality_metrics(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> CentralityReport:
    """Return degree and weighted betweenness centrality per device."""
    return _centrality_from_graph(
        build_structural_graph(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
    )


def component_analysis(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> ComponentAnalysis:
    """Return the connected components of the physical projection."""
    return _components_from_graph(
        build_structural_graph(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
    )


def diameter_analysis(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> DiameterReport:
    """Return hop-based diameters, per component and overall."""
    return _diameter_from_graph(
        build_structural_graph(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
    )


def critical_nodes(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> CriticalNodesReport:
    """Return articulation points and their removal impact."""
    return _critical_nodes_from_graph(
        build_structural_graph(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
    )


def critical_links(
    topology: Topology,
    *,
    failed_devices: Iterable[str] = (),
    failed_links: Iterable[str] = (),
) -> CriticalLinksReport:
    """Return bridges and their removal impact.

    Parallel physical links between the same pair are not reported as single
    link failure points.
    """
    return _critical_links_from_graph(
        build_structural_graph(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
    )
