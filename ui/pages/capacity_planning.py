"""Capacity Planning page (Phase 12c).

A read-only inventory of the capacities and demand assumptions already stored in
the digital twin, plus the modeled utilization from the most recent scenario run
on the same twin revision. The page does not forecast growth, recommend a
capacity change, or introduce a new capacity model.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from digital_twin import DigitalTwin
from simulation import ScenarioRun, twin_fingerprint
from ui import state
from ui.components import csv_bytes, empty_state, page_header

LINKS_DOWNLOAD_KEY = "capacity_links_download"
DEMANDS_DOWNLOAD_KEY = "capacity_demands_download"
LOAD_DOWNLOAD_KEY = "capacity_load_download"


def _link_frame(twin: DigitalTwin) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "link_id": link.id,
                "endpoint_a": link.endpoints[0],
                "endpoint_b": link.endpoints[1],
                "capacity_mbps": link.capacity_mbps,
                "directed": link.directed,
            }
            for link in twin.topology.links
        ],
        columns=[
            "link_id",
            "endpoint_a",
            "endpoint_b",
            "capacity_mbps",
            "directed",
        ],
    )


def _demand_frame(twin: DigitalTwin) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": demand.name,
                "source": demand.source,
                "destination": demand.destination,
                "bandwidth_mbps": demand.bandwidth_mbps,
                "priority": demand.priority,
            }
            for demand in twin.demands
        ],
        columns=[
            "name",
            "source",
            "destination",
            "bandwidth_mbps",
            "priority",
        ],
    )


def _render_inventory(twin: DigitalTwin) -> None:
    links = _link_frame(twin)
    demands = _demand_frame(twin)
    total_capacity = float(links["capacity_mbps"].sum()) if len(links) else 0.0
    total_requested = (
        float(demands["bandwidth_mbps"].sum()) if len(demands) else 0.0
    )

    columns = st.columns(4)
    columns[0].metric("Links", len(links))
    columns[1].metric("Configured capacity", f"{total_capacity:,.1f} Mbps")
    columns[2].metric("Demands", len(demands))
    columns[3].metric("Stated demand", f"{total_requested:,.1f} Mbps")
    st.caption(
        "Configured capacity is the sum of link capacities. Stated demand is the "
        "sum of demand bandwidth assumptions; the two totals are inventory "
        "figures, not a utilization or feasibility result."
    )

    st.subheader("Link capacity inventory")
    if links.empty:
        empty_state("The topology has no links.")
    else:
        st.dataframe(
            links,
            hide_index=True,
            width="stretch",
            column_config={
                "link_id": st.column_config.TextColumn("Link id"),
                "endpoint_a": st.column_config.TextColumn("Endpoint A"),
                "endpoint_b": st.column_config.TextColumn("Endpoint B"),
                "capacity_mbps": st.column_config.NumberColumn(
                    "Capacity (Mbps)", format="%.1f"
                ),
                "directed": st.column_config.CheckboxColumn("Directed"),
            },
        )
        st.download_button(
            "Download link capacity as CSV",
            data=csv_bytes(links),
            file_name="capacity-links.csv",
            mime="text/csv",
            key=LINKS_DOWNLOAD_KEY,
        )

    st.subheader("Demand inventory")
    if demands.empty:
        empty_state(
            "The twin has no traffic demands. Add them on the Simulation Lab page."
        )
    else:
        st.dataframe(
            demands,
            hide_index=True,
            width="stretch",
            column_config={
                "name": st.column_config.TextColumn("Demand"),
                "source": st.column_config.TextColumn("Source"),
                "destination": st.column_config.TextColumn("Destination"),
                "bandwidth_mbps": st.column_config.NumberColumn(
                    "Bandwidth (Mbps)", format="%.2f"
                ),
                "priority": st.column_config.NumberColumn("Priority", format="%d"),
            },
        )
        st.download_button(
            "Download demands as CSV",
            data=csv_bytes(demands),
            file_name="capacity-demands.csv",
            mime="text/csv",
            key=DEMANDS_DOWNLOAD_KEY,
        )


def _latest_run(twin: DigitalTwin) -> ScenarioRun | None:
    runs = state.peek_simulation_runs()
    if not runs:
        return None
    run = runs[-1]
    if run.baseline_twin.fingerprint != twin_fingerprint(twin):
        return None
    return run


def _load_frame(run: ScenarioRun) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "link_id": link.link_id,
                "endpoint_a": link.endpoints[0],
                "endpoint_b": link.endpoints[1],
                "capacity_mbps": link.capacity_mbps,
                "load_mbps": link.load_mbps,
                "utilization_percent": link.utilization_percent,
            }
            for link in run.scenario_state.links
        ],
        columns=[
            "link_id",
            "endpoint_a",
            "endpoint_b",
            "capacity_mbps",
            "load_mbps",
            "utilization_percent",
        ],
    )


def _render_latest_load(twin: DigitalTwin) -> None:
    st.subheader("Latest modeled utilization")
    run = _latest_run(twin)
    if run is None:
        empty_state(
            "No scenario run matches the current twin revision. Run a scenario "
            "in the Simulation Lab to see modeled link utilization here.",
            hint=(
                "Utilization is a modeled estimate from the simulation "
                "assumptions, not measured traffic."
            ),
        )
        return

    st.caption(
        f"Source: scenario {run.scenario.name!r} on this twin revision. "
        f"Assumption: link capacity is {twin.topology.name!r} metadata; load is "
        "modeled from the demand set."
    )
    frame = _load_frame(run)
    if frame.empty:
        empty_state("The scenario state has no surviving links to report.")
        return
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            "link_id": st.column_config.TextColumn("Link id"),
            "endpoint_a": st.column_config.TextColumn("Endpoint A"),
            "endpoint_b": st.column_config.TextColumn("Endpoint B"),
            "capacity_mbps": st.column_config.NumberColumn(
                "Capacity (Mbps)", format="%.1f"
            ),
            "load_mbps": st.column_config.NumberColumn(
                "Modeled load (Mbps)", format="%.2f"
            ),
            "utilization_percent": st.column_config.NumberColumn(
                "Utilization (%)", format="%.2f"
            ),
        },
    )
    st.download_button(
        "Download modeled utilization as CSV",
        data=csv_bytes(frame),
        file_name="capacity-utilization.csv",
        mime="text/csv",
        key=LOAD_DOWNLOAD_KEY,
    )


def render() -> None:
    """Render the read-only capacity inventory."""
    page_header(
        "Capacity Planning",
        "Read-only inventory of configured link capacities, stated demand "
        "bandwidth, and the latest modeled utilization on the current twin "
        "revision. No growth forecast or capacity recommendation is produced.",
    )

    twin = state.get_twin()
    if twin is None or not twin.topology.devices:
        empty_state(
            "No digital twin with a topology is loaded. Open the Topology "
            "Editor to create, generate, or import one, then return here.",
            title="Digital twin required",
            hint=(
                "This page reports existing capacity data only. Forecasts and "
                "capacity planning recommendations are outside Phase 12."
            ),
        )
        return

    _render_inventory(twin)
    st.divider()
    _render_latest_load(twin)


__all__ = ["render"]
