"""Topology editor page.

Presentation only: every topology change is delegated to the deterministic
services in :mod:`network.topology`. The page reads and writes the baseline
topology through :mod:`ui.state`, which keeps it inside the one digital-twin
session object. Tables and figures are derived on each rerun and never kept as
a second copy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

from config.limits import MAX_NODES
from core.exceptions import NetArchitectError
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from digital_twin import validate_twin
from network.topology import (
    add_device,
    add_link,
    analyze_connectivity,
    from_json,
    generate_hierarchical_campus,
    generate_hybrid,
    generate_mesh,
    generate_ring,
    generate_spine_leaf,
    generate_star,
    generate_tree,
    remove_device,
    remove_link,
    to_json,
    to_networkx,
    update_device,
    update_link,
)
from ui import state
from ui.components import findings_frame

DEVICE_COLUMNS = ("id", "type", "site", "role")
LINK_COLUMNS = ("id", "endpoint_a", "endpoint_b", "capacity_mbps", "cost", "directed")

GENERATOR_FAMILIES = (
    "Star",
    "Ring",
    "Full mesh",
    "Tree",
    "Hierarchical campus",
    "Spine-leaf",
    "Hybrid",
)

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

LINK_STYLES = (
    (False, "Undirected link", "solid", "#9aa7b4"),
    (True, "Directed link", "dash", "#a15c2f"),
)


def _flash(level: str, message: str) -> None:
    """Queue a one-shot message to display after the next rerun."""
    messages = state.session_get(state.FLASH_KEY, [])
    state.session_set(state.FLASH_KEY, [*messages, (level, message)])


def _render_flash() -> None:
    for level, message in state.session_pop(state.FLASH_KEY, []):
        getattr(st, level)(message)


def _format_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        parts = [
            f"{'.'.join(str(item) for item in detail['loc'])}: {detail['msg']}"
            for detail in error.errors()[:3]
        ]
        return "; ".join(parts)
    return str(error)


def _current_topology() -> Topology | None:
    return state.get_topology()


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def _number(value: object, label: str, entity: str) -> float:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError(f"{entity}: {label} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{entity}: {label} must be a number.") from error
    if number <= 0:
        raise ValueError(f"{entity}: {label} must be greater than zero.")
    return number


def _id_was_edited(editor_key: str, original_count: int) -> bool:
    """Detect an id edit on a row that already existed when the table opened."""
    editor_state = st.session_state.get(editor_key)
    if not isinstance(editor_state, Mapping):
        return False
    for row, changes in editor_state.get("edited_rows", {}).items():
        try:
            row_index = int(row)
        except (TypeError, ValueError):
            continue
        if row_index < original_count and "id" in changes:
            return True
    return False


def _render_generator_controls(family: str) -> None:
    """Render the parameter widgets for ``family``."""
    if family == "Star":
        st.number_input(
            "Spokes",
            min_value=1,
            max_value=MAX_NODES,
            value=6,
            step=1,
            key="gen_star_spokes",
        )
    elif family == "Ring":
        st.number_input(
            "Ring nodes",
            min_value=3,
            max_value=MAX_NODES,
            value=5,
            step=1,
            key="gen_ring_nodes",
        )
    elif family == "Full mesh":
        st.number_input(
            "Mesh nodes",
            min_value=2,
            max_value=MAX_NODES,
            value=5,
            step=1,
            key="gen_mesh_nodes",
        )
    elif family == "Tree":
        st.number_input(
            "Depth",
            min_value=0,
            max_value=10,
            value=2,
            step=1,
            key="gen_tree_depth",
        )
        st.number_input(
            "Branching factor",
            min_value=1,
            max_value=10,
            value=2,
            step=1,
            key="gen_tree_branching",
        )
    elif family == "Hierarchical campus":
        st.number_input(
            "Distribution switches",
            min_value=1,
            max_value=32,
            value=2,
            step=1,
            key="gen_campus_distributions",
        )
        st.number_input(
            "Access switches per distribution",
            min_value=1,
            max_value=64,
            value=4,
            step=1,
            key="gen_campus_access",
        )
        st.checkbox(
            "Redundant uplinks (dual-homing)",
            value=False,
            key="gen_campus_redundant",
        )
    elif family == "Spine-leaf":
        st.number_input(
            "Spines",
            min_value=1,
            max_value=32,
            value=2,
            step=1,
            key="gen_fabric_spines",
        )
        st.number_input(
            "Leaves",
            min_value=1,
            max_value=128,
            value=4,
            step=1,
            key="gen_fabric_leaves",
        )
        st.checkbox(
            "Full leaf-spine mesh",
            value=True,
            key="gen_fabric_full_mesh",
        )
    else:
        st.number_input(
            "Core ring nodes",
            min_value=3,
            max_value=32,
            value=4,
            step=1,
            key="gen_hybrid_core_nodes",
        )
        st.number_input(
            "Access hosts per core node",
            min_value=1,
            max_value=32,
            value=3,
            step=1,
            key="gen_hybrid_access",
        )


def _generate_from_widgets(family: str, site: str) -> Topology:
    """Build a topology from the rendered generator widget values."""
    if family == "Star":
        return generate_star(
            site=site, spoke_count=st.session_state["gen_star_spokes"]
        )
    if family == "Ring":
        return generate_ring(site=site, node_count=st.session_state["gen_ring_nodes"])
    if family == "Full mesh":
        return generate_mesh(
            site=site, node_count=st.session_state["gen_mesh_nodes"]
        )
    if family == "Tree":
        return generate_tree(
            site=site,
            depth=st.session_state["gen_tree_depth"],
            branching_factor=st.session_state["gen_tree_branching"],
        )
    if family == "Hierarchical campus":
        return generate_hierarchical_campus(
            site=site,
            distribution_count=st.session_state["gen_campus_distributions"],
            access_per_distribution=st.session_state["gen_campus_access"],
            redundant_uplinks=st.session_state["gen_campus_redundant"],
        )
    if family == "Spine-leaf":
        return generate_spine_leaf(
            site=site,
            spines=st.session_state["gen_fabric_spines"],
            leaves=st.session_state["gen_fabric_leaves"],
            full_mesh=st.session_state["gen_fabric_full_mesh"],
        )
    return generate_hybrid(
        site=site,
        core_nodes=st.session_state["gen_hybrid_core_nodes"],
        access_per_core=st.session_state["gen_hybrid_access"],
    )


def _render_generator() -> None:
    with st.container(border=True):
        st.subheader("Generate topology")
        st.caption(
            "Every generator is deterministic: the same parameters produce the "
            "same device and link ids."
        )
        family = st.selectbox(
            "Topology family",
            GENERATOR_FAMILIES,
            key="generator_family",
        )
        with st.form("generator_form"):
            site = _text(st.text_input("Site id", value="site-1", key="gen_site"))
            _render_generator_controls(family)
            submitted = st.form_submit_button(
                "Generate topology", type="primary", key="generate_topology"
            )
        if submitted:
            try:
                topology = _generate_from_widgets(family, site or "site-1")
            except (NetArchitectError, ValidationError, ValueError) as error:
                st.error(_format_error(error), title="Generation failed")
            else:
                state.replace_topology(topology)
                _flash(
                    "success",
                    f"Generated {topology.name}: {len(topology.devices)} devices, "
                    f"{len(topology.links)} links.",
                )
                st.rerun()


def _device_rows(topology: Topology) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": device.id,
                "type": device.type.value,
                "site": device.site,
                "role": device.role.value,
            }
            for device in topology.devices
        ],
        columns=list(DEVICE_COLUMNS),
    )


def _link_rows(topology: Topology) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": link.id,
                "endpoint_a": link.endpoints[0],
                "endpoint_b": link.endpoints[1],
                "capacity_mbps": link.capacity_mbps,
                "cost": link.cost,
                "directed": link.directed,
            }
            for link in topology.links
        ],
        columns=list(LINK_COLUMNS),
    )


def _apply_device_edits(topology: Topology, edited: pd.DataFrame) -> int:
    if _id_was_edited("device_editor", len(topology.devices)):
        raise ValueError(
            "Device ids are immutable. Delete the row and add a new device instead."
        )

    devices: list[Device] = []
    for _, row in edited.iterrows():
        device_id = _text(row["id"])
        if not device_id:
            raise ValueError("Every device row needs a non-empty id.")
        site = _text(row["site"])
        if not site:
            raise ValueError(f"Device {device_id!r} needs a site id.")
        try:
            devices.append(
                Device(
                    id=device_id,
                    type=DeviceType(_text(row["type"])),
                    site=site,
                    role=DeviceRole(_text(row["role"])),
                )
            )
        except ValueError as error:
            raise ValueError(
                f"Device {device_id!r} has an invalid type or role."
            ) from error

    ids = [device.id for device in devices]
    if len(set(ids)) != len(ids):
        raise ValueError("Device ids must be unique.")

    original = {device.id: device for device in topology.devices}
    edited_by_id = {device.id: device for device in devices}
    updated = topology
    changes = 0

    for device_id, device in edited_by_id.items():
        if device_id in original:
            current = original[device_id]
            if (current.type, current.site, current.role) != (
                device.type,
                device.site,
                device.role,
            ):
                updated = update_device(
                    updated,
                    device_id,
                    type=device.type,
                    site=device.site,
                    role=device.role,
                )
                changes += 1
        else:
            updated = add_device(updated, device)
            changes += 1

    for device_id in original:
        if device_id not in edited_by_id:
            updated = remove_device(updated, device_id)
            changes += 1

    if changes:
        state.replace_topology(updated)
    return changes


def _apply_link_edits(topology: Topology, edited: pd.DataFrame) -> int:
    if _id_was_edited("link_editor", len(topology.links)):
        raise ValueError(
            "Link ids are immutable. Delete the row and add a new link instead."
        )

    links: list[Link] = []
    for _, row in edited.iterrows():
        link_id = _text(row["id"])
        if not link_id:
            raise ValueError("Every link row needs a non-empty id.")
        entities = f"Link {link_id!r}"
        endpoint_a = _text(row["endpoint_a"])
        endpoint_b = _text(row["endpoint_b"])
        if not endpoint_a or not endpoint_b:
            raise ValueError(f"{entities} needs two non-empty endpoints.")
        directed_value = row["directed"]
        directed = False if pd.isna(directed_value) else bool(directed_value)
        links.append(
            Link(
                id=link_id,
                endpoints=(endpoint_a, endpoint_b),
                capacity_mbps=_number(row["capacity_mbps"], "capacity", entities),
                cost=_number(row["cost"], "cost", entities),
                directed=directed,
            )
        )

    ids = [link.id for link in links]
    if len(set(ids)) != len(ids):
        raise ValueError("Link ids must be unique.")

    original = {link.id: link for link in topology.links}
    edited_by_id = {link.id: link for link in links}
    updated = topology
    changes = 0

    for link_id, link in edited_by_id.items():
        if link_id in original:
            current = original[link_id]
            if (
                current.endpoints,
                current.capacity_mbps,
                current.cost,
                current.directed,
            ) != (
                link.endpoints,
                link.capacity_mbps,
                link.cost,
                link.directed,
            ):
                updated = update_link(
                    updated,
                    link_id,
                    endpoints=link.endpoints,
                    capacity_mbps=link.capacity_mbps,
                    cost=link.cost,
                    directed=link.directed,
                )
                changes += 1
        else:
            updated = add_link(updated, link)
            changes += 1

    for link_id in original:
        if link_id not in edited_by_id:
            updated = remove_link(updated, link_id)
            changes += 1

    if changes:
        state.replace_topology(updated)
    return changes


def _render_tables(topology: Topology) -> None:
    st.subheader("Edit topology")
    st.caption(
        "Table edits are applied through the topology engine. Invalid rows are "
        "rejected; ids are immutable."
    )

    with st.container(border=True):
        st.markdown("**Devices**")
        with st.form("device_edit_form"):
            edited_devices = st.data_editor(
                _device_rows(topology),
                key="device_editor",
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                column_config={
                    "id": st.column_config.TextColumn("Device id", required=True),
                    "type": st.column_config.SelectboxColumn(
                        "Type",
                        options=[device_type.value for device_type in DeviceType],
                        required=True,
                    ),
                    "site": st.column_config.TextColumn("Site", required=True),
                    "role": st.column_config.SelectboxColumn(
                        "Role",
                        options=[role.value for role in DeviceRole],
                        required=True,
                    ),
                },
            )
            apply_devices = st.form_submit_button(
                "Apply device changes", key="apply_device_changes"
            )
        if apply_devices:
            try:
                changes = _apply_device_edits(topology, edited_devices)
            except (NetArchitectError, ValidationError, ValueError) as error:
                st.error(_format_error(error), title="Device edits rejected")
            else:
                if changes:
                    _flash("success", f"Applied {changes} device change(s).")
                    st.rerun()
                else:
                    st.info("No device changes to apply.")

    with st.container(border=True):
        st.markdown("**Links**")
        with st.form("link_edit_form"):
            edited_links = st.data_editor(
                _link_rows(topology),
                key="link_editor",
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                column_config={
                    "id": st.column_config.TextColumn("Link id", required=True),
                    "endpoint_a": st.column_config.TextColumn(
                        "Endpoint A", required=True
                    ),
                    "endpoint_b": st.column_config.TextColumn(
                        "Endpoint B", required=True
                    ),
                    "capacity_mbps": st.column_config.NumberColumn(
                        "Capacity (Mbps)", min_value=0.001, format="%.1f"
                    ),
                    "cost": st.column_config.NumberColumn(
                        "Cost", min_value=0.001, format="%.2f"
                    ),
                    "directed": st.column_config.CheckboxColumn("Directed"),
                },
            )
            apply_links = st.form_submit_button(
                "Apply link changes", key="apply_link_changes"
            )
        if apply_links:
            try:
                changes = _apply_link_edits(topology, edited_links)
            except (NetArchitectError, ValidationError, ValueError) as error:
                st.error(_format_error(error), title="Link edits rejected")
            else:
                if changes:
                    _flash("success", f"Applied {changes} link change(s).")
                    st.rerun()
                else:
                    st.info("No link changes to apply.")


def _build_figure(topology: Topology) -> go.Figure | None:
    engine_graph = to_networkx(topology)
    if engine_graph.number_of_nodes() == 0:
        return None

    layout_graph = nx.Graph()
    for node in engine_graph.nodes:
        layout_graph.add_node(node)

    seen_links: set[str] = set()
    links: list[tuple[str, str, bool]] = []
    for source, target, attributes in engine_graph.edges(data=True):
        link_id = str(attributes["link_id"])
        if link_id in seen_links:
            continue
        seen_links.add(link_id)
        links.append((source, target, bool(attributes["directed"])))
        if not layout_graph.has_edge(source, target):
            layout_graph.add_edge(source, target)

    positions = nx.spring_layout(layout_graph, seed=42, iterations=60)
    figure = go.Figure()

    for directed, label, dash, color in LINK_STYLES:
        x_values: list[float | None] = []
        y_values: list[float | None] = []
        for source, target, is_directed in links:
            if is_directed is not directed:
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

    roles = sorted({engine_graph.nodes[node]["role"] for node in engine_graph.nodes})
    show_labels = engine_graph.number_of_nodes() <= 30
    for role in roles:
        nodes = [
            node for node in engine_graph.nodes if engine_graph.nodes[node]["role"] == role
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


def _render_connectivity(topology: Topology) -> None:
    report = analyze_connectivity(topology)
    columns = st.columns(4)
    columns[0].metric("Devices", report.node_count)
    columns[1].metric("Links", report.link_count)
    columns[2].metric("Components", report.component_count)
    columns[3].metric("Isolated devices", len(report.isolated_device_ids))

    if report.is_connected:
        st.success(
            "Connected: every device is reachable through the modeled links.",
            title="Connectivity",
        )
    else:
        st.warning(
            f"The topology has {report.component_count} disconnected components.",
            title="Connectivity",
        )
    if report.isolated_device_ids:
        listed = ", ".join(report.isolated_device_ids[:12])
        suffix = (
            f" and {len(report.isolated_device_ids) - 12} more"
            if len(report.isolated_device_ids) > 12
            else ""
        )
        st.caption(f"Isolated devices: {listed}{suffix}")


def _render_twin_consistency() -> None:
    """Show dependent-plan findings after a topology change.

    The twin keeps addressing, VLAN, DHCP, demand, and state data when the
    topology changes. Stale references are reported here instead of being
    pruned silently. The topology-only connectivity finding is omitted because
    the connectivity panel above already reports it.
    """
    twin = state.get_twin()
    if twin is None:
        return
    findings = [
        finding
        for finding in validate_twin(twin).findings
        if finding.code != "twin_topology_disconnected"
    ]
    with st.container(border=True):
        st.subheader("Digital twin consistency")
        if not findings:
            st.success(
                "Addressing, VLAN, DHCP, demands, and operational state all "
                "reference current topology entities.",
                title="Consistent",
            )
            return
        st.warning(
            "Dependent parts reference entities that are no longer current. "
            "Review the findings before relying on this twin.",
            title="Needs review",
        )
        st.dataframe(findings_frame(findings), hide_index=True, width="stretch")


def _render_diagram(topology: Topology) -> None:
    with st.container(border=True):
        st.subheader("Diagram")
        st.caption(
            "Deterministic spring layout (seed 42). Link style shows direction; "
            "node color shows hierarchical role."
        )
        figure = _build_figure(topology)
        if figure is None:
            st.info("The topology has no devices to display.")
            return
        st.plotly_chart(
            figure,
            width="stretch",
            config={"displayModeBar": False},
            alt=(
                f"Topology diagram with {len(topology.devices)} devices and "
                f"{len(topology.links)} links"
            ),
        )


def _render_json(topology: Topology | None) -> None:
    with st.container(border=True):
        st.subheader("JSON")
        st.caption(
            "Exports use the versioned domain schema and round-trip exactly. "
            "Imported files are validated before they replace the current topology."
        )
        if topology is not None:
            safe_name = re.sub(r"[^a-z0-9]+", "-", topology.name.lower()).strip("-")
            st.download_button(
                "Download topology JSON",
                data=to_json(topology),
                file_name=f"{safe_name or 'topology'}.json",
                mime="application/json",
                key="download_topology",
            )
        with st.form("import_form"):
            uploaded = st.file_uploader(
                "Import topology JSON",
                type=["json"],
                key="topology_upload",
            )
            load = st.form_submit_button("Load topology", key="import_topology")
        if load:
            if uploaded is None:
                st.error("Choose a JSON file before loading.")
            else:
                try:
                    imported = from_json(uploaded.getvalue().decode("utf-8"))
                except (NetArchitectError, ValidationError, ValueError) as error:
                    st.error(_format_error(error), title="Import failed")
                else:
                    state.replace_topology(imported)
                    _flash(
                        "success",
                        f"Imported {imported.name}: {len(imported.devices)} devices, "
                        f"{len(imported.links)} links.",
                    )
                    st.rerun()


def render() -> None:
    """Render the topology editor page."""
    st.title("Topology editor")
    st.caption(
        "Generate, inspect, and edit the modeled network. All changes run "
        "through deterministic engineering services."
    )
    _render_flash()

    _render_generator()
    topology = _current_topology()

    if topology is None:
        st.info(
            "No topology loaded. Generate one above, or import a topology JSON file."
        )
        _render_json(None)
        return

    st.subheader(topology.name)
    _render_connectivity(topology)
    _render_twin_consistency()
    _render_diagram(topology)
    _render_tables(topology)
    _render_json(topology)
