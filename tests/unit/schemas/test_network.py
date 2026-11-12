"""Unit tests for ``core.schemas.network``."""

import pytest
from pydantic import ValidationError

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology


def _router(device_id: str = "r1") -> Device:
    return Device(
        id=device_id, type=DeviceType.router, site="site-1", role=DeviceRole.core
    )


def _switch(device_id: str = "s1") -> Device:
    return Device(
        id=device_id, type=DeviceType.switch, site="site-1", role=DeviceRole.access
    )


def test_device_valid() -> None:
    dev = _router()
    assert dev.type is DeviceType.router


def test_device_invalid_type_invalid() -> None:
    with pytest.raises(ValidationError):
        Device(id="r1", type="not-a-type", site="site-1", role=DeviceRole.core)


def test_link_valid() -> None:
    link = Link(id="l1", endpoints=("r1", "s1"), capacity_mbps=1000.0, cost=10.0)
    assert link.directed is False


def test_link_capacity_zero_invalid() -> None:
    with pytest.raises(ValidationError):
        Link(id="l1", endpoints=("r1", "s1"), capacity_mbps=0.0, cost=10.0)


def test_link_cost_zero_invalid() -> None:
    with pytest.raises(ValidationError):
        Link(id="l1", endpoints=("r1", "s1"), capacity_mbps=10.0, cost=0.0)


def test_link_self_loop_invalid() -> None:
    with pytest.raises(ValidationError):
        Link(id="l1", endpoints=("r1", "r1"), capacity_mbps=10.0, cost=1.0)


def test_link_wrong_endpoint_count_invalid() -> None:
    with pytest.raises(ValidationError):
        Link(id="l1", endpoints=("r1",), capacity_mbps=10.0, cost=1.0)
    with pytest.raises(ValidationError):
        Link(id="l1", endpoints=("r1", "s1", "x"), capacity_mbps=10.0, cost=1.0)


def test_topology_valid() -> None:
    topo = Topology(
        name="t1",
        devices=[_router("r1"), _switch("s1")],
        links=[Link(id="l1", endpoints=("r1", "s1"), capacity_mbps=1000.0, cost=10.0)],
    )
    assert topo.links[0].id == "l1"


def test_topology_duplicate_device_id_invalid() -> None:
    with pytest.raises(ValidationError):
        Topology(name="t1", devices=[_router("dup"), _router("dup")])


def test_topology_duplicate_link_id_invalid() -> None:
    with pytest.raises(ValidationError):
        Topology(
            name="t1",
            devices=[_router("r1"), _switch("s1")],
            links=[
                Link(id="dup", endpoints=("r1", "s1"), capacity_mbps=1.0, cost=1.0),
                Link(id="dup", endpoints=("s1", "r1"), capacity_mbps=2.0, cost=2.0),
            ],
        )


def test_topology_link_endpoint_not_in_devices_invalid() -> None:
    with pytest.raises(ValidationError):
        Topology(
            name="t1",
            devices=[_router("r1")],
            links=[Link(id="l1", endpoints=("r1", "ghost"), capacity_mbps=1.0, cost=1.0)],
        )


def test_topology_json_round_trip() -> None:
    topo = Topology(
        name="t1",
        devices=[_router("r1"), _switch("s1")],
        links=[
            Link(
                id="l1",
                endpoints=("r1", "s1"),
                capacity_mbps=1000.0,
                cost=10.0,
                directed=True,
            )
        ],
    )
    restored = Topology.model_validate_json(topo.model_dump_json())
    assert restored == topo
