"""Tests for the unified design-health validation entry point."""

from __future__ import annotations

import pytest

from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.validation import Finding, Severity
from digital_twin import (
    TWIN_SCHEMA_VERSION,
    DeviceState,
    DigitalTwin,
    OperationalState,
    TwinMetadata,
)
from network.l2.models import LinkL2Mode
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.vlan import VlanAssignment, VlanPlanResult
from network.wan.models import WanLinkType
from network.wireless.models import WirelessArea, WirelessDesign
from services.validation import (
    CATEGORY_ORDER,
    SEVERITY_RANK,
    DesignHealth,
    ValidationCategory,
    build_design_health,
    categorize_design_finding,
)
from services.validation import health as health_module
from tests.unit.digital_twin.helpers import CREATED_AT, make_twin
from tests.unit.simulation.helpers import (
    line_twin,
    make_demand,
    make_link,
    make_topology,
)
from tests.unit.simulation.helpers import (
    make_twin as make_simulation_twin,
)


def _schema_twin() -> DigitalTwin:
    return make_twin(
        metadata=TwinMetadata(
            name="Unsupported schema",
            created_at=CREATED_AT,
            schema_version=TWIN_SCHEMA_VERSION + 1,
        )
    )


def _topology_twin() -> DigitalTwin:
    return make_simulation_twin(make_topology(["a", "b"], []))


def _addressing_twin() -> DigitalTwin:
    # A valid AddressingPlan rejects overlaps, so build the invalid state that a
    # corrupt import could produce and confirm validation still catches it.
    plan = AddressingPlan.model_construct(
        vlan_plans=[],
        subnets=[
            Subnet(name="users", network="10.0.0.0/24"),
            Subnet(name="voice", network="10.0.0.128/25"),
        ],
    )
    return DigitalTwin.model_construct(
        metadata=TwinMetadata(name="Overlap", created_at=CREATED_AT),
        topology=Topology(name="Overlap"),
        addressing=plan,
        vlan_plan=None,
        dhcp_scopes=(),
        demands=(),
        device_states=(),
        link_states=(),
        assumptions=(),
    )


def _vlan_twin() -> DigitalTwin:
    return make_twin(
        vlan_plan=VlanPlanResult(
            assignments=[
                VlanAssignment(
                    department="users",
                    vlan_id=10,
                    vlan_name="Users",
                    subnet_name="users",
                    network="10.9.0.0/24",
                    purpose="User access",
                )
            ]
        )
    )


def _dhcp_twin() -> DigitalTwin:
    return make_twin(
        dhcp_scopes=(
            DhcpScope(
                name="users DHCP",
                network="10.0.0.0/24",
                gateway="10.0.1.1",
                start_address="10.0.0.10",
                end_address="10.0.0.200",
                lease_minutes=1440,
            ),
        )
    )


def _routing_twin() -> DigitalTwin:
    topology = make_topology(
        ["a", "b", "c", "d"],
        [make_link("ab", "a", "b"), make_link("cd", "c", "d")],
    )
    return make_simulation_twin(
        topology,
        demands=(make_demand("a-to-d", "a", "d"),),
    )


def _capacity_twin() -> DigitalTwin:
    return line_twin(
        demands=(make_demand("bulk", "a", "c", bandwidth_mbps=250.0),)
    )


def _references_twin() -> DigitalTwin:
    return make_twin(
        device_states=(
            DeviceState(device_id="ghost", state=OperationalState.down),
        )
    )


def test_clean_twin_has_no_findings() -> None:
    health = build_design_health(make_twin())

    assert isinstance(health, DesignHealth)
    assert health.findings == ()
    assert health.is_valid
    assert health.summary == "No design-health findings."
    assert tuple(group.category for group in health.groups) == CATEGORY_ORDER
    assert all(group.findings == () for group in health.groups)


def test_schema_category_finding() -> None:
    health = build_design_health(_schema_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.schema
    )] == ["twin_schema_version_unsupported"]
    assert not health.is_valid


def test_topology_category_finding() -> None:
    health = build_design_health(_topology_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.topology
    )] == ["twin_topology_disconnected"]


