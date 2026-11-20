"""Declarative navigation structure for the Streamlit application.

The Dashboard is ungrouped and first. The four groups and their order are part
of the product design; page implementations stay in ``ui/pages`` and are
reached through thin files in ``app_pages`` so cold start stays lazy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

import streamlit as st


@dataclass(frozen=True)
class PageSpec:
    """One navigation entry and its canonical page title."""

    title: str
    label: str
    path: str
    icon: str
    help: str


PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec(
        "Dashboard",
        "Dashboard",
        "app_pages/dashboard.py",
        ":material/space_dashboard:",
        "Session overview: design health, retained runs, and sample projects.",
    ),
    PageSpec(
        "AI Network Designer",
        "AI Designer",
        "app_pages/ai_designer.py",
        ":material/architecture:",
        "Turn structured requirements into a deterministic design plan.",
    ),
    PageSpec(
        "Topology Editor",
        "Topology",
        "app_pages/topology.py",
        ":material/account_tree:",
        "Generate, edit, and inspect the current network topology.",
    ),
    PageSpec(
        "IP Addressing & Subnetting",
        "IP",
        "app_pages/ip_addressing.py",
        ":material/router:",
        "Plan CIDR blocks and VLSM subnets from the current design.",
    ),
    PageSpec(
        "VLAN & DHCP Planner",
        "VLAN/DHCP",
        "app_pages/vlan_dhcp.py",
        ":material/lan:",
        "Allocate VLANs and DHCP scopes from department requirements.",
    ),
    PageSpec(
        "Routing Analysis",
        "Routing",
        "app_pages/routing.py",
        ":material/route:",
        "Inspect reachability, shortest paths, and failure paths.",
    ),
    PageSpec(
        "Network Analytics",
        "Analytics",
        "app_pages/analytics.py",
        ":material/query_stats:",
        "Compute graph metrics and identify structural risks.",
    ),
    PageSpec(
        "Security Analysis",
        "Security",
        "app_pages/security.py",
        ":material/security:",
        "Model zones, policy, and design-time flow checks.",
    ),
    PageSpec(
        "Digital Twin",
        "Digital Twin",
        "app_pages/digital_twin.py",
        ":material/hub:",
        "Inspect and snapshot the single session model of the design.",
    ),
    PageSpec(
        "Simulation Lab",
        "Simulation",
        "app_pages/simulation.py",
        ":material/bolt:",
        "Evaluate deterministic what-if failures and demand changes.",
    ),
    PageSpec(
        "Optimization Center",
        "Optimization",
        "app_pages/optimization.py",
        ":material/tune:",
        "Search bounded trade-offs between cost, resilience, and capacity.",
    ),
    PageSpec(
        "Capacity Planning",
        "Capacity",
        "app_pages/capacity.py",
        ":material/speed:",
        "Project utilization and forecast capacity from bounded series.",
    ),
    PageSpec(
        "Reports & Documentation",
        "Reports",
        "app_pages/reports.py",
        ":material/description:",
        "Generate provenance-tagged reports and in-memory downloads.",
    ),
    PageSpec(
        "Agent Control Center",
        "Agent Center",
        "app_pages/agent_center.py",
        ":material/smart_toy:",
        "Review the deterministic agent trace and task outcomes.",
    ),
    PageSpec(
        "Settings",
        "Settings",
        "app_pages/settings.py",
        ":material/settings:",
        "Configure optional AI access and review session-only limits.",
    ),
)

NAVIGATION_GROUPS: MappingProxyType[str, tuple[PageSpec, ...]] = MappingProxyType(
    {
        "": tuple(spec for spec in PAGE_SPECS if spec.title == "Dashboard"),
        "Design": tuple(
            spec
            for spec in PAGE_SPECS
            if spec.title
            in {
                "AI Network Designer",
                "Topology Editor",
                "IP Addressing & Subnetting",
                "VLAN & DHCP Planner",
            }
        ),
        "Analyze": tuple(
            spec
            for spec in PAGE_SPECS
            if spec.title
            in {"Routing Analysis", "Network Analytics", "Security Analysis"}
        ),
        "Operate": tuple(
            spec
            for spec in PAGE_SPECS
            if spec.title
            in {
                "Digital Twin",
                "Simulation Lab",
                "Optimization Center",
                "Capacity Planning",
            }
        ),
        "Output": tuple(
            spec
            for spec in PAGE_SPECS
            if spec.title
            in {"Reports & Documentation", "Agent Control Center", "Settings"}
        ),
    }
)

PAGE_FILES: MappingProxyType[str, str] = MappingProxyType(
    {spec.title: spec.path for spec in PAGE_SPECS}
)


def build_navigation(
    *,
    label_for: Callable[[PageSpec], str] | None = None,
) -> dict[str, list[st.Page]]:
    """Build the grouped page mapping for ``st.navigation``."""
    label = label_for or (lambda spec: spec.label)
    return {
        group: [
            st.Page(
                spec.path,
                title=label(spec),
                icon=spec.icon,
                help=spec.help,
            )
            for spec in specs
        ]
        for group, specs in NAVIGATION_GROUPS.items()
    }


__all__ = [
    "NAVIGATION_GROUPS",
    "PAGE_FILES",
    "PAGE_SPECS",
    "PageSpec",
    "build_navigation",
]
