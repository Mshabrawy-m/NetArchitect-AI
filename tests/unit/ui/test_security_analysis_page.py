"""AppTest coverage for the Phase 14d Security Analysis page."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config.limits import MAX_SECURITY_FLOW_CHECKS
from security import SECURITY_DISCLAIMER, FlowRequest, Protocol, get_security_model
from tests.unit.security.design_helpers import case_design, hardened_design
from ui import state
from ui.pages import security_analysis as page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _page(twin=None) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    if twin is not None:
        at.session_state[state.TWIN_KEY] = twin
    at.run()
    at.selectbox(key="page_nav").select("Security Analysis").run()
    return at


def test_security_analysis_requires_a_twin() -> None:
    at = _page()

    assert not at.exception
    assert at.title[0].value == "Security Analysis"
    assert any(info.value == SECURITY_DISCLAIMER for info in at.info)
    assert any("No digital twin with a topology" in info.value for info in at.info)
    assert any("Topology Editor" in info.value for info in at.info)
    assert not at.tabs
    assert not at.download_button


def test_security_analysis_shows_five_tabs_and_exact_disclaimer() -> None:
    twin, _ = hardened_design()
    at = _page(twin)

    assert not at.exception
    assert [tab.label for tab in at.tabs] == [
        "Zones",
        "Policy",
        "Flow check",
        "Findings",
        "Templates",
    ]
    assert any(info.value == SECURITY_DISCLAIMER for info in at.info)
    assert at.button(key=page.ZONE_APPLY_KEY)
    assert at.button(key=page.POLICY_APPLY_KEY)
    assert at.button(key=page.FLOW_ADD_KEY)
    assert at.download_button(key=page.TEMPLATE_DOWNLOAD_KEY)
    assert at.download_button(key=page.ANALYSIS_DOWNLOAD_KEY)


def test_security_analysis_adds_a_bounded_modeled_flow_check() -> None:
    twin, _ = hardened_design()
    at = _page(twin)

    at.session_state[page.FLOW_ID_KEY] = "user-to-mgmt"
    at.session_state[page.FLOW_SOURCE_KEY] = "user-sw"
    at.session_state[page.FLOW_DESTINATION_KEY] = "mgmt-sw"
    at.session_state[page.FLOW_PROTOCOL_KEY] = "tcp"
    at.session_state[page.FLOW_PORT_KEY] = 80
    at.button(key=page.FLOW_ADD_KEY).click().run()

    assert not at.exception
    flows = at.session_state[state.SECURITY_FLOWS_KEY]
    assert [item.id for item in flows] == ["user-to-mgmt"]
    assert flows[0].protocol is Protocol.tcp
    assert flows[0].port == 80
    assert at.selectbox(key=page.FLOW_REMOVE_KEY)

    at.button(key=page.FLOW_REMOVE_BUTTON_KEY).click().run()

    assert not at.exception
    assert at.session_state[state.SECURITY_FLOWS_KEY] == ()


def test_security_analysis_applies_a_valid_zone_edit() -> None:
    twin, _ = hardened_design()
    at = _page(twin)

    at.session_state[page.ZONE_EDITOR_BASE] = {
        "edited_rows": {},
        "added_rows": [
            {
                "id": "z-new",
                "name": "Review zone",
                "type": "other",
                "criticality": 2,
                "member_vlan_ids": "99",
                "member_device_ids": "",
                "expected_hosts": None,
            }
        ],
        "deleted_rows": [],
    }
    at.button(key=page.ZONE_APPLY_KEY).click().run()

    assert not at.exception
    assert not at.error
    stored = at.session_state[state.TWIN_KEY]
    assert stored is not twin
    assert "z-new" in {zone.id for zone in get_security_model(stored).zones}


def test_rejected_zone_edit_resets_the_versioned_editor() -> None:
    twin, _ = hardened_design()
    at = _page(twin)

    at.session_state[page.ZONE_EDITOR_BASE] = {
        "edited_rows": {},
        "added_rows": [
            {
                "id": "z-user",
                "name": "Duplicate",
                "type": "user",
                "criticality": 3,
                "member_vlan_ids": "99",
                "member_device_ids": "",
                "expected_hosts": None,
            }
        ],
        "deleted_rows": [],
    }
    at.button(key=page.ZONE_APPLY_KEY).click().run()

    assert not at.exception
    assert any("Zone edits rejected" in error.value for error in at.error)
    assert at.session_state["editor_key_versions"][page.ZONE_EDITOR_BASE] == 1
    fresh = at.session_state.get(f"{page.ZONE_EDITOR_BASE}_v1", {})
    assert not fresh.get("edited_rows")
    assert not fresh.get("added_rows")
    assert len(get_security_model(at.session_state[state.TWIN_KEY]).zones) == 7


def test_rejected_policy_edit_resets_both_versioned_editors() -> None:
    twin, _ = hardened_design()
    at = _page(twin)

    at.session_state[page.RULE_EDITOR_BASE] = {
        "edited_rows": {},
        "added_rows": [
            {
                "id": "r-bad",
                "order": 99,
                "src_zone": "ghost",
                "dst_zone": "z-srv",
                "services": "any",
                "any_service": True,
                "action": "deny",
                "enabled": True,
                "note": "",
            }
        ],
        "deleted_rows": [],
    }
    at.button(key=page.POLICY_APPLY_KEY).click().run()

    assert not at.exception
    assert any("Policy edits rejected" in error.value for error in at.error)
    versions = at.session_state["editor_key_versions"]
    assert versions[page.SERVICE_EDITOR_BASE] == 1
    assert versions[page.RULE_EDITOR_BASE] == 1
    assert len(get_security_model(at.session_state[state.TWIN_KEY]).rules) == 12


def test_security_proposals_are_applied_only_on_explicit_acceptance() -> None:
    twin, _ = case_design("SEC-DW-004")
    at = _page(twin)

    assert at.session_state[state.TWIN_KEY] is twin
    options = list(at.multiselect(key=page.PROPOSAL_SELECT_KEY).options)
    assert options

    at.multiselect(key=page.PROPOSAL_SELECT_KEY).set_value(options).run()
    at.button(key=page.APPLY_PROPOSALS_KEY).click().run()

    assert not at.exception
    updated = at.session_state[state.TWIN_KEY]
    assert updated is not twin
    rule_ids = {rule.id for rule in get_security_model(updated).rules}
    assert set(options) <= rule_ids


def test_security_flow_accessors_are_typed_and_bounded() -> None:
    state.clear_security_flows()
    try:
        for index in range(MAX_SECURITY_FLOW_CHECKS):
            state.add_security_flow(
                FlowRequest(
                    id=f"flow-{index}",
                    source_device_id="a",
                    destination_device_id="b",
                    protocol=Protocol.tcp,
                    port=80,
                )
            )
        assert len(state.peek_security_flows()) == MAX_SECURITY_FLOW_CHECKS

        with pytest.raises(ValueError, match="session limit"):
            state.add_security_flow(
                FlowRequest(
                    id="overflow",
                    source_device_id="a",
                    destination_device_id="b",
                    protocol=Protocol.tcp,
                    port=80,
                )
            )
        with pytest.raises(TypeError, match="FlowRequest"):
            state.add_security_flow("not-a-flow")  # type: ignore[arg-type]

        state.set_security_flows(("bad", *state.get_security_flows()))  # type: ignore[arg-type]
        assert len(state.get_security_flows()) == MAX_SECURITY_FLOW_CHECKS
    finally:
        state.clear_security_flows()


def test_security_templates_are_disclosed_and_data_only() -> None:
    twin, _ = hardened_design()
    at = _page(twin)

    assert not at.exception
    assert at.download_button(key=page.TEMPLATE_DOWNLOAD_KEY)
    assert at.download_button(key=page.ANALYSIS_DOWNLOAD_KEY)
    assert any(info.value == SECURITY_DISCLAIMER for info in at.info)
