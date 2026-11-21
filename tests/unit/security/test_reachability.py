"""S1: deterministic policy reachability and bounded blast-radius tests."""

from __future__ import annotations

import pytest

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from security import (
    POLICY_REACHABILITY_NOTE,
    SECURITY_DISCLAIMER,
    PolicyAction,
    ReachabilityReport,
    SecurityAnalysis,
    SecurityModel,
    ZoneType,
    analyze_design,
    build_reachability_report,
)
from tests.unit.digital_twin.helpers import make_twin

from .helpers import make_rule, make_service, make_zone


def _chain_twin():
    """Return a twin whose four zone devices form a routed chain."""
    topology = Topology(
        name="Four-zone chain",
        devices=[
            Device(id="d-ext", type=DeviceType.router, site="hq", role=DeviceRole.border),
            Device(id="d-guest", type=DeviceType.switch, site="hq", role=DeviceRole.access),
            Device(id="d-app", type=DeviceType.server, site="hq", role=DeviceRole.access),
            Device(id="d-db", type=DeviceType.server, site="hq", role=DeviceRole.access),
        ],
        links=[
            Link(id="l1", endpoints=("d-ext", "d-guest"), capacity_mbps=1000.0, cost=1.0),
            Link(id="l2", endpoints=("d-guest", "d-app"), capacity_mbps=1000.0, cost=1.0),
            Link(id="l3", endpoints=("d-app", "d-db"), capacity_mbps=1000.0, cost=1.0),
        ],
    )
    return make_twin(topology=topology, demands=())


def _four_zone_model():
    return SecurityModel(
        zones=(
            make_zone("z-ext", zone_type=ZoneType.untrusted_external, device_id="d-ext", criticality=2),
            make_zone("z-guest", zone_type=ZoneType.guest, device_id="d-guest", criticality=2),
            make_zone("z-app", zone_type=ZoneType.server, device_id="d-app", criticality=4),
            make_zone("z-db", zone_type=ZoneType.server, device_id="d-db", criticality=5),
        ),
        services=(make_service("http"),),
        rules=(
            make_rule("ext-guest", order=0, src_zone="z-ext", dst_zone="z-guest"),
            make_rule("guest-app", order=1, src_zone="z-guest", dst_zone="z-app"),
            make_rule("app-db", order=2, src_zone="z-app", dst_zone="z-db"),
        ),
        default_action=PolicyAction.deny,
    )


def test_four_zone_matrix_shape_and_policy_cells() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    report = build_reachability_report(twin, model)

    assert report.matrix.zones == ("z-ext", "z-guest", "z-app", "z-db")
    assert report.matrix.services == ("http",)
    assert len(report.matrix.cells) == 4 * 4 * 1
    assert report.matrix.is_reachable("z-ext", "z-guest", "http")
    assert not report.matrix.is_reachable("z-ext", "z-app", "http")
    cell = report.matrix.cell("z-ext", "z-app", "http")
    assert cell is not None and cell.policy_permitted is False
    assert "No rule matched" in cell.reason
    assert report.disclaimer == SECURITY_DISCLAIMER
    assert report.note == POLICY_REACHABILITY_NOTE


def test_transitive_closure_blast_radius() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    report = build_reachability_report(twin, model)
    radii = {item.origin_zone: item for item in report.blast_radii}

    ext = radii["z-ext"]
    assert ext.directly_reachable == ("z-guest",)
    assert ext.closure_zones == ("z-app", "z-db", "z-guest")
    assert ext.hop_count == 3
    assert ext.max_criticality_reached == 5
    assert ext.exposure is True
    # A server zone is not highlighted even though it reaches high criticality.
    assert radii["z-app"].exposure is False
    assert radii["z-db"].closure_zones == ()


