"""Shared builders for simulation unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin import DeviceState, DigitalTwin, LinkState, TwinMetadata


def make_device(device_id: str) -> Device:
    return Device(
        id=device_id,
        type=DeviceType.router,
        site="site-1",
        role=DeviceRole.core,
    )


def make_link(
    link_id: str,
    first: str,
    second: str,
    *,
    cost: float = 1.0,
    capacity_mbps: float = 100.0,
    directed: bool = False,
) -> Link:
    return Link(
        id=link_id,
        endpoints=(first, second),
        capacity_mbps=capacity_mbps,
        cost=cost,
        directed=directed,
    )


def make_topology(
    device_ids: list[str],
    links: list[Link],
    *,
    name: str = "Simulation test",
) -> Topology:
    return Topology(
        name=name,
        devices=[make_device(device_id) for device_id in device_ids],
        links=links,
    )


def make_demand(
    name: str,
    source: str,
    destination: str,
    bandwidth_mbps: float = 10.0,
) -> TrafficDemand:
    return TrafficDemand(
        name=name,
        source=source,
        destination=destination,
        bandwidth_mbps=bandwidth_mbps,
    )


def make_twin(
    topology: Topology,
    demands: tuple[TrafficDemand, ...] = (),
    *,
    device_states: tuple[DeviceState, ...] = (),
    link_states: tuple[LinkState, ...] = (),
) -> DigitalTwin:
    return DigitalTwin(
        metadata=TwinMetadata(
            name="Simulation twin",
            created_at=datetime(2026, 11, 13, 9, 0, tzinfo=UTC),
        ),
        topology=topology,
        demands=demands,
        device_states=device_states,
        link_states=link_states,
    )


def line_twin(
    *,
    demands: tuple[TrafficDemand, ...] = (),
    capacity_mbps: float = 100.0,
) -> DigitalTwin:
    """A three-device line a-b-c with two 100 Mbps links by default."""
    topology = make_topology(
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", capacity_mbps=capacity_mbps),
            make_link("bc", "b", "c", capacity_mbps=capacity_mbps),
        ],
    )
    return make_twin(topology, demands)


def diamond_twin(
    *,
    demands: tuple[TrafficDemand, ...] = (),
) -> DigitalTwin:
    """A diamond a-b-d / a-c-d where the direct branch is cheaper."""
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("ac", "a", "c", cost=2.0),
            make_link("cd", "c", "d", cost=2.0),
        ],
    )
    return make_twin(topology, demands)
