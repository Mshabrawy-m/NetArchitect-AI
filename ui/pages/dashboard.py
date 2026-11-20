"""Dashboard page: a read-only overview of the current session.

The page reports only data already stored in session state. It does not create
a design, run an engine, or show placeholder numbers.
"""

from __future__ import annotations

import streamlit as st

from ui import state
from ui.components import empty_state, page_header, render_design_health


def render_dashboard() -> None:
    """Render the application overview from twin and session data."""
    page_header(
        "Dashboard",
        "Current state of the digital twin and the engineering runs retained in "
        "this session.",
    )

    twin = state.get_twin()
    if twin is None:
        empty_state(
            "No digital twin is loaded. Create one in the AI Network Designer "
            "or generate or import a topology in the Topology Editor.",
            title="Digital twin required",
            hint=(
                "The dashboard reports only data already stored in session "
                "state. It does not create a design or run an engine."
            ),
        )
        return

    topology = twin.topology
    snapshots = state.peek_snapshots()
    scenarios = state.peek_simulation_runs()
    optimizations = state.peek_optimization_runs()

    columns = st.columns(6)
    columns[0].metric("Devices", len(topology.devices))
    columns[1].metric("Links", len(topology.links))
    columns[2].metric("Demands", len(twin.demands))
    columns[3].metric("Snapshots", len(snapshots))
    columns[4].metric("Scenario runs", len(scenarios))
    columns[5].metric("Optimization runs", len(optimizations))

    addressing = twin.addressing
    st.caption(
        f"Twin: {twin.metadata.name} | Schema version: "
        f"{twin.metadata.schema_version} | Created: "
        f"{twin.metadata.created_at.isoformat()} | Subnets: "
        f"{len(addressing.subnets) if addressing is not None else 0} | "
        f"VLAN plans: "
        f"{len(addressing.vlan_plans) if addressing is not None else 0} | "
        f"DHCP scopes: {len(twin.dhcp_scopes)}"
    )

    render_design_health(twin)

    st.subheader("Retained runs")
    if not scenarios and not optimizations:
        empty_state(
            "No scenario or optimization runs are retained in this session. "
            "Run one from the Simulation Lab or Optimization Center."
        )
        return

    latest_columns = st.columns(2)
    with latest_columns[0]:
        if scenarios:
            run = scenarios[-1]
            status = (
                "recovery available"
                if run.comparison.recovery_available
                else "not all baseline demands recovered"
            )
            st.metric(
                "Latest scenario served demand",
                f"{run.comparison.scenario_served_demand_ratio:.1%}",
                help=f"Scenario: {run.scenario.name}. Status: {status}.",
            )
            st.caption(
                f"{run.scenario.name} | {run.scenario.type.value} | "
                f"{status} | {len(run.comparison.newly_unserved_demands)} newly "
                "unserved demand(s)"
            )
        else:
            st.caption("No scenario runs retained.")

    with latest_columns[1]:
        if optimizations:
            run = optimizations[-1]
            st.metric(
                "Latest optimization evaluations",
                run.evaluations,
                help=(
                    f"{run.algorithm.value}; stopped with "
                    f"{run.stop_reason.value}."
                ),
            )
            st.caption(
                f"{run.algorithm.value} | {run.stop_reason.value} | "
                f"{len(run.pareto_front)} Pareto candidate(s) | "
                f"{'feasible best' if run.best is not None else 'no feasible best'}"
            )
        else:
            st.caption("No optimization runs retained.")


__all__ = ["render_dashboard"]
