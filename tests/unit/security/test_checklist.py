"""S5: fixed versioned design checklist status tests."""

from __future__ import annotations

from security import (
    DESIGN_CHECKLIST_VERSION,
    SECURITY_DISCLAIMER,
    ChecklistStatus,
    DesignChecklist,
    FlowRequest,
    PolicyAction,
    Protocol,
    SecurityAnalysis,
    SecurityModel,
    ZoneType,
    analyze_design,
)
from tests.unit.digital_twin.helpers import make_twin

from .helpers import make_rule, make_zone
from .test_reachability import _chain_twin, _four_zone_model

_FLOW_ALLOWED = FlowRequest(
    id="allowed",
    source_device_id="d-ext",
    destination_device_id="d-guest",
    protocol=Protocol.tcp,
    port=80,
)
_FLOW_DENIED = FlowRequest(
    id="denied",
    source_device_id="d-db",
    destination_device_id="d-ext",
    protocol=Protocol.tcp,
    port=80,
)


def _item(analysis, identifier: str):
    return next(item for item in analysis.checklist.items if item.id == identifier)


def _status(analysis, identifier: str) -> ChecklistStatus:
    return _item(analysis, identifier).status


def test_checklist_is_fixed_versioned_and_disclosed() -> None:
    analysis = analyze_design(_chain_twin(), model=_four_zone_model())

    checklist = analysis.checklist
    assert isinstance(checklist, DesignChecklist)
    assert checklist.version == DESIGN_CHECKLIST_VERSION == "1.0"
    assert [item.id for item in checklist.items] == [f"CHK-{index:02d}" for index in range(1, 9)]
    assert all(item.disclaimer == SECURITY_DISCLAIMER for item in checklist.items)
    assert checklist.disclaimer == SECURITY_DISCLAIMER
    assert "aligned with common practice (design-level)" in checklist.note
    assert "compliance" in checklist.note.lower()
    assert (
        checklist.pass_count + checklist.fail_count + checklist.not_modeled_count
        == len(checklist.items)
    )


def test_chk01_default_action_status() -> None:
    twin, model = _chain_twin(), _four_zone_model()
    assert _status(analyze_design(twin, model=model), "CHK-01") is ChecklistStatus.pass_

    allowed = model.model_copy(update={"default_action": PolicyAction.allow})
    analysis = analyze_design(twin, model=allowed)
    assert _status(analysis, "CHK-01") is ChecklistStatus.fail
    assert "POLICY-DEFAULT-ALLOW" in _item(analysis, "CHK-01").rule_linkage


def test_chk02_device_assignment_status() -> None:
    twin = _chain_twin()

    assert _status(analyze_design(twin, model=_four_zone_model()), "CHK-02") is ChecklistStatus.pass_
    assert _status(analyze_design(twin, model=SecurityModel()), "CHK-02") is ChecklistStatus.fail
    empty_twin = make_twin(
        topology=twin.topology.model_copy(update={"devices": [], "links": []}),
        demands=(),
    )
    assert (
        _status(analyze_design(empty_twin, model=_four_zone_model()), "CHK-02")
        is ChecklistStatus.not_modeled
    )


def test_chk03_any_service_allow_status() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    assert _status(analyze_design(twin, model=model), "CHK-03") is ChecklistStatus.pass_

    any_allow = model.model_copy(
        update={
            "rules": model.rules
            + (
                make_rule(
                    "any-allow",
                    order=10,
                    src_zone="z-ext",
                    dst_zone="z-db",
                    any_service=True,
                    services=(),
                ),
            )
        }
    )
    analysis = analyze_design(twin, model=any_allow)
    assert _status(analysis, "CHK-03") is ChecklistStatus.fail
    assert "POLICY-ANY-ALLOW" in _item(analysis, "CHK-03").rule_linkage


