"""Unit tests for the deterministic abstract wireless planning engine."""

from __future__ import annotations

from core.schemas.validation import Severity
from network.wireless.models import WirelessArea, WirelessDesign
from network.wireless.planning import (
    ASSUMPTIONS,
    CAPACITY_FORMULA,
    COVERAGE_FORMULA,
    FORMULAS,
    NO_RF_NOTE,
    UPLINK_FORMULA,
    WirelessAreaPlan,
    analyze_wireless_design,
    plan_wireless_area,
)


def _codes(plan: object) -> set[str]:
    return {finding.code for finding in plan.findings}  # type: ignore[attr-defined]


def test_capacity_binding_plan() -> None:
    area = WirelessArea(
        id="floor-1",
        name="Floor 1",
        area_m2=1000,
        clients=200,
        client_mbps=10,
        ap_capacity_mbps=100,
        utilization_target=0.5,
    )

    # Capacity: ceil(200 * 10 / (100 * 0.5)) = ceil(2000 / 50) = 40 APs.
    # Coverage: ceil(1000 / (pi * 20^2 * 0.8)) = ceil(1000 / 1005.3096)
    #           = ceil(0.9947) = 1 AP.
    # Uplink:   40 * 100 * 0.5 = 2000 Mbps.
    plan = plan_wireless_area(area)

    assert isinstance(plan, WirelessAreaPlan)
    assert plan.area_id == "floor-1"
    assert plan.area_name == "Floor 1"
    assert plan.effective_clients == 200
    assert plan.capacity_ap_count == 40
    assert plan.coverage_ap_count == 1
    assert plan.recommended_ap_count == 40
    assert plan.binding_constraint == "capacity"
    assert plan.uplink_required_mbps == 2000.0
    assert plan.uplink_switch_id is None


def test_coverage_binding_plan() -> None:
    area = WirelessArea(
        id="hall",
        area_m2=10000,
        clients=10,
        client_mbps=10,
        ap_capacity_mbps=1000,
        utilization_target=1,
        coverage_radius_m=10,
        overlap_factor=0.5,
    )

    # Capacity: ceil(10 * 10 / (1000 * 1)) = ceil(100 / 1000) = 1 AP.
    # Coverage: ceil(10000 / (pi * 10^2 * 0.5)) = ceil(10000 / 157.0796)
    #           = ceil(63.662) = 64 APs.
    # Uplink:   64 * 1000 * 1 = 64000 Mbps.
    plan = plan_wireless_area(area)

    assert plan.effective_clients == 10
    assert plan.capacity_ap_count == 1
    assert plan.coverage_ap_count == 64
    assert plan.recommended_ap_count == 64
    assert plan.binding_constraint == "coverage"
    assert plan.uplink_required_mbps == 64000.0


def test_empty_design_has_one_no_demand_info_and_zero_totals() -> None:
    for design in (None, WirelessDesign()):
        analysis = analyze_wireless_design(design)

        assert analysis.plans == ()
        assert analysis.total_recommended_aps == 0
        assert analysis.total_uplink_required_mbps == 0.0
        assert len(analysis.findings) == 1
        finding = analysis.findings[0]
        assert finding.code == "wireless_no_modeled_demand"
        assert finding.severity is Severity.info
        assert finding.affected_entities == []
        assert not any(item.severity is Severity.error for item in analysis.findings)


def test_density_derivation_does_not_enumerate_clients() -> None:
    area = WirelessArea(
        id="density",
        area_m2=500,
        clients=0,
        client_density_per_100m2=40,
        client_mbps=10,
        ap_capacity_mbps=100,
        utilization_target=0.5,
    )

    # Clients:  ceil(500 / 100 * 40) = ceil(200) = 200 modeled clients.
    # Capacity: ceil(200 * 10 / (100 * 0.5)) = ceil(2000 / 50) = 40 APs.
    # Coverage: ceil(500 / (pi * 20^2 * 0.8)) = ceil(0.4974) = 1 AP.
    # Uplink:   40 * 100 * 0.5 = 2000 Mbps.
    plan = plan_wireless_area(area)

    assert plan.effective_clients == 200
    assert plan.capacity_ap_count == 40
    assert plan.coverage_ap_count == 1
    assert plan.recommended_ap_count == 40
    assert plan.binding_constraint == "capacity"
    assert plan.uplink_required_mbps == 2000.0


