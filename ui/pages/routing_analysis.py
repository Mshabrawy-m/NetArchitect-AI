"""Routing analysis page.

Presentation only: path search, alternatives, routing tables, reachability,
and failure handling are delegated to :mod:`network.routing`. The page reads
the one topology stored in ``st.session_state["topology"]`` and never keeps a
second copy of graph state.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.limits import MAX_ALTERNATIVE_PATHS
from core.exceptions import NetArchitectError
from core.schemas.network import Topology
from network.routing import (
    AlternativePaths,
    ReachabilityMatrix,
    RoutePath,
    RoutingTable,
    alternative_paths,
    alternative_rows,
    path_rows,
    reachability_matrix,
    reachability_rows,
    routing_table,
    routing_table_rows,
    shortest_path,
)
from network.topology import to_networkx
from ui.components import csv_bytes, format_error

TOPOLOGY_KEY = "topology"

ROLE_COLORS = {
    "core": "#1f3a5f",
    "distribution": "#2f6690",
    "aggregation": "#3d7ea6",
    "access": "#7fa8c9",
    "border": "#6b4c3b",
    "edge": "#4f7cac",
    "wan": "#6b4c3b",
    "dmz": "#8a6d3b",
}


def _current_topology() -> Topology | None:
    topology = st.session_state.get(TOPOLOGY_KEY)
    return topology if isinstance(topology, Topology) else None


def _render_empty_state() -> None:
    st.title("Routing Analysis")
    st.info(
        "No topology is loaded. Open the Topology Editor from the sidebar to "
        "create, generate, or import a topology, then return to this page."
    )
    st.caption(
        "Routing calculations are deterministic and stateless: they read the "
        "stored topology and return derived results without modifying it."
    )


def _select(
    label: str,
    options: list[str],
    key: str,
    default_index: int = 0,
) -> str:
    if key not in st.session_state or st.session_state[key] not in options:
        st.session_state[key] = options[default_index]
    return st.selectbox(label, options=options, key=key)


def _multi_select(
    label: str,
    options: list[str],
    key: str,
    help_text: str,
) -> list[str]:
    current = st.session_state.get(key, [])
    valid = [value for value in current if value in options]
    if valid != current:
        st.session_state[key] = valid
    return st.multiselect(label, options=options, key=key, help=help_text)


def _reachable_pairs(matrix: ReachabilityMatrix) -> int:
    count = len(matrix.device_ids)
    return count * (count - 1) - matrix.unreachable_pairs


def _comparison_frame(
    baseline: ReachabilityMatrix,
    after: ReachabilityMatrix,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": "Baseline",
                "devices": len(baseline.device_ids),
                "reachable_ordered_pairs": _reachable_pairs(baseline),
                "unreachable_ordered_pairs": baseline.unreachable_pairs,
                "removed_devices": len(baseline.excluded_device_ids),
            },
            {
                "scenario": "After selected failures",
                "devices": len(after.device_ids),
                "reachable_ordered_pairs": _reachable_pairs(after),
                "unreachable_ordered_pairs": after.unreachable_pairs,
                "removed_devices": len(after.excluded_device_ids),
            },
        ]
    )


def _routing_comparison(
    baseline: RoutingTable,
    after: RoutingTable,
) -> pd.DataFrame:
    before_entries = {entry.destination: entry for entry in baseline.entries}
    after_entries = {entry.destination: entry for entry in after.entries}
    rows: list[dict[str, object]] = []
    for destination in sorted(set(before_entries) | set(after_entries)):
        before = before_entries.get(destination)
        current = after_entries.get(destination)
        if current is None:
            status = "unreachable"
        elif before is None:
            status = "new"
        elif (before.next_hop, before.total_cost) != (
            current.next_hop,
            current.total_cost,
        ):
            status = "rerouted"
        else:
            status = "unchanged"
        rows.append(
            {
                "destination": destination,
                "next_hop_before": before.next_hop if before else "",
                "next_hop_after": current.next_hop if current else "",
                "cost_before": before.total_cost if before else None,
                "cost_after": current.total_cost if current else None,
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def _build_figure(
    topology: Topology,
    *,
    baseline_path: RoutePath | None,
    after_path: RoutePath | None,
    failed_devices: set[str],
    failed_links: set[str],
) -> go.Figure | None:
    engine_graph = to_networkx(topology)
    if engine_graph.number_of_nodes() == 0:
        return None

    layout_graph = nx.Graph()
    for node in engine_graph.nodes:
        layout_graph.add_node(node)

    links: list[tuple[str, str, bool, str]] = []
    seen_links: set[str] = set()
    for source, target, attributes in engine_graph.edges(data=True):
        link_id = str(attributes["link_id"])
        if link_id in seen_links:
            continue
        seen_links.add(link_id)
        links.append(
            (source, target, bool(attributes["directed"]), link_id)
        )
        if not layout_graph.has_edge(source, target):
            layout_graph.add_edge(source, target)

    positions = nx.spring_layout(layout_graph, seed=42, iterations=60)
    figure = go.Figure()

    for directed, label, dash, color in (
        (False, "Undirected link", "solid", "#9aa7b4"),
        (True, "Directed link", "dash", "#a15c2f"),
    ):
        x_values: list[float | None] = []
        y_values: list[float | None] = []
        for source, target, is_directed, link_id in links:
            if is_directed is not directed or link_id in failed_links:
                continue
            source_x, source_y = positions[source]
            target_x, target_y = positions[target]
            x_values.extend([source_x, target_x, None])
            y_values.extend([source_y, target_y, None])
        if x_values:
            figure.add_trace(
                go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode="lines",
                    line={"color": color, "width": 1.4, "dash": dash},
                    hoverinfo="skip",
                    name=label,
                )
            )

    failed_x: list[float | None] = []
    failed_y: list[float | None] = []
    for source, target, _, link_id in links:
        if link_id not in failed_links:
            continue
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        failed_x.extend([source_x, target_x, None])
        failed_y.extend([source_y, target_y, None])
    if failed_x:
        figure.add_trace(
            go.Scatter(
                x=failed_x,
                y=failed_y,
                mode="lines",
                line={"color": "#b23c3c", "width": 2.4, "dash": "dot"},
                hoverinfo="skip",
                name="Failed link",
            )
        )

    highlights: list[tuple[str, RoutePath, str, str]] = []
    if after_path is not None and after_path.reachable:
        highlights.append(("Shortest path", after_path, "#1f6f8b", "solid"))
    if (
        baseline_path is not None
        and baseline_path.reachable
        and (
            after_path is None
            or baseline_path.device_ids != after_path.device_ids
        )
    ):
        highlights.append(("Baseline path", baseline_path, "#b07a3a", "dash"))
    for label, path, color, dash in highlights:
        x_values = []
        y_values = []
        for hop in path.hops:
            source_x, source_y = positions[hop.source]
            target_x, target_y = positions[hop.target]
            x_values.extend([source_x, target_x, None])
            y_values.extend([source_y, target_y, None])
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="lines",
                line={"color": color, "width": 4.0, "dash": dash},
                hoverinfo="skip",
                name=label,
            )
        )

    surviving_nodes = [
        node for node in engine_graph.nodes if node not in failed_devices
    ]
    roles = sorted({engine_graph.nodes[node]["role"] for node in surviving_nodes})
    show_labels = engine_graph.number_of_nodes() <= 30
    for role in roles:
        nodes = [
            node
            for node in surviving_nodes
            if engine_graph.nodes[node]["role"] == role
        ]
        figure.add_trace(
            go.Scatter(
                x=[positions[node][0] for node in nodes],
                y=[positions[node][1] for node in nodes],
                mode="markers+text" if show_labels else "markers",
                text=nodes if show_labels else None,
                textposition="top center",
                textfont={"size": 10, "color": "#33414f"},
                marker={
                    "size": 18,
                    "color": ROLE_COLORS.get(role, "#7fa8c9"),
                    "line": {"width": 1, "color": "#ffffff"},
                },
                customdata=[
                    [
                        node,
                        engine_graph.nodes[node]["type"],
                        engine_graph.nodes[node]["site"],
                        engine_graph.nodes[node]["role"],
                    ]
                    for node in nodes
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>Type: %{customdata[1]}"
                    "<br>Site: %{customdata[2]}<br>Role: %{customdata[3]}"
                    "<extra></extra>"
                ),
                name=role.replace("_", " ").capitalize(),
            )
        )

    failed_nodes = sorted(failed_devices & set(engine_graph.nodes))
    if failed_nodes:
        figure.add_trace(
            go.Scatter(
                x=[positions[node][0] for node in failed_nodes],
                y=[positions[node][1] for node in failed_nodes],
                mode="markers+text" if show_labels else "markers",
                text=failed_nodes if show_labels else None,
                textposition="top center",
                textfont={"size": 10, "color": "#7a2f2f"},
                marker={
                    "size": 14,
                    "color": "#b23c3c",
                    "symbol": "x",
                    "line": {"width": 1, "color": "#7a2f2f"},
                },
                hovertemplate="<b>%{text}</b><br>Failed device<extra></extra>",
                name="Failed device",
            )
        )

    figure.update_layout(
        height=520,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11},
        },
        hovermode="closest",
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def _render_path(
    *,
    baseline_path: RoutePath,
    after_path: RoutePath,
    failures_active: bool,
    figure: go.Figure | None,
) -> None:
    st.subheader("Shortest path")
    columns = st.columns(4)
    columns[0].metric(
        "Cost",
        f"{after_path.total_cost:.2f}" if after_path.reachable else "unreachable",
    )
    columns[1].metric(
        "Hops",
        str(after_path.hop_count) if after_path.reachable else "-",
    )
    columns[2].metric(
        "Baseline cost",
        f"{baseline_path.total_cost:.2f}"
        if baseline_path.reachable
        else "unreachable",
    )
    columns[3].metric(
        "Status",
        "reachable" if after_path.reachable else "unreachable",
    )

    left, right = st.columns([1.1, 1])
    with left:
        if not after_path.reachable:
            st.warning(after_path.reason, title="No path")
        else:
            if (
                failures_active
                and baseline_path.reachable
                and baseline_path.device_ids != after_path.device_ids
            ):
                st.info(
                    "The selected failures change the forwarding path; the "
                    "previous path is shown dashed in the topology view."
                )
            frame = pd.DataFrame(path_rows(after_path))
            st.dataframe(frame, hide_index=True, width="stretch")
            st.download_button(
                "Download path as CSV",
                data=csv_bytes(frame),
                file_name="routing-path.csv",
                mime="text/csv",
                key="routing_path_download",
            )
    with right, st.container(border=True):
        st.caption(
            "Deterministic spring layout (seed 42). Highlighted links show "
            "the current shortest path; failed entities are drawn in red."
        )
        if figure is None:
            st.info("The topology has no devices to display.")
        else:
            st.plotly_chart(
                figure,
                width="stretch",
                config={"displayModeBar": False},
                alt="Topology with the selected shortest path highlighted",
            )


def _render_alternatives(
    alternatives: AlternativePaths,
    *,
    failures_active: bool,
) -> None:
    st.subheader("Alternative paths")
    st.caption(
        "Simple paths ordered by total cost, then by device sequence. The "
        "number returned is bounded by the configured limit of "
        f"{MAX_ALTERNATIVE_PATHS}."
    )
    if failures_active:
        st.caption("Alternatives are recomputed with the selected failures applied.")
    if not alternatives.paths:
        st.info(alternatives.reason or "No alternative path is available.")
        return
    frame = pd.DataFrame(alternative_rows(alternatives))
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download alternatives as CSV",
        data=csv_bytes(frame),
        file_name="routing-alternatives.csv",
        mime="text/csv",
        key="routing_alternatives_download",
    )


def _render_routing_table(
    baseline: RoutingTable,
    after: RoutingTable,
    *,
    failures_active: bool,
) -> None:
    st.subheader("Routing table")
    if after.reason:
        st.warning(after.reason)
    if failures_active:
        st.caption(
            "Next hop and total cost before and after the selected failures. "
            "Blank next hops mean the destination is no longer reachable."
        )
        frame = _routing_comparison(baseline, after)
        st.dataframe(frame, hide_index=True, width="stretch")
        st.download_button(
            "Download routing comparison as CSV",
            data=csv_bytes(frame),
            file_name="routing-comparison.csv",
            mime="text/csv",
            key="routing_comparison_download",
        )
    else:
        if not after.entries:
            st.info("This source has no reachable destinations.")
            return
        frame = pd.DataFrame(routing_table_rows(after))
        st.dataframe(frame, hide_index=True, width="stretch")
        st.download_button(
            "Download routing table as CSV",
            data=csv_bytes(frame),
            file_name="routing-table.csv",
            mime="text/csv",
            key="routing_table_download",
        )


def _render_matrix(
    matrix: ReachabilityMatrix,
    *,
    label: str,
    key: str,
) -> None:
    if not matrix.device_ids:
        st.info("No devices remain for a reachability matrix.")
        return
    frame = pd.DataFrame(reachability_rows(matrix))
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        f"Download {label.lower()} matrix as CSV",
        data=csv_bytes(frame),
        file_name=f"routing-reachability-{key}.csv",
        mime="text/csv",
        key=f"routing_reachability_{key}_download",
    )


def _render_reachability(
    baseline: ReachabilityMatrix,
    after: ReachabilityMatrix,
    *,
    failures_active: bool,
) -> None:
    st.subheader("Reachability")
    st.caption(
        "The matrix is directed: rows are sources and columns are destinations. "
        "The diagonal is always reachable."
    )
    st.dataframe(
        _comparison_frame(baseline, after),
        hide_index=True,
        width="stretch",
    )
    if failures_active:
        after_tab, baseline_tab = st.tabs(["After selected failures", "Baseline"])
        with after_tab:
            _render_matrix(after, label="After-failure", key="after")
        with baseline_tab:
            _render_matrix(baseline, label="Baseline", key="baseline")
    else:
        (current_tab,) = st.tabs(["Reachability matrix"])
        with current_tab:
            _render_matrix(after, label="Reachability", key="current")


def render() -> None:
    """Render the routing analysis page."""
    topology = _current_topology()
    if topology is None or not topology.devices:
        _render_empty_state()
        return

    device_ids = sorted(device.id for device in topology.devices)
    link_ids = sorted(link.id for link in topology.links)

    st.title("Routing Analysis")
    st.caption(
        "Deterministic shortest-path routing over the stored topology. Link "
        "cost is the only path weight; link capacity is metadata and does not "
        "affect selection. Ties resolve to the lexicographically smallest "
        "device sequence."
    )

    controls = st.columns(3)
    with controls[0]:
        source = _select("Source device", device_ids, "routing_source")
    destination_options = (
        device_ids
        if len(device_ids) == 1
        else [device_id for device_id in device_ids if device_id != source]
    )
    with controls[1]:
        destination = _select(
            "Destination device",
            destination_options,
            "routing_destination",
        )
    with controls[2]:
        k = st.slider(
            "Alternative paths (k)",
            min_value=1,
            max_value=MAX_ALTERNATIVE_PATHS,
            value=min(3, MAX_ALTERNATIVE_PATHS),
            key="routing_k",
        )

    with st.expander("Failure scenario", expanded=False):
        profile_columns = st.columns(2)
        with profile_columns[0]:
            failed_devices = _multi_select(
                "Failed devices",
                device_ids,
                "routing_failed_devices",
                "Select devices to remove from the derived routing graph.",
            )
        with profile_columns[1]:
            failed_links = _multi_select(
                "Failed links",
                link_ids,
                "routing_failed_links",
                "Select links to remove from the derived routing graph.",
            )
        st.caption(
            "Failures are applied to a derived graph only. The stored topology "
            "is never modified."
        )

    failures_active = bool(failed_devices or failed_links)

    try:
        baseline_path = shortest_path(topology, source, destination)
        after_path = shortest_path(
            topology,
            source,
            destination,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
        alternatives = alternative_paths(
            topology,
            source,
            destination,
            k=k,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
        baseline_table = routing_table(topology, source)
        after_table = routing_table(
            topology,
            source,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
        baseline_matrix = reachability_matrix(topology)
        after_matrix = reachability_matrix(
            topology,
            failed_devices=failed_devices,
            failed_links=failed_links,
        )
    except (NetArchitectError, ValueError) as error:
        st.error(format_error(error), title="Routing analysis failed")
        return

    figure = _build_figure(
        topology,
        baseline_path=baseline_path,
        after_path=after_path,
        failed_devices=set(failed_devices),
        failed_links=set(failed_links),
    )
    _render_path(
        baseline_path=baseline_path,
        after_path=after_path,
        failures_active=failures_active,
        figure=figure,
    )
    _render_alternatives(alternatives, failures_active=failures_active)
    _render_routing_table(
        baseline_table,
        after_table,
        failures_active=failures_active,
    )
    _render_reachability(
        baseline_matrix,
        after_matrix,
        failures_active=failures_active,
    )
    st.caption(
        "Reachability and routing results are structural. They do not model "
        "traffic volume, queueing, or hardware forwarding limits."
    )