def test_addressing_category_finding() -> None:
    health = build_design_health(_addressing_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.addressing
    )] == ["subnet_overlap"]


def test_vlan_category_finding() -> None:
    health = build_design_health(_vlan_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.vlan
    )] == ["twin_vlan_subnet_missing"]


def test_dhcp_category_finding() -> None:
    health = build_design_health(_dhcp_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.dhcp
    )] == ["dhcp_gateway_outside_subnet"]


def test_routing_category_finding() -> None:
    health = build_design_health(_routing_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.routing
    )] == ["routing_demand_unreachable"]


def test_capacity_category_finding() -> None:
    health = build_design_health(_capacity_twin())

    codes = [
        finding.code
        for finding in health.findings_for(ValidationCategory.capacity)
    ]
    assert codes == ["capacity_link_overloaded", "capacity_link_overloaded"]


def test_redundancy_category_requires_expensive_checks() -> None:
    twin = line_twin()

    basic = build_design_health(twin)
    assert basic.findings_for(ValidationCategory.redundancy) == ()
    assert basic.include_expensive is False

    expensive = build_design_health(twin, include_expensive=True)
    codes = {
        finding.code
        for finding in expensive.findings_for(ValidationCategory.redundancy)
    }
    assert codes == {"spof_device", "spof_link"}
    assert expensive.include_expensive is True
    assert any("Expensive checks add" in note for note in expensive.notes)


def test_constraints_category_finding() -> None:
    twin = line_twin(
        demands=(make_demand("bulk", "a", "c", bandwidth_mbps=60.0),)
    )

    health = build_design_health(
        twin,
        constraints=("Maximum link utilization 50%", "support future growth"),
    )

    findings = health.findings_for(ValidationCategory.constraints)
    codes = [finding.code for finding in findings]
    assert "constraint_max_utilization_violated" in codes
    assert "constraint_not_machine_checkable" in codes
    assert all(finding.remediation for finding in findings)


def test_references_category_finding() -> None:
    health = build_design_health(_references_twin())

    assert [finding.code for finding in health.findings_for(
        ValidationCategory.references
    )] == ["twin_unknown_device_state"]


def test_findings_are_severity_sorted_and_groups_are_ordered() -> None:
    twin = line_twin(
        demands=(make_demand("bulk", "a", "c", bandwidth_mbps=250.0),)
    ).model_copy(
        update={
            "device_states": (
                DeviceState(device_id="ghost", state=OperationalState.down),
            )
        }
    )

    health = build_design_health(
        twin,
        include_expensive=True,
        constraints=("support future growth",),
    )

    ranks = [SEVERITY_RANK[finding.severity] for finding in health.findings]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) >= 3
    assert health.findings[0].severity is Severity.critical
    assert any(
        finding.severity is Severity.info for finding in health.findings
    )

    indexes = [CATEGORY_ORDER.index(group.category) for group in health.groups]
    assert indexes == sorted(indexes)

    constrained = health.findings_in({ValidationCategory.constraints})
    assert constrained
    assert all(
        finding in health.findings_for(ValidationCategory.constraints)
        for finding in constrained
    )


# ---------------------------------------------------------------------------
# W5: additive L2/WAN/wireless/QoS design models.
# ---------------------------------------------------------------------------

_W5_CATEGORIES = (
    ValidationCategory.l2,
    ValidationCategory.wan,
    ValidationCategory.wireless,
    ValidationCategory.qos,
)


def test_optional_design_engines_are_not_called_for_a_legacy_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("an optional W5 design engine ran for a legacy twin")

    monkeypatch.setattr(health_module, "analyze_l2_design", forbidden)
    monkeypatch.setattr(health_module, "analyze_wan_design", forbidden)
    monkeypatch.setattr(health_module, "analyze_wireless_design", forbidden)
    monkeypatch.setattr(health_module, "qos_findings", forbidden)

    report = build_design_health(make_twin())

    assert all(report.findings_for(category) == () for category in _W5_CATEGORIES)
    assert report.is_valid


