"""Network analytics page.

Presentation only: centrality, connectivity, critical entities, single points
of failure, and redundancy are delegated to :mod:`network.analysis`. The page
reads the one topology stored in ``st.session_state["topology"]`` and keeps no
second copy of graph state.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.exceptions import NetArchitectError
from core.schemas.network import Topology
from network.analysis import (
    METRIC_DEFINITIONS,
    AnalysisReport,
    analyze_topology,
    centrality_rows,
    component_rows,
    critical_link_rows,
    critical_node_rows,
    diameter_rows,
    redundancy,
    redundancy_rows,
    spof_rows,
)
from ui.components import (
    csv_bytes,
    findings_frame,
    format_error,
    render_findings,
)

TOPOLOGY_KEY = "topology"


def _current_topology() -> Topology | None:
    topology = st.session_state.get(TOPOLOGY_KEY)
    return topology if isinstance(topology, Topology) else None


def _render_empty_state() -> None:
    st.title("Network Analytics")
    st.info(
        "No topology is loaded. Open the Topology Editor from the sidebar to "
        "create, generate, or import a topology, then return to this page."
    )
    st.caption(
        "Analytics are derived from the stored topology on each rerun; no "
        "graph snapshot is cached by this page."
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


def _download(frame: pd.DataFrame, label: str, file_name: str, key: str) -> None:
    st.download_button(
        f"Download {label} as CSV",
        data=csv_bytes(frame),
        file_name=file_name,
        mime="text/csv",
        key=key,
    )


def _render_centrality(report: AnalysisReport) -> None:
    st.subheader("Centrality")
    st.caption(
        METRIC_DEFINITIONS["degree_centrality"]
        + " "
        + METRIC_DEFINITIONS["betweenness_centrality"]
    )
    frame = pd.DataFrame(centrality_rows(report.centrality))
    if frame.empty:
        st.info("The topology has no devices to analyze.")
        return

    left, right = st.columns(2)
    with left:
        st.caption("Degree centrality")
        st.bar_chart(
            frame.set_index("device_id")["degree_centrality"],
            horizontal=True,
            height=max(220, 24 * len(frame)),
        )
    with right:
        st.caption("Betweenness centrality (weighted by link cost)")
        st.bar_chart(
            frame.set_index("device_id")["betweenness_centrality"],
            horizontal=True,
            height=max(220, 24 * len(frame)),
        )

    st.dataframe(frame, hide_index=True, width="stretch")
    _download(frame, "centrality", "network-centrality.csv", "analytics_centrality")


def _render_connectivity(report: AnalysisReport) -> None:
    st.subheader("Connectivity and diameter")
    if not report.components.is_connected:
        st.warning(
            f"The physical topology has {report.components.component_count} "
            f"connected components. Per-component diameters are reported; an "
            f"overall diameter is undefined."
        )
    left, right = st.columns(2)
    with left:
        st.caption(METRIC_DEFINITIONS["connected_components"])
        component_frame = pd.DataFrame(component_rows(report.components))
        if component_frame.empty:
            st.info("The topology has no devices.")
        else:
            st.dataframe(component_frame, hide_index=True, width="stretch")
            _download(
                component_frame,
                "components",
                "network-components.csv",
                "analytics_components",
            )
    with right:
        st.caption(METRIC_DEFINITIONS["diameter"])
        diameter_frame = pd.DataFrame(diameter_rows(report.diameter))
        if diameter_frame.empty:
            st.info("No component diameter is available.")
        else:
            st.dataframe(diameter_frame, hide_index=True, width="stretch")
            _download(
                diameter_frame,
                "diameters",
                "network-diameters.csv",
                "analytics_diameters",
            )


def _render_critical_entities(report: AnalysisReport) -> None:
    st.subheader("Critical devices and links")
    left, right = st.columns(2)
    with left:
        st.caption(METRIC_DEFINITIONS["articulation_point"])
        node_frame = pd.DataFrame(critical_node_rows(report.critical_nodes))
        if node_frame.empty:
            st.info("No articulation points detected.")
        else:
            st.dataframe(node_frame, hide_index=True, width="stretch")
            _download(
                node_frame,
                "critical devices",
                "network-critical-devices.csv",
                "analytics_critical_devices",
            )
    with right:
        st.caption(METRIC_DEFINITIONS["bridge"])
        link_frame = pd.DataFrame(critical_link_rows(report.critical_links))
        if link_frame.empty:
            st.info("No bridges detected.")
        else:
            st.dataframe(link_frame, hide_index=True, width="stretch")
            _download(
                link_frame,
                "critical links",
                "network-critical-links.csv",
                "analytics_critical_links",
            )


def _render_spof(report: AnalysisReport) -> None:
    st.subheader("Single points of failure")
    st.caption(METRIC_DEFINITIONS["spof"])
    frame = pd.DataFrame(spof_rows(report.spof))
    if frame.empty:
        st.info("No single device or link removal splits the topology.")
    else:
        st.dataframe(frame, hide_index=True, width="stretch")
        _download(
            frame,
            "SPOF summary",
            "network-spof.csv",
            "analytics_spof",
        )

    render_findings(
        report.findings,
        "No single points of failure or connectivity warnings detected.",
    )
    if report.findings:
        _download(
            findings_frame(report.findings),
            "findings",
            "network-findings.csv",
            "analytics_findings",
        )


def _render_redundancy(topology: Topology) -> None:
    st.subheader("Path redundancy")
    st.caption(
        METRIC_DEFINITIONS["node_disjoint_paths"]
        + " "
        + METRIC_DEFINITIONS["edge_disjoint_paths"]
    )
    device_ids = sorted(device.id for device in topology.devices)
    if not device_ids:
        st.info("The topology has no devices.")
        return

    left, right = st.columns(2)
    with left:
        source = _select("Redundancy source", device_ids, "analytics_source")
    destination_options = (
        device_ids
        if len(device_ids) == 1
        else [device_id for device_id in device_ids if device_id != source]
    )
    with right:
        destination = _select(
            "Redundancy destination",
            destination_options,
            "analytics_destination",
        )

    try:
        result = redundancy(topology, source, destination)
    except (NetArchitectError, ValueError) as error:
        st.error(format_error(error), title="Redundancy analysis failed")
        return

    if not result.reachable:
        st.warning(result.reason or "No directed path exists between the pair.")
        return
    if source == destination:
        st.info(result.reason)
        return

    columns = st.columns(2)
    columns[0].metric("Node-disjoint paths", result.node_disjoint_paths)
    columns[1].metric("Edge-disjoint paths", result.edge_disjoint_paths)
    frame = pd.DataFrame(redundancy_rows(result))
    st.dataframe(frame, hide_index=True, width="stretch")
    _download(
        frame,
        "redundancy",
        "network-redundancy.csv",
        "analytics_redundancy",
    )


def _render_definitions() -> None:
    with st.expander("Metric definitions"):
        for name, text in METRIC_DEFINITIONS.items():
            st.markdown(f"**{name.replace('_', ' ').capitalize()}.** {text}")
        st.caption(
            "All values are structural indicators for design review, not "
            "measurements of live bandwidth, latency, utilization, or "
            "availability."
        )


def render() -> None:
    """Render the network analytics page."""
    topology = _current_topology()
    if topology is None or not topology.devices:
        _render_empty_state()
        return

    try:
        report = analyze_topology(topology)
    except (NetArchitectError, ValueError) as error:
        st.title("Network Analytics")
        st.error(format_error(error), title="Analysis failed")
        return

    st.title("Network Analytics")
    st.caption(
        "Structural indicators derived from the stored topology. They describe "
        "design position and connectivity, not measured traffic or hardware "
        "performance."
    )

    columns = st.columns(5)
    columns[0].metric("Devices", len(topology.devices))
    columns[1].metric("Links", len(topology.links))
    columns[2].metric("Components", report.components.component_count)
    columns[3].metric(
        "Diameter (hops)",
        str(report.diameter.overall_diameter)
        if report.diameter.overall_diameter is not None
        else "per component",
    )
    columns[4].metric("SPOF entities", len(report.spof.entries))

    _render_centrality(report)
    _render_connectivity(report)
    _render_critical_entities(report)
    _render_spof(report)
    _render_redundancy(topology)
    _render_definitions()
