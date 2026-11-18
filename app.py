"""NetArchitect AI - Streamlit entry point.

Phase 6 adds the digital twin: one session model that is the single source of
truth for the topology, planning results, traffic demands, and modeled
operational state. Phase 7 adds deterministic what-if simulation over that twin.
Phase 8 adds bounded, reproducible multi-objective optimization. Phase 9 adds
the optional Groq provider layer, the deterministic agent framework, and the
Settings page with a structured design-plan runner. Phase 10 adds the
specialized requirements, critic, and documentation agents plus the AI Network
Designer and read-only Agent Control Center pages. Phase 11 adds
provenance-tagged reports, in-memory exports, and the Reports & Documentation
page. The Topology Editor, IP Addressing, VLAN & DHCP Planner, Routing
Analysis, Network Analytics, Digital Twin, Simulation Lab, Optimization Center,
Capacity Planning, Security Analysis, AI Network Designer, Agent Control
Center, Reports & Documentation, and Settings are working engineering pages.
"""

from __future__ import annotations

import streamlit as st

from ui import state
from ui.components import empty_state, page_header, render_design_health
from ui.pages.agent_control_center import render as render_agent_control_center
from ui.pages.ai_designer import render as render_ai_designer
from ui.pages.capacity_planning import render as render_capacity_planning
from ui.pages.digital_twin import render as render_digital_twin
from ui.pages.ip_addressing import render as render_ip_addressing
from ui.pages.network_analytics import render as render_network_analytics
from ui.pages.optimization_center import render as render_optimization_center
from ui.pages.reports import render as render_reports
from ui.pages.routing_analysis import render as render_routing_analysis
from ui.pages.security_analysis import render as render_security_analysis
from ui.pages.settings import render as render_settings
from ui.pages.simulation_lab import render as render_simulation_lab
from ui.pages.topology_editor import render as render_topology_editor
from ui.pages.vlan_dhcp import render as render_vlan_dhcp

# The 15 planned application pages from the blueprint (section 7).
PAGES: tuple[str, ...] = (
    "Dashboard",
    "AI Network Designer",
    "Topology Editor",
    "IP Addressing & Subnetting",
    "VLAN & DHCP Planner",
    "Routing Analysis",
    "Network Analytics",
    "Digital Twin",
    "Simulation Lab",
    "Optimization Center",
    "Capacity Planning",
    "Security Analysis",
    "Agent Control Center",
    "Reports & Documentation",
    "Settings",
)

READY_PAGES: frozenset[str] = frozenset(PAGES)


def render_sidebar_navigation() -> str:
    """Render the sidebar navigation and return the selected page."""
    with st.sidebar:
        st.markdown("## Navigation")
        page = st.selectbox("Page", PAGES, index=0, key="page_nav")
        st.caption("All 15 pages are available.")
        st.divider()
        st.caption("NetArchitect AI - deterministic network engineering first.")
    return page


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


def main() -> None:
    """Render the selected application page."""
    st.set_page_config(
        page_title="NetArchitect AI",
        page_icon=":material/hub:",
        layout="wide",
        menu_items={
            "About": (
                "NetArchitect AI - agentic network architecture, digital "
                "twin, and multi-objective optimization platform."
            ),
        },
    )

    page = render_sidebar_navigation()

    if page == "Dashboard":
        render_dashboard()
    elif page == "AI Network Designer":
        render_ai_designer()
    elif page == "Topology Editor":
        render_topology_editor()
    elif page == "IP Addressing & Subnetting":
        render_ip_addressing()
    elif page == "VLAN & DHCP Planner":
        render_vlan_dhcp()
    elif page == "Routing Analysis":
        render_routing_analysis()
    elif page == "Network Analytics":
        render_network_analytics()
    elif page == "Digital Twin":
        render_digital_twin()
    elif page == "Simulation Lab":
        render_simulation_lab()
    elif page == "Optimization Center":
        render_optimization_center()
    elif page == "Capacity Planning":
        render_capacity_planning()
    elif page == "Security Analysis":
        render_security_analysis()
    elif page == "Agent Control Center":
        render_agent_control_center()
    elif page == "Reports & Documentation":
        render_reports()
    elif page == "Settings":
        render_settings()


if __name__ == "__main__":
    main()
