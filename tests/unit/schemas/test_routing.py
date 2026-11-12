"""Unit tests for ``core.schemas.routing``."""

import pytest
from pydantic import ValidationError

from core.schemas.routing import RouteEntry, TrafficDemand


def test_route_entry_valid_v4() -> None:
    entry = RouteEntry(
        destination="10.0.0.0/24",
        next_hop="10.0.0.1",
        interface="eth0",
        metric=10,
        source="static",
    )
    assert entry.metric == 10


def test_route_entry_directly_connected() -> None:
    entry = RouteEntry(destination="10.0.0.0/24", metric=0)
    assert entry.next_hop is None


def test_route_entry_negative_metric_invalid() -> None:
    with pytest.raises(ValidationError):
        RouteEntry(destination="10.0.0.0/24", metric=-1)


def test_route_entry_json_round_trip_v4() -> None:
    entry = RouteEntry(
        destination="10.0.0.0/24",
        next_hop="10.0.0.1",
        interface="eth0",
        metric=10,
        source="static",
    )
    assert RouteEntry.model_validate_json(entry.model_dump_json()) == entry


def test_route_entry_json_round_trip_v6() -> None:
    entry = RouteEntry(
        destination="2001:db8::/32",
        next_hop="2001:db8::1",
        metric=10,
    )
    assert RouteEntry.model_validate_json(entry.model_dump_json()) == entry


def test_traffic_demand_valid() -> None:
    demand = TrafficDemand(
        name="d1", source="r1", destination="r2", bandwidth_mbps=100.0, priority=5
    )
    assert demand.priority == 5


def test_traffic_demand_default_priority() -> None:
    demand = TrafficDemand(name="d1", source="r1", destination="r2", bandwidth_mbps=100.0)
    assert demand.priority == 0


def test_traffic_demand_negative_bandwidth_invalid() -> None:
    with pytest.raises(ValidationError):
        TrafficDemand(name="d1", source="r1", destination="r2", bandwidth_mbps=-1.0)


def test_traffic_demand_negative_priority_invalid() -> None:
    with pytest.raises(ValidationError):
        TrafficDemand(name="d1", source="r1", destination="r2", bandwidth_mbps=1.0, priority=-1)


def test_traffic_demand_json_round_trip() -> None:
    demand = TrafficDemand(
        name="d1", source="r1", destination="r2", bandwidth_mbps=100.0, priority=5
    )
    assert TrafficDemand.model_validate_json(demand.model_dump_json()) == demand