def test_zero_and_tied_demand_name_none_constraint() -> None:
    empty = plan_wireless_area(WirelessArea(id="empty"))

    # No area and no clients: 0 effective clients, 0 capacity APs, 0 coverage APs.
    assert empty.effective_clients == 0
    assert empty.capacity_ap_count == 0
    assert empty.coverage_ap_count == 0
    assert empty.recommended_ap_count == 0
    assert empty.binding_constraint == "none"
    assert empty.uplink_required_mbps == 0.0

    tied = plan_wireless_area(
        WirelessArea(
            id="tied",
            area_m2=1000,
            clients=5,
            client_mbps=10,
            ap_capacity_mbps=100,
            utilization_target=1,
        )
    )

    # Capacity: ceil(5 * 10 / (100 * 1)) = 1 AP.
    # Coverage: ceil(1000 / (pi * 400 * 0.8)) = ceil(0.9947) = 1 AP.
    assert tied.capacity_ap_count == 1
    assert tied.coverage_ap_count == 1
    assert tied.recommended_ap_count == 1
    assert tied.binding_constraint == "none"
    assert tied.uplink_required_mbps == 100.0

    empty_analysis = analyze_wireless_design(
        WirelessDesign(areas=(WirelessArea(id="empty"),))
    )
    assert _codes(empty_analysis) == {"wireless_no_modeled_demand"}
    assert empty_analysis.findings[0].affected_entities == ["empty"]

    tied_area = WirelessArea(
        id="tied",
        area_m2=1000,
        clients=5,
        ap_capacity_mbps=100,
        utilization_target=1,
    )
    tied_analysis = analyze_wireless_design(WirelessDesign(areas=(tied_area,)))
    assert tied_analysis.findings == ()


def test_design_round_trip_and_exact_strings() -> None:
    capacity_area = WirelessArea(
        id="z-capacity",
        area_m2=1000,
        clients=200,
        client_mbps=10,
        ap_capacity_mbps=100,
        utilization_target=0.5,
        uplink_switch_id="sw-1",
    )
    coverage_area = WirelessArea(
        id="a-coverage",
        area_m2=10000,
        clients=10,
        client_mbps=10,
        ap_capacity_mbps=1000,
        utilization_target=1,
        coverage_radius_m=10,
        overlap_factor=0.5,
    )
    design = WirelessDesign(areas=(capacity_area, coverage_area))
    analysis = analyze_wireless_design(design)

    # Totals: 40 + 64 = 104 APs; 2000 + 64000 = 66000 Mbps.
    assert analysis.total_recommended_aps == 104
    assert analysis.total_uplink_required_mbps == 66000.0
    assert [plan.area_id for plan in analysis.plans] == ["z-capacity", "a-coverage"]
    assert [plan.binding_constraint for plan in analysis.plans] == [
        "capacity",
        "coverage",
    ]
    assert analysis.plans[0].uplink_switch_id == "sw-1"
    assert _codes(analysis) == {"wireless_capacity_binding", "wireless_coverage_binding"}
    for finding in analysis.findings:
        assert finding.severity is Severity.info
        assert finding.affected_entities == sorted(finding.affected_entities)

    assert CAPACITY_FORMULA == "ceil(clients * client_mbps / (ap_capacity_mbps * utilization_target))"
    assert COVERAGE_FORMULA == "ceil(area_m2 / (pi * coverage_radius_m^2 * overlap_factor))"
    assert UPLINK_FORMULA == "recommended_ap_count * ap_capacity_mbps * utilization_target"
    assert NO_RF_NOTE == (
        "Modeled estimate from stated area/capacity assumptions; "
        "no RF propagation or signal modeling."
    )

    for plan in analysis.plans:
        assert plan.formulas == FORMULAS
        assert plan.assumptions == ASSUMPTIONS
        assert CAPACITY_FORMULA in plan.formulas[0]
        assert COVERAGE_FORMULA in plan.formulas[1]
        assert UPLINK_FORMULA in plan.formulas[2]
        assert NO_RF_NOTE in plan.assumptions
        for text in (*plan.formulas, *plan.assumptions):
            assert "modeled estimate" in text.lower()
            assert not any(
                term in text.lower()
                for term in ("rssi", "dbm", "snr", "signal strength")
            )

    restored = WirelessDesign.model_validate_json(design.model_dump_json())
    assert analyze_wireless_design(restored) == analysis