def test_categorize_design_finding_maps_all_new_prefixes() -> None:
    for prefix, category in (
        ("l2_", ValidationCategory.l2),
        ("wan_", ValidationCategory.wan),
        ("wireless_", ValidationCategory.wireless),
        ("qos_", ValidationCategory.qos),
    ):
        finding = Finding(
            severity=Severity.info,
            code=f"{prefix}modeled",
            affected_entities=[],
            explanation="Modeled design finding.",
        )
        assert categorize_design_finding(finding) is category

    legacy = Finding(
        severity=Severity.warning,
        code="twin_topology_disconnected",
        affected_entities=[],
        explanation="Legacy finding.",
    )
    assert categorize_design_finding(legacy) is ValidationCategory.topology


def test_l2_link_fields_produce_one_categorized_error() -> None:
    base = make_twin()
    link = base.topology.links[0].model_copy(
        update={
            "l2_mode": LinkL2Mode.trunk,
            "l2_allowed_vlans": (10,),
            "l2_native_vlan": 10,
            "l2_peer_native_vlan": 20,
        }
    )
    twin = base.model_copy(
        update={
            "topology": base.topology.model_copy(
                update={"links": [link, *base.topology.links[1:]]}
            )
        }
    )

    report = build_design_health(twin)

    # Hand check: one modeled trunk has native VLAN 10 on one end and 20 on the
    # other, so the deterministic L2 review emits exactly one error.
    findings = report.findings_for(ValidationCategory.l2)
    assert [(item.code, item.severity) for item in findings] == [
        ("l2_native_vlan_mismatch", Severity.error)
    ]
    assert not report.findings_for(ValidationCategory.wan)
    assert not report.findings_for(ValidationCategory.qos)


def _wan_twin() -> DigitalTwin:
    return make_twin(
        topology=Topology(
            name="Two-site WAN",
            devices=[
                Device(
                    id="hq-r",
                    type=DeviceType.router,
                    site="hq",
                    role=DeviceRole.border,
                ),
                Device(
                    id="br-r",
                    type=DeviceType.router,
                    site="branch",
                    role=DeviceRole.wan,
                ),
            ],
            links=[
                Link(
                    id="wan-1",
                    endpoints=("hq-r", "br-r"),
                    capacity_mbps=100.0,
                    cost=1.0,
                    wan_type=WanLinkType.leased,
                    wan_monthly_cost_proxy=120.0,
                )
            ],
        ),
        demands=(),
    )


def test_wan_fields_run_cheap_checks_and_expensive_check_is_opt_in() -> None:
    twin = _wan_twin()

    basic = build_design_health(twin)
    codes = [item.code for item in basic.findings_for(ValidationCategory.wan)]
    # Hand check: two sites, one modeled inter-site link each => two SPOF errors;
    # the single 120 proxy total produces one info finding.
    assert codes == [
        "wan_site_single_link_spof",
        "wan_site_single_link_spof",
        "wan_cost_proxy_total",
    ]
    assert any("120" in item.explanation for item in basic.findings_for(
        ValidationCategory.wan
    ))
    assert basic.findings_for(ValidationCategory.redundancy) == ()

    expensive = build_design_health(twin, include_expensive=True)
    assert [
        item.code for item in expensive.findings_for(ValidationCategory.wan)
    ] == codes
    assert expensive.include_expensive is True


def test_expensive_wan_check_reports_capacity_shortfall() -> None:
    twin = _wan_twin().model_copy(
        update={
            "demands": (
                make_demand("bulk", "hq-r", "br-r", bandwidth_mbps=250.0),
            )
        }
    )

    basic = build_design_health(twin)
    assert "wan_capacity_shortfall" not in [
        item.code for item in basic.findings_for(ValidationCategory.wan)
    ]

    expensive = build_design_health(twin, include_expensive=True)
    codes = [item.code for item in expensive.findings_for(ValidationCategory.wan)]
    # Hand check: one 100 Mbps path carrying a 250 Mbps modeled demand leaves
    # 150 Mbps unserved, so only the opt-in check adds one shortfall error.
    assert codes.count("wan_capacity_shortfall") == 1
    assert codes.count("wan_site_single_link_spof") == 2
    assert any("1 inter-site demand" in item.explanation for item in
               expensive.findings_for(ValidationCategory.wan))