def test_chk04_exposure_status_including_not_modeled() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    analysis = analyze_design(twin, model=model)
    assert _status(analysis, "CHK-04") is ChecklistStatus.fail
    assert "REACH-EXPOSURE-HIGH-CRITICALITY" in _item(analysis, "CHK-04").rule_linkage

    closed = model.model_copy(
        update={
            "rules": (
                make_rule(
                    "deny-guest-app",
                    order=0,
                    src_zone="z-guest",
                    dst_zone="z-app",
                    action=PolicyAction.deny,
                ),
            )
        }
    )
    assert _status(analyze_design(twin, model=closed), "CHK-04") is ChecklistStatus.pass_

    high_only = model.model_copy(
        update={
            "zones": tuple(
                zone for zone in model.zones if zone.type not in {ZoneType.untrusted_external, ZoneType.guest}
            )
        }
    )
    assert (
        _status(analyze_design(twin, model=high_only), "CHK-04")
        is ChecklistStatus.not_modeled
    )


def test_chk05_logging_is_always_not_modeled() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    for candidate in (model, SecurityModel()):
        item = _item(analyze_design(twin, model=candidate), "CHK-05")
        assert item.status is ChecklistStatus.not_modeled
        assert item.rule_linkage == ()
        assert "no logging field" in item.evidence[0]


def test_chk06_flow_status() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    assert _status(analyze_design(twin, model=model), "CHK-06") is ChecklistStatus.not_modeled
    assert (
        _status(analyze_design(twin, model=model, flows=(_FLOW_ALLOWED,)), "CHK-06")
        is ChecklistStatus.pass_
    )
    analysis = analyze_design(twin, model=model, flows=(_FLOW_DENIED,))
    assert _status(analysis, "CHK-06") is ChecklistStatus.fail
    assert "flows_checked=1" in _item(analysis, "CHK-06").evidence[0]


def test_chk07_high_criticality_separation_status() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    assert _status(analyze_design(twin, model=model), "CHK-07") is ChecklistStatus.fail

    separated = model.model_copy(
        update={
            "rules": model.rules
            + (
                make_rule(
                    "deny-app-db",
                    order=10,
                    src_zone="z-app",
                    dst_zone="z-db",
                    action=PolicyAction.deny,
                ),
                make_rule(
                    "deny-db-app",
                    order=11,
                    src_zone="z-db",
                    dst_zone="z-app",
                    action=PolicyAction.deny,
                ),
            )
        }
    )
    assert _status(analyze_design(twin, model=separated), "CHK-07") is ChecklistStatus.pass_

    single_high = model.model_copy(
        update={
            "zones": tuple(
                zone.model_copy(update={"criticality": 3}) if zone.id == "z-app" else zone
                for zone in model.zones
            )
        }
    )
    assert (
        _status(analyze_design(twin, model=single_high), "CHK-07")
        is ChecklistStatus.not_modeled
    )


def test_chk08_service_reference_status() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    assert _status(analyze_design(twin, model=SecurityModel()), "CHK-08") is ChecklistStatus.not_modeled
    assert _status(analyze_design(twin, model=model), "CHK-08") is ChecklistStatus.pass_

    broken = model.model_copy(
        update={
            "rules": (
                make_rule("unknown-service", src_zone="z-ext", dst_zone="z-app", services=("missing",)),
            )
        }
    )
    analysis = analyze_design(twin, model=broken)
    assert _status(analysis, "CHK-08") is ChecklistStatus.fail
    assert "unknown_service_refs=1" in _item(analysis, "CHK-08").evidence[0]


def test_legacy_json_and_freshness() -> None:
    analysis = analyze_design(_chain_twin(), model=_four_zone_model())

    payload = analysis.model_dump()
    payload.pop("checklist")
    legacy = SecurityAnalysis.model_validate(payload)
    assert legacy.checklist is None

    fresh = analyze_design(_chain_twin(), model=_four_zone_model())
    assert fresh.checklist == analysis.checklist


def test_make_zone_criticality_is_a_modeled_fact() -> None:
    zone = make_zone("z-test", criticality=4, vlan_id=99)
    assert zone.criticality == 4
