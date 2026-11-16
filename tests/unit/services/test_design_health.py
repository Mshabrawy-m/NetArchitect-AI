"""Tests for the unified design-health validation entry point."""

from __future__ import annotations

from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet
from core.schemas.network import Topology
from core.schemas.validation import Severity
from digital_twin import DeviceState, DigitalTwin, OperationalState, TwinMetadata
from network.vlan import VlanAssignment, VlanPlanResult
from services.validation import (
    CATEGORY_ORDER,
    SEVERITY_RANK,
    DesignHealth,
    ValidationCategory,
    build_design_health,
)
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
            schema_version=2,
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
