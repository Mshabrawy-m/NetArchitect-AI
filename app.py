"""NetArchitect AI - Streamlit entry point.

Phase 1: minimal skeleton with a sidebar navigation placeholder. No page
routing logic is implemented yet; functional pages are introduced
progressively in later phases.
"""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings

# The 14 planned application pages from the blueprint (section 7).
# "Dashboard" is the current view; the rest are placeholders.
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


def render_sidebar_navigation() -> None:
    """Render the sidebar navigation placeholder.

    Lists the planned pages. The current view (Dashboard) is emphasized;
    every other page is marked as coming soon. This is a placeholder only.
    """
    with st.sidebar:
        st.markdown("## Navigation")
        for index, page in enumerate(PAGES, start=1):
            if page == "Dashboard":
                st.markdown(f"**{index}. {page}**  \n_(current view)_")
            else:
                st.markdown(f"{index}. {page}  \n_(coming soon)_")


def main() -> None:
    """Render the Phase 1 startup page."""
    st.set_page_config(
        page_title="NetArchitect AI",
        page_icon=":gear:",
        layout="wide",
        menu_items={
            "About": (
                "NetArchitect AI - agentic network architecture, digital "
                "twin, and multi-objective optimization platform."
            ),
        },
    )

    render_sidebar_navigation()

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
        "Phase 1 - Project Foundation and Environment. This page is the "
        "application entry point; functional pages are introduced "
        "progressively in later phases."
    )


if __name__ == "__main__":
    main()
