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
page. V2 adds grouped navigation and a shared design system; the 15 engineering
page render functions remain in ``ui/pages``.
"""

from __future__ import annotations

import streamlit as st

from ui.navigation import PAGE_SPECS, build_navigation
from ui.progress import render_progress

# Page modules are imported by app_pages/ when selected. The Dashboard is the
# default page, so cold start must not import the report, export, agent, or
# other rarely used page modules.

PAGES: tuple[str, ...] = tuple(spec.title for spec in PAGE_SPECS)
READY_PAGES: frozenset[str] = frozenset(PAGES)


def main() -> None:
    """Build navigation and run the selected application page."""
    st.set_page_config(
        page_title="NetArchitect AI",
        page_icon=":material/hub:",
        layout="wide",
        menu_items={
            "About": (
                "NetArchitect AI v1.0.0-rc1 - deterministic, design-time "
                "network engineering. Results are modeled from the current "
                "twin and stated assumptions. No device access, live scanning, "
                "or guaranteed outcomes. See Settings > Release limitations."
            ),
        },
    )

    page = st.navigation(build_navigation(), position="sidebar")
    with st.sidebar:
        st.caption("NetArchitect AI - deterministic network engineering first.")
    render_progress()
    page.run()


if __name__ == "__main__":
    main()
