"""Shared fixtures for digital-twin unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet, VlanPlan
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.requirements import Assumption
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.vlan import VlanAssignment, VlanPlanResult

CREATED_AT = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)


def make_topology() -> Topology:
    return Topology(
        name="Campus edge",
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
            Device(
                id="sw1",
                type=DeviceType.switch,
                site="hq",
                role=DeviceRole.access,
            ),
        ],
        links=[
            Link(
                id="l1",
                endpoints=("r1", "r2"),
                capacity_mbps=1000.0,
                cost=1.0,
            ),
            Link(
                id="l2",
                endpoints=("r2", "sw1"),
                capacity_mbps=100.0,
                cost=2.0,
            ),
        ],
    )


def make_addressing() -> AddressingPlan:
    return AddressingPlan(
        vlan_plans=[
            VlanPlan(
                vlan_id=10,
                name="Users",
                subnets=[Subnet(name="users", network="10.0.0.0/24")],
            )
        ],
        subnets=[Subnet(name="transit", network="10.1.0.0/30")],
    )


def make_vlan_plan() -> VlanPlanResult:
    return VlanPlanResult(
        assignments=[
            VlanAssignment(
                department="users",
                vlan_id=10,
                vlan_name="Users",
                subnet_name="users",
                network="10.0.0.0/24",
                purpose="User access",
            )
        ]
    )


def make_scope() -> DhcpScope:
    return DhcpScope(
        name="users DHCP",
        network="10.0.0.0/24",
        gateway="10.0.0.1",
        start_address="10.0.0.10",
        end_address="10.0.0.200",
        lease_minutes=1440,
    )


def make_demand() -> TrafficDemand:
    return TrafficDemand(
        name="client-to-server",
        source="r1",
        destination="sw1",
        bandwidth_mbps=50.0,
        priority=1,
    )


def make_assumption() -> Assumption:
    return Assumption(
        id="growth-1",
        category="growth",
        description="User count grows 10% per year.",
        rationale="Planning assumption supplied with the design.",
    )


def make_twin(**overrides: object) -> DigitalTwin:
    values: dict[str, object] = {
        "metadata": TwinMetadata(name="Campus twin", created_at=CREATED_AT),
        "topology": make_topology(),
        "addressing": make_addressing(),
        "vlan_plan": make_vlan_plan(),
        "dhcp_scopes": (make_scope(),),
        "demands": (make_demand(),),
        "device_states": (),
        "link_states": (),
        "assumptions": (make_assumption(),),
    }
    values.update(overrides)
    return DigitalTwin(**values)  # type: ignore[arg-type]
