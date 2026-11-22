"""AppTest coverage for the L3 Design page and IP-page L3 tabs."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from network.addressing.nat import NatType
from network.routing.ha import HaGroup, HaMember
from network.routing.ospf import OspfArea, OspfDesign
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.pages import l3_design as page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _page(twin=None) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    if twin is not None:
        at.session_state[state.TWIN_KEY] = twin
    at.run()
    open_page(at, "L3 Design")
    return at


def test_l3_design_requires_a_twin() -> None:
    at = _page()

    assert not at.exception
    assert at.title[0].value == "L3 Design"
    assert any(page.MODEL_NOTE in info.value for info in at.info)
    assert any("No digital twin" in info.value for info in at.info)
    assert not at.tabs


def test_l3_design_shows_five_tabs_and_editors() -> None:
    at = _page(make_twin())

    assert not at.exception
    assert [tab.label for tab in at.tabs] == [
        "IPv6 dual-stack",
        "NAT/PAT",
        "OSPF areas",
        "Gateway redundancy",
        "Findings",
    ]
    assert at.button(key=page.DUAL_STACK_APPLY_KEY)
    assert at.button(key=page.NAT_APPLY_KEY)
    assert at.button(key=page.OSPF_APPLY_KEY)
    assert at.button(key=page.HA_APPLY_KEY)
    assert at.data_editor(key=page.NAT_RULE_EDITOR_BASE)
    assert at.data_editor(key=page.OSPF_AREA_EDITOR_BASE)
    assert at.data_editor(key=page.HA_GROUP_EDITOR_BASE)


def test_l3_editors_store_bounded_models_on_the_twin() -> None:
    at = _page(make_twin())

    at.button(key=page.DUAL_STACK_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.ipv6_plan is not None
    assert twin.ipv6_plan.block == "fd00::/48"
    assert twin.ipv6_plan.prefixes_used == 2  # hand: users/10 and transit subnets

    at.button(key=page.NAT_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.nat_plan is not None
    assert twin.nat_plan.rules[0].nat_type is NatType.pat_overload
    assert twin.nat_plan.rules[0].inside_hosts == 254

    at.button(key=page.OSPF_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.ospf_design is not None
    assert twin.ospf_design.areas[0].area_id == 0

    at.button(key=page.HA_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert len(twin.ha_groups) == 1
    assert twin.ha_groups[0].members[0].device_id == "r1"
    assert twin.ha_groups[0].members[0].priority == 150


def test_l3_design_offers_explanations_for_stored_ospf_and_ha_models() -> None:
    twin = make_twin(
        ospf_design=OspfDesign(
            areas=(OspfArea(area_id=0, name="Backbone", device_ids=("r1", "r2")),)
        ),
        ha_groups=(
            HaGroup(
                id="gw-1",
                name="Gateway",
                virtual_ip="10.0.0.1",
                subnet="10.0.0.0/24",
                members=(
                    HaMember(device_id="r1", priority=150),
                    HaMember(device_id="r2", priority=100),
                ),
            ),
        ),
    )
    at = _page(twin)

    assert not at.exception
    assert at.button(key=page.OSPF_WHY_KEY)
    assert at.button(key=page.HA_WHY_KEY)
    at.button(key=page.OSPF_WHY_KEY).click().run()
    assert not at.exception
    assert at.session_state["copilot_explanation_results"][page.OSPF_WHY_KEY].target.value == (
        "ospf_design"
    )


def test_ip_page_adds_dual_stack_and_nat_tabs() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    open_page(at, "IP Addressing & Subnetting")

    assert not at.exception
    assert [tab.label for tab in at.tabs] == [
        "CIDR calculator",
        "VLSM planner",
        "Subnet check",
        "Dual-stack planner",
        "NAT/PAT planner",
    ]
