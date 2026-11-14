"""NetArchitect AI - Streamlit entry point.

Phase 6 adds the digital twin: one session model that is the single source of
truth for the topology, planning results, traffic demands, and modeled
operational state. Phase 7 adds deterministic what-if simulation over that twin.
Phase 8 adds bounded, reproducible multi-objective optimization. Phase 9 adds
the optional Groq provider layer, the deterministic agent framework, and the
Settings page with a structured design-plan runner. Phase 10 adds the
specialized requirements, critic, and documentation agents plus the AI Network
Designer and read-only Agent Control Center pages. The Topology Editor, IP
Addressing, VLAN & DHCP Planner, Routing Analysis, Network Analytics, Digital
Twin, Simulation Lab, Optimization Center, AI Network Designer, Agent Control
Center, and Settings are working engineering pages; the remaining planned pages
stay as placeholders and are added phase by phase.
"""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from ui.pages.agent_control_center import render as render_agent_control_center
from ui.pages.ai_designer import render as render_ai_designer
from ui.pages.digital_twin import render as render_digital_twin
from ui.pages.ip_addressing import render as render_ip_addressing
from ui.pages.network_analytics import render as render_network_analytics
from ui.pages.optimization_center import render as render_optimization_center
from ui.pages.routing_analysis import render as render_routing_analysis
from ui.pages.settings import render as render_settings
from ui.pages.simulation_lab import render as render_simulation_lab
from ui.pages.topology_editor import render as render_topology_editor
from ui.pages.vlan_dhcp import render as render_vlan_dhcp

# The 14 planned application pages from the blueprint (section 7).
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
    "Agent Control Center",
    "Reports & Documentation",
    "Settings",
)

READY_PAGES: frozenset[str] = frozenset(
    {
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
        "Agent Control Center",
        "Settings",
    }
)


def render_sidebar_navigation() -> str:
    """Render the sidebar navigation and return the selected page."""
    with st.sidebar:
        st.markdown("## Navigation")
        page = st.selectbox("Page", PAGES, index=0, key="page_nav")
        if page in READY_PAGES:
            st.caption(
                "Available now: Dashboard, AI Network Designer, Topology Editor, "
                "IP Addressing, VLAN & DHCP Planner, Routing Analysis, Network "
                "Analytics, Digital Twin, Simulation Lab, Optimization Center, "
                "Agent Control Center, and Settings."
            )
        else:
            st.caption("This page arrives in a later phase.")
        st.divider()
        st.caption("NetArchitect AI - deterministic network engineering first.")
    return page


def render_dashboard() -> None:
    """Render the application overview page."""
    settings = get_settings()

    st.title("NetArchitect AI")
    st.write(
        "A software platform for designing, simulating, validating, and "
        "optimizing computer network architectures using coordinated AI "
        "agents and deterministic network-engineering tools. The network "
        "model and simulation are abstractions implemented in Python; the "
        "platform does not configure or operate real networking equipment."
    )

    st.write(f"**Application:** {settings.APP_NAME}  ")
    st.write(f"**Version:** {settings.APP_VERSION}  ")
    st.write(f"**Deployment target:** {settings.DEPLOYMENT_TARGET}")

    st.info(
        "Phase 10 is in progress. The Topology Editor, IP Addressing, VLAN & "
        "DHCP Planner, Routing Analysis, Network Analytics, Digital Twin, "
        "Simulation Lab, Optimization Center, AI Network Designer, Agent Control "
        "Center, and Settings are available from the sidebar; remaining pages are "
        "introduced with their engineering modules. AI features are optional and "
        "need a Groq API key, while the engineering engines and the deterministic "
        "structured plan do not."
    )


def render_placeholder(page: str) -> None:
    """Render the coming-soon state for a planned page."""
    st.title(page)
    st.info(f"{page} will be implemented in a later phase.")


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
    elif page == "Agent Control Center":
        render_agent_control_center()
    elif page == "Settings":
        render_settings()
    else:
        render_placeholder(page)


if __name__ == "__main__":
    main()
