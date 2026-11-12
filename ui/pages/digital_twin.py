"""Digital Twin page.

The digital twin is a *software model* of a network design. It is the single
source of truth for the topology, addressing/VLAN/DHCP plans, traffic demands,
and modeled operational state. It is not a connection to, or a live copy of,
real networking equipment.

This page is presentation only. State edits and snapshots are delegated to
:mod:`digital_twin`; session access goes through :mod:`ui.state`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.exceptions import NetArchitectError
from digital_twin import (
    OperationalState,
    Snapshot,
    diff_twins,
    effective_device_state,
    effective_link_state,
    to_json,
    validate_twin,
)
from ui import state
from ui.components import csv_bytes, render_findings

SNAPSHOT_LABEL_KEY = "twin_snapshot_label"
SNAPSHOT_CREATE_KEY = "twin_create_snapshot"
STATE_APPLY_KEY = "twin_apply_states"
COMPARE_BEFORE_KEY = "twin_compare_before"
COMPARE_AFTER_KEY = "twin_compare_after"
DOWNLOAD_SNAPSHOT_KEY = "twin_download_snapshot"
DELETE_SNAPSHOT_KEY = "twin_delete_snapshot"


def _state_value(value: object) -> OperationalState:
    """Coerce an editor cell to a canonical operational state."""
    if isinstance(value, OperationalState):
        return value
    try:
        return OperationalState(str(value).strip().lower())
    except ValueError as error:
        raise ValueError(f"Unknown operational state {value!r}.") from error


def _device_state_rows(twin) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "device_id": device.id,
                "type": device.type.value,
                "site": device.site,
                "state": effective_device_state(twin, device.id).value,
            }
            for device in twin.topology.devices
        ],
        columns=["device_id", "type", "site", "state"],
    )


def _link_state_rows(twin) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "link_id": link.id,
                "endpoint_a": link.endpoints[0],
                "endpoint_b": link.endpoints[1],
                "capacity_mbps": link.capacity_mbps,
                "cost": link.cost,
                "state": effective_link_state(twin, link.id).value,
            }
            for link in twin.topology.links
        ],
        columns=[
            "link_id",
            "endpoint_a",
            "endpoint_b",
            "capacity_mbps",
            "cost",
            "state",
        ],
    )


def _render_summary(twin) -> None:
    columns = st.columns(5)
    columns[0].metric("Devices", len(twin.topology.devices))
    columns[1].metric("Links", len(twin.topology.links))
    columns[2].metric("Demands", len(twin.demands))
    columns[3].metric("DHCP scopes", len(twin.dhcp_scopes))
    columns[4].metric("Snapshots", len(state.get_snapshots()))
    st.caption(
        f"Name: {twin.metadata.name} | Schema version: "
        f"{twin.metadata.schema_version} | Created: "
        f"{twin.metadata.created_at.isoformat()} | Addressing plan: "
        f"{'present' if twin.addressing is not None else 'none'} | VLAN plan: "
        f"{'present' if twin.vlan_plan is not None else 'none'}"
    )


def _render_state_editor(twin) -> None:
    st.subheader("Operational state")
    st.caption(
        "State is modeled, not measured. A device or link without an explicit "
        "entry is up. Marking an entity down excludes it from routing and "
        "analytics; it does not change the baseline topology."
    )
    with st.form("twin_state_form"):
        st.markdown("**Devices**")
        devices = st.data_editor(
            _device_state_rows(twin),
            key="twin_device_state_editor",
            hide_index=True,
            width="stretch",
            disabled=["device_id", "type", "site"],
            column_config={
                "device_id": st.column_config.TextColumn("Device id"),
                "type": st.column_config.TextColumn("Type"),
                "site": st.column_config.TextColumn("Site"),
                "state": st.column_config.SelectboxColumn(
                    "State",
                    options=[value.value for value in OperationalState],
                    required=True,
                ),
            },
        )
        st.markdown("**Links**")
        links = st.data_editor(
            _link_state_rows(twin),
            key="twin_link_state_editor",
            hide_index=True,
            width="stretch",
            disabled=[
                "link_id",
                "endpoint_a",
                "endpoint_b",
                "capacity_mbps",
                "cost",
            ],
            column_config={
                "link_id": st.column_config.TextColumn("Link id"),
                "endpoint_a": st.column_config.TextColumn("Endpoint A"),
                "endpoint_b": st.column_config.TextColumn("Endpoint B"),
                "capacity_mbps": st.column_config.NumberColumn(
                    "Capacity (Mbps)", format="%.2f"
                ),
                "cost": st.column_config.NumberColumn("Cost", format="%.2f"),
                "state": st.column_config.SelectboxColumn(
                    "State",
                    options=[value.value for value in OperationalState],
                    required=True,
                ),
            },
        )
        applied = st.form_submit_button(
            "Apply operational state",
            key=STATE_APPLY_KEY,
            type="primary",
        )

    if not applied:
        return

    try:
        down_devices = tuple(
            str(row["device_id"])
            for _, row in devices.iterrows()
            if _state_value(row["state"]) is OperationalState.down
        )
        down_links = tuple(
            str(row["link_id"])
            for _, row in links.iterrows()
            if _state_value(row["state"]) is OperationalState.down
        )
        state.set_operational_states(
            down_devices=down_devices,
            down_links=down_links,
        )
    except (NetArchitectError, ValidationError, ValueError) as error:
        st.error(str(error), title="State update failed")
    else:
        st.success(
            f"Operational state applied: {len(down_devices)} device(s) and "
            f"{len(down_links)} link(s) modeled as down."
        )
        st.rerun()


def _snapshot_label(index: int, snapshot: Snapshot) -> str:
    return f"{index + 1}. {snapshot.label} ({snapshot.captured_at.isoformat()})"


def _snapshot_frame(snapshots: tuple[Snapshot, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "index": index + 1,
                "label": snapshot.label,
                "captured_at": snapshot.captured_at.isoformat(),
                "devices": len(snapshot.twin.topology.devices),
                "links": len(snapshot.twin.topology.links),
                "size_bytes": snapshot.size_bytes(),
            }
            for index, snapshot in enumerate(snapshots)
        ],
        columns=[
            "index",
            "label",
            "captured_at",
            "devices",
            "links",
            "size_bytes",
        ],
    )


def _diff_rows(diff) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for device_id in diff.devices_added:
        rows.append({"kind": "device added", "entity": device_id, "before": "", "after": ""})
    for device_id in diff.devices_removed:
        rows.append({"kind": "device removed", "entity": device_id, "before": "", "after": ""})
    for link_id in diff.links_added:
        rows.append({"kind": "link added", "entity": link_id, "before": "", "after": ""})
    for link_id in diff.links_removed:
        rows.append({"kind": "link removed", "entity": link_id, "before": "", "after": ""})
    for change in diff.device_state_changes:
        rows.append(
            {
                "kind": "device state",
                "entity": change.entity_id,
                "before": change.before.value,
                "after": change.after.value,
            }
        )
    for change in diff.link_state_changes:
        rows.append(
            {
                "kind": "link state",
                "entity": change.entity_id,
                "before": change.before.value,
                "after": change.after.value,
            }
        )
    for change in diff.capacity_changes:
        rows.append(
            {
                "kind": "link capacity (Mbps)",
                "entity": change.link_id,
                "before": change.before_mbps,
                "after": change.after_mbps,
            }
        )
    for change in diff.cost_changes:
        rows.append(
            {
                "kind": "link cost",
                "entity": change.link_id,
                "before": change.before,
                "after": change.after,
            }
        )
    for name in diff.demands_added:
        rows.append({"kind": "demand added", "entity": name, "before": "", "after": ""})
    for name in diff.demands_removed:
        rows.append({"kind": "demand removed", "entity": name, "before": "", "after": ""})
    for change in diff.demand_changes:
        rows.append(
            {
                "kind": "demand changed",
                "entity": change.name,
                "before": str(change.before),
                "after": str(change.after),
            }
        )
    if diff.addressing_changed:
        rows.append(
            {"kind": "addressing plan", "entity": "", "before": "", "after": "changed"}
        )
    if diff.vlan_plan_changed:
        rows.append(
            {"kind": "VLAN plan", "entity": "", "before": "", "after": "changed"}
        )
    if diff.dhcp_scopes_changed:
        rows.append(
            {"kind": "DHCP scopes", "entity": "", "before": "", "after": "changed"}
        )
    if diff.assumptions_changed:
        rows.append(
            {"kind": "assumptions", "entity": "", "before": "", "after": "changed"}
        )
    return pd.DataFrame(
        rows,
        columns=["kind", "entity", "before", "after"],
    )


def _render_snapshot_actions(twin, snapshots: tuple[Snapshot, ...]) -> None:
    st.subheader("Snapshots")
    st.caption(
        "A snapshot is a frozen deep copy of the current twin. Snapshots are "
        "bounded in count and total size; they are not comparisons with live "
        "equipment."
    )
    label = st.text_input(
        "Snapshot label",
        value=f"{twin.metadata.name} snapshot",
        key=SNAPSHOT_LABEL_KEY,
    )
    if st.button(
        "Create snapshot",
        key=SNAPSHOT_CREATE_KEY,
        type="primary",
    ):
        try:
            state.create_twin_snapshot(label.strip() or "Untitled snapshot")
        except (NetArchitectError, ValidationError, ValueError) as error:
            st.error(str(error), title="Snapshot not created")
        else:
            st.success(f"Created snapshot {label.strip()!r}.")
            st.rerun()

    if not snapshots:
        st.info("No snapshots yet. Create one to compare later revisions.")
        return

    st.dataframe(_snapshot_frame(snapshots), hide_index=True, width="stretch")
    st.download_button(
        "Download snapshot list as CSV",
        data=csv_bytes(_snapshot_frame(snapshots)),
        file_name="twin-snapshots.csv",
        mime="text/csv",
        key="twin_snapshots_download",
    )

    labels = [_snapshot_label(index, snapshot) for index, snapshot in enumerate(snapshots)]
    selected_index = state.session_get(DOWNLOAD_SNAPSHOT_KEY)
    if selected_index not in range(len(snapshots)):
        selected_index = 0
        state.session_set(DOWNLOAD_SNAPSHOT_KEY, selected_index)
    selected_index = st.selectbox(
        "Snapshot for download or deletion",
        options=range(len(snapshots)),
        format_func=lambda index: labels[index],
        key=DOWNLOAD_SNAPSHOT_KEY,
    )
    selected = snapshots[selected_index]
    safe_label = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in selected.label.lower()
    ).strip("-")
    download_columns = st.columns(2)
    with download_columns[0]:
        st.download_button(
            "Download selected snapshot JSON",
            data=to_json(selected.twin),
            file_name=f"{safe_label or 'snapshot'}.json",
            mime="application/json",
            key="twin_snapshot_download",
        )
    with download_columns[1]:
        if st.button("Delete selected snapshot", key=DELETE_SNAPSHOT_KEY):
            try:
                state.delete_snapshot(selected_index)
            except (IndexError, ValueError) as error:
                st.error(str(error), title="Snapshot not deleted")
            else:
                st.success(f"Deleted snapshot {selected.label!r}.")
                st.rerun()


def _render_comparison(
    twin,
    snapshots: tuple[Snapshot, ...],
) -> None:
    st.subheader("Compare")
    choices = [*range(len(snapshots)), -1]
    if len(choices) < 2:
        st.info("Create at least one snapshot to compare revisions.")
        return

    def format_choice(index: int) -> str:
        if index == -1:
            return "Current twin"
        return _snapshot_label(index, snapshots[index])

    def choose(label: str, key: str, default: int) -> int:
        current = state.session_get(key)
        if current not in choices:
            state.session_set(key, default)
        return st.selectbox(
            label,
            options=choices,
            index=choices.index(default),
            format_func=format_choice,
            key=key,
        )

    before_choice = choose("Before", COMPARE_BEFORE_KEY, choices[0])
    after_choice = choose("After", COMPARE_AFTER_KEY, choices[-1])

    def resolve(index: int):
        if index == -1:
            return twin
        return snapshots[index].twin

    try:
        before = resolve(before_choice)
        after = resolve(after_choice)
        diff = diff_twins(before, after)
    except (IndexError, ValueError) as error:
        st.error(str(error), title="Comparison failed")
        return

    st.caption(diff.summary())
    if not diff.has_changes:
        st.success("The selected revisions are identical.")
        return

    frame = _diff_rows(diff)
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download comparison as CSV",
        data=csv_bytes(frame),
        file_name="twin-comparison.csv",
        mime="text/csv",
        key="twin_comparison_download",
    )


def render() -> None:
    """Render the Digital Twin page."""
    st.title("Digital Twin")
    st.caption(
        "The digital twin is a software model of the design and the single "
        "source of truth for topology, addressing, VLAN/DHCP plans, demands, "
        "and modeled operational state. It is not a live copy of real equipment."
    )

    twin = state.get_twin()
    if twin is None:
        st.info(
            "No digital twin is loaded. Generate or import a topology in the "
            "Topology Editor to create one."
        )
        return

    _render_summary(twin)
    st.divider()
    _render_state_editor(twin)
    st.divider()
    st.subheader("Validation")
    render_findings(
        validate_twin(twin).findings,
        "No digital-twin findings: topology, plans, demands, and state are consistent.",
    )
    st.divider()
    _render_snapshot_actions(twin, state.get_snapshots())
    st.divider()
    _render_comparison(twin, state.get_snapshots())
