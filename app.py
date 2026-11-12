"""NetArchitect AI - Streamlit entry point.

Phase 3 introduces functional page routing. The Topology Editor is the first
working engineering page; the remaining planned pages stay as placeholders and
are added phase by phase.
"""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from ui.pages.topology_editor import render as render_topology_editor

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

READY_PAGES: frozenset[str] = frozenset({"Dashboard", "Topology Editor"})


def render_sidebar_navigation() -> str:
    """Render the sidebar navigation and return the selected page."""
    with st.sidebar:
        st.markdown("## Navigation")
        page = st.selectbox("Page", PAGES, index=0, key="page_nav")
        if page in READY_PAGES:
            st.caption("Available now: Dashboard and Topology Editor.")
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
        "Phase 3 is in progress. The Topology Editor is available from the "
        "sidebar; remaining pages are introduced with their engineering "
        "modules."
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
    elif page == "Topology Editor":
        render_topology_editor()
    else:
        render_placeholder(page)


if __name__ == "__main__":
    main()
