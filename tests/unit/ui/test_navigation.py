"""Navigation coverage for every page in the sidebar."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import PAGES
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.navigation import NAVIGATION_GROUPS, PAGE_SPECS

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"

_PLACEHOLDER_WORDS = ("coming soon", "later phase", "will be implemented")


def test_navigation_has_fifteen_declared_pages() -> None:
    assert len(PAGES) == 15
    assert PAGES[0] == "Dashboard"
    assert "Security Analysis" in PAGES
    assert "Settings" == PAGES[-1]


def test_navigation_groups_match_the_product_spec() -> None:
    assert tuple(NAVIGATION_GROUPS) == ("", "Design", "Analyze", "Operate", "Output")
    assert [spec.label for spec in NAVIGATION_GROUPS[""]] == ["Dashboard"]
    assert [spec.label for spec in NAVIGATION_GROUPS["Design"]] == [
        "AI Designer",
        "Topology",
        "IP",
        "VLAN/DHCP",
    ]
    assert [spec.label for spec in NAVIGATION_GROUPS["Analyze"]] == [
        "Routing",
        "Analytics",
        "Security",
    ]
    assert [spec.label for spec in NAVIGATION_GROUPS["Operate"]] == [
        "Digital Twin",
        "Simulation",
        "Optimization",
        "Capacity",
    ]
    assert [spec.label for spec in NAVIGATION_GROUPS["Output"]] == [
        "Reports",
        "Agent Center",
        "Settings",
    ]
    assert sum(len(specs) for specs in NAVIGATION_GROUPS.values()) == len(PAGE_SPECS)


def test_legacy_selectbox_navigation_is_absent() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    assert not at.exception
    assert not any(widget.key == "page_nav" for widget in at.selectbox)


def _visible_text(at: AppTest) -> str:
    groups = (
        at.title,
        at.header,
        at.subheader,
        at.caption,
        at.info,
        at.warning,
        at.error,
        at.success,
    )
    return " ".join(
        element.value
        for group in groups
        for element in group
    ).lower()


@pytest.mark.parametrize("page", PAGES)
def test_every_nav_page_loads_without_a_twin(page: str) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    assert not at.exception

    open_page(at, page)

    assert not at.exception
    assert at.title[0].value == page
    assert not any(word in _visible_text(at) for word in _PLACEHOLDER_WORDS)


@pytest.mark.parametrize("page", PAGES)
def test_every_nav_page_loads_with_a_twin(page: str) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at.session_state[state.TWIN_KEY] = make_twin()
    open_page(at, page)

    assert not at.exception
    assert at.title[0].value == page
    assert not any(word in _visible_text(at) for word in _PLACEHOLDER_WORDS)