def test_deny_rule_removes_reachability_and_blast_radius() -> None:
    twin, model = _chain_twin(), _four_zone_model()
    deny_first = make_rule(
        "deny-ext-guest",
        order=0,
        src_zone="z-ext",
        dst_zone="z-guest",
        action=PolicyAction.deny,
    )
    rest = tuple(rule.model_copy(update={"order": rule.order + 1}) for rule in model.rules)
    model = model.model_copy(update={"rules": (deny_first, *rest)})

    report = build_reachability_report(twin, model)
    radii = {item.origin_zone: item for item in report.blast_radii}

    assert not report.matrix.is_reachable("z-ext", "z-guest", "http")
    assert radii["z-ext"].closure_zones == ()
    assert radii["z-ext"].exposure is False
    assert report.matrix.is_reachable("z-guest", "z-app", "http")


def test_routing_absent_blocks_reachability() -> None:
    topology = Topology(
        name="Disconnected",
        devices=[
            Device(id="d-a", type=DeviceType.router, site="hq", role=DeviceRole.border),
            Device(id="d-b", type=DeviceType.server, site="hq", role=DeviceRole.access),
        ],
        links=(),
    )
    twin = make_twin(topology=topology, demands=())
    model = SecurityModel(
        zones=(
            make_zone("z-ext", zone_type=ZoneType.untrusted_external, device_id="d-a", criticality=2),
            make_zone("z-critical", zone_type=ZoneType.server, device_id="d-b", criticality=5),
        ),
        services=(make_service("http"),),
        rules=(make_rule("allow", src_zone="z-ext", dst_zone="z-critical"),),
        default_action=PolicyAction.deny,
    )

    report = build_reachability_report(twin, model)
    cell = report.matrix.cell("z-ext", "z-critical", "http")

    assert cell is not None and cell.policy_permitted is True
    assert cell.route_exists is False and cell.routing_modeled is True
    assert cell.reachable is False
    assert report.blast_radii[0].exposure is False


def test_exposure_findings_and_hop_limit() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    report = build_reachability_report(twin, model, hop_limit=1)
    radii = {item.origin_zone: item for item in report.blast_radii}

    assert radii["z-ext"].closure_zones == ("z-guest",)
    assert radii["z-ext"].hop_count == 1
    assert all(item.disclaimer == SECURITY_DISCLAIMER for item in report.exposure_findings)
    assert {item.code for item in report.exposure_findings} == {
        "REACH-EXPOSURE-HIGH-CRITICALITY"
    }
    assert "not an attack path" in report.exposure_findings[0].explanation


def test_analysis_integration_and_legacy_json() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    analysis = analyze_design(twin, model=model)
    assert isinstance(analysis.reachability, ReachabilityReport)
    assert analysis.disclaimer == SECURITY_DISCLAIMER

    payload = analysis.model_dump()
    payload.pop("reachability")
    legacy = SecurityAnalysis.model_validate(payload)
    assert legacy.reachability is None
    assert legacy.model_dump_json() == SecurityAnalysis.model_validate(
        legacy.model_dump()
    ).model_dump_json()


@pytest.mark.perf
def test_s1_max_zone_count_timing() -> None:
    """Measure the full matrix at the maximum zone/service counts."""
    from time import perf_counter

    from config.limits import MAX_SERVICES, MAX_ZONES

    zones = tuple(
        make_zone(
            f"z-{index}",
            zone_type=ZoneType.server,
            vlan_id=index + 1,
            criticality=4,
        )
        for index in range(MAX_ZONES)
    )
    services = tuple(
        make_service(f"svc-{index}", port_start=1000 + index, port_end=1000 + index)
        for index in range(MAX_SERVICES)
    )
    model = SecurityModel(
        zones=zones,
        services=services,
        default_action=PolicyAction.allow,
    )
    twin = make_twin(demands=())

    started = perf_counter()
    report = build_reachability_report(twin, model)
    elapsed = perf_counter() - started

    print(f"S1 max-zone reachability ({MAX_ZONES} zones, {MAX_SERVICES} services): {elapsed:.3f}s")
    assert len(report.matrix.cells) == MAX_ZONES * MAX_ZONES * MAX_SERVICES
    assert elapsed < 15.0, f"max-zone reachability took {elapsed:.3f}s"
