"""AppTest smoke tests for the Phase 4 planning pages."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.schemas.validation import ValidationReport
from network.addressing import SubnetInfo, VlsmResult
from network.vlan import VlanPlanResult
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def test_ip_addressing_page_calculates_and_validates() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("IP Addressing & Subnetting").run()
    assert not at.exception

    at.button(key="ip_cidr_calculate").click().run()
    assert not at.exception
    cidr = at.session_state["ip_cidr_result"]
    assert isinstance(cidr, SubnetInfo)
    assert str(cidr.network) == "192.168.1.0/24"
    assert cidr.usable_host_count == 254

    at.button(key="vlsm_allocate").click().run()
    assert not at.exception
    vlsm = at.session_state["addressing_result"]
    assert isinstance(vlsm, VlsmResult)
    assert [str(item.network) for item in vlsm.allocations] == [
        "192.168.1.0/25",
        "192.168.1.128/26",
        "192.168.1.192/27",
        "192.168.1.224/28",
        "192.168.1.240/29",
    ]
    twin = at.session_state[state.TWIN_KEY]
    assert twin.addressing is not None
    assert [str(subnet.network) for subnet in twin.addressing.subnets] == [
        "192.168.1.0/25",
        "192.168.1.128/26",
        "192.168.1.192/27",
        "192.168.1.224/28",
        "192.168.1.240/29",
    ]

    at.button(key="subnet_check_run").click().run()
    assert not at.exception
    report = at.session_state["addressing_check_report"]
    assert isinstance(report, ValidationReport)
    assert report.is_valid is False
    assert any(finding.code == "subnet_overlap" for finding in report.findings)

    assert at.get("dataframe")
    assert at.get("download_button")


def test_vlan_dhcp_page_builds_default_plan() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("VLAN & DHCP Planner").run()
    assert not at.exception

    at.button(key="vlan_build_plan").click().run()
    assert not at.exception

    twin = at.session_state[state.TWIN_KEY]
    plan = twin.vlan_plan
    scopes = twin.dhcp_scopes
    assert isinstance(plan, VlanPlanResult)
    assert len(plan.assignments) == 5
    assert len(scopes) == 5
    assert [assignment.vlan_id for assignment in plan.assignments] == [
        10,
        11,
        12,
        13,
        14,
    ]
    assert all(
        scope.gateway == scope.network.network_address + 1 for scope in scopes
    )
    assert twin.addressing is not None
    assert [vlan.vlan_id for vlan in twin.addressing.vlan_plans] == [
        10,
        11,
        12,
        13,
        14,
    ]
    assert not at.exception
    assert at.get("dataframe")
    assert at.get("download_button")


def test_vlan_dhcp_page_reports_invalid_parent() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("VLAN & DHCP Planner").run()
    at.text_input(key="vlan_parent").set_value("not-an-ip/16").run()
    at.button(key="vlan_build_plan").click().run()

    assert not at.exception
    assert at.error
    assert state.TWIN_KEY not in at.session_state
