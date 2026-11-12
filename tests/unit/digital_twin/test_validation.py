"""Tests for digital-twin cross-part validation."""

from __future__ import annotations

from datetime import UTC

from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet
from core.schemas.network import Device, DeviceRole, DeviceType
from core.schemas.requirements import Assumption
from core.schemas.routing import TrafficDemand
from digital_twin import (
    DeviceState,
    LinkState,
    OperationalState,
    TwinMetadata,
    validate_twin,
)
from network.vlan import VlanAssignment, VlanPlanResult

from .helpers import CREATED_AT, make_assumption, make_scope, make_topology, make_twin


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_valid_twin_has_no_findings() -> None:
    report = validate_twin(make_twin())

    assert report.is_valid is True
    assert report.findings == []
    assert report.summary == "No digital-twin findings."


def test_stale_state_references_are_reported_not_pruned() -> None:
    twin = make_twin(
        device_states=(DeviceState(device_id="removed", state=OperationalState.down),),
        link_states=(LinkState(link_id="removed-link", state=OperationalState.down),),
    )

    report = validate_twin(twin)

    assert report.is_valid is False
    assert {"twin_unknown_device_state", "twin_unknown_link_state"} <= _codes(report)
    assert len(twin.device_states) == 1
    assert len(twin.link_states) == 1


def test_duplicate_state_entries_are_errors() -> None:
    twin = make_twin(
        device_states=(
            DeviceState(device_id="r1", state=OperationalState.down),
            DeviceState(device_id="r1", state=OperationalState.up),
        )
    )

    report = validate_twin(twin)

    assert "twin_duplicate_device_state" in _codes(report)


def test_demands_must_reference_real_devices_and_unique_names() -> None:
    twin = make_twin(
        demands=(
            TrafficDemand(
                name="bad",
                source="r1",
                destination="ghost",
                bandwidth_mbps=1.0,
            ),
            TrafficDemand(
                name="bad",
                source="r1",
                destination="r2",
                bandwidth_mbps=1.0,
            ),
        )
    )

    report = validate_twin(twin)

    assert "twin_demand_unknown_device" in _codes(report)
    assert "twin_duplicate_demand_name" in _codes(report)


def test_addressing_overlap_findings_are_reused() -> None:
    invalid_addressing = AddressingPlan.model_construct(
        vlan_plans=[],
        subnets=[
            Subnet(name="a", network="10.0.0.0/24"),
            Subnet(name="b", network="10.0.0.0/25"),
        ],
    )
    twin = make_twin(
        vlan_plan=None,
        dhcp_scopes=(),
        demands=(),
    ).model_copy(update={"addressing": invalid_addressing})

    report = validate_twin(twin)

    assert "subnet_overlap" in _codes(report)


def test_dhcp_scope_findings_are_reused() -> None:
    twin = make_twin(
        dhcp_scopes=(
            DhcpScope(
                name="outside",
                network="10.0.0.0/24",
                gateway="10.0.1.1",
            ),
        )
    )

    report = validate_twin(twin)

    assert "dhcp_gateway_outside_subnet" in _codes(report)


def test_vlan_assignment_must_exist_in_addressing() -> None:
    vlan_plan = VlanPlanResult(
        assignments=[
            VlanAssignment(
                department="guest",
                vlan_id=20,
                vlan_name="Guest",
                subnet_name="guest",
                network="10.9.0.0/24",
                purpose="Guest access",
            )
        ]
    )
    twin = make_twin(vlan_plan=vlan_plan, dhcp_scopes=(), demands=())

    report = validate_twin(twin)

    assert "twin_vlan_subnet_missing" in _codes(report)


def test_dhcp_scope_network_should_map_to_addressing() -> None:
    twin = make_twin(
        dhcp_scopes=(DhcpScope(name="guest DHCP", network="10.9.0.0/24"),),
        demands=(),
    )

    report = validate_twin(twin)

    assert "twin_dhcp_scope_network_missing" in _codes(report)


def test_disconnected_topology_is_a_warning() -> None:
    topology = make_topology()
    topology.devices.append(
        Device(
            id="ghost",
            type=DeviceType.host,
            site="hq",
            role=DeviceRole.access,
        )
    )
    twin = make_twin(topology=topology)

    report = validate_twin(twin)

    finding = next(
        item
        for item in report.findings
        if item.code == "twin_topology_disconnected"
    )
    assert finding.affected_entities == ["ghost"]
    assert report.is_valid is True


def test_unsupported_schema_version_is_an_error() -> None:
    twin = make_twin(
        metadata=TwinMetadata(
            name="Future twin",
            created_at=CREATED_AT.astimezone(UTC),
            schema_version=2,
        )
    )

    report = validate_twin(twin)

    assert "twin_schema_version_unsupported" in _codes(report)


def test_duplicate_assumption_ids_warn() -> None:
    twin = make_twin(
        assumptions=(
            make_assumption(),
            Assumption(
                id="growth-1",
                category="traffic",
                description="Duplicate id",
            ),
        ),
        demands=(),
    )

    report = validate_twin(twin)

    assert "twin_duplicate_assumption" in _codes(report)


def test_scope_helper_is_valid_on_the_baseline() -> None:
    scope = make_scope()

    assert scope.name == "users DHCP"