def test_wireless_zero_design_has_one_informational_finding() -> None:
    twin = make_twin(
        wireless_design=WirelessDesign(areas=(WirelessArea(id="empty"),))
    )

    report = build_design_health(twin)

    # Hand check: zero area and zero clients make both capacity and coverage AP
    # counts zero, so the engine reports one modeled no-demand note.
    assert [(item.code, item.severity) for item in report.findings_for(
        ValidationCategory.wireless
    )] == [("wireless_no_modeled_demand", Severity.info)]


def test_wireless_capacity_design_is_categorized() -> None:
    design = WirelessDesign(
        areas=(
            WirelessArea(
                id="floor-1",
                area_m2=1000,
                clients=200,
                client_mbps=10,
                ap_capacity_mbps=100,
                utilization_target=0.5,
            ),
        )
    )

    findings = build_design_health(
        make_twin(wireless_design=design)
    ).findings_for(ValidationCategory.wireless)

    # Hand check: ceil(200*10/(100*0.5)) = 40 capacity APs, while
    # ceil(1000/(pi*20^2*0.8)) = 1 coverage AP; capacity binds.
    assert [(item.code, item.severity) for item in findings] == [
        ("wireless_capacity_binding", Severity.info)
    ]
    assert findings[0].affected_entities == ["floor-1"]


def _qos_twin() -> DigitalTwin:
    voice = make_demand("voice", "r1", "r2", bandwidth_mbps=80.0).model_copy(
        update={"traffic_class": TrafficClass.voice}
    )
    bulk = make_demand("bulk", "r1", "r2", bandwidth_mbps=80.0).model_copy(
        update={"traffic_class": TrafficClass.best_effort}
    )
    return make_twin(
        topology=Topology(
            name="QoS admission",
            devices=[
                Device(
                    id="r1",
                    type=DeviceType.router,
                    site="hq",
                    role=DeviceRole.core,
                ),
                Device(
                    id="r2",
                    type=DeviceType.router,
                    site="hq",
                    role=DeviceRole.core,
                ),
            ],
            links=[
                Link(id="l1", endpoints=("r1", "r2"), capacity_mbps=100.0, cost=1.0),
                Link(id="l2", endpoints=("r1", "r2"), capacity_mbps=100.0, cost=2.0),
            ],
        ),
        demands=(voice, bulk),
        qos_design=QosDesign(
            class_share_caps=(
                ClassShareCap(
                    link_id="missing",
                    traffic_class=TrafficClass.voice,
                    share_cap=0.2,
                ),
            )
        ),
    )


def test_qos_admission_findings_are_categorized_as_errors() -> None:
    report = build_design_health(_qos_twin())

    findings = report.findings_for(ValidationCategory.qos)
    # Hand check: voice (priority 0) takes 80 of 100 Mbps, leaving best effort
    # starved; the cap on nonexistent link "missing" is a second modeled error.
    assert {item.code for item in findings} == {
        "qos_demand_starved",
        "qos_unknown_cap_link",
    }
    assert all(item.severity is Severity.error for item in findings)
    assert not report.findings_for(ValidationCategory.l2)


def test_optional_engine_failure_is_isolated_to_its_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("modeled L2 input rejected")

    monkeypatch.setattr(health_module, "analyze_l2_design", broken)
    wan_twin = _wan_twin()
    l2_link = wan_twin.topology.links[0].model_copy(
        update={"l2_mode": LinkL2Mode.trunk, "l2_allowed_vlans": (10,)}
    )
    twin = wan_twin.model_copy(
        update={
            "topology": wan_twin.topology.model_copy(update={"links": [l2_link]})
        }
    )

    report = build_design_health(twin)

    assert [
        item.code for item in report.findings_for(ValidationCategory.l2)
    ] == ["design_check_failed"]
    assert report.findings_for(ValidationCategory.wan)
    assert not report.findings_for(ValidationCategory.qos)
