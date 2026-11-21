"""Capacity-aware admission-control model tests."""

from __future__ import annotations

from core.schemas.scenario import ScenarioType
from simulation.comparison import compare_routing_modes
from simulation.evaluator import evaluate, twin_fingerprint
from simulation.models import RoutingMode, SimulationAssumptions
from simulation.scenarios import build_scenario_twin

from .helpers import (
    line_twin,
    make_demand,
    make_link,
    make_scenario,
    make_topology,
    make_twin,
)


def _assumptions() -> SimulationAssumptions:
    return SimulationAssumptions(routing_mode=RoutingMode.capacity_aware)


def test_second_demand_rejected_when_line_capacity_exhausted() -> None:
    twin = line_twin(
        demands=(
            make_demand("small", "a", "c", 30.0),
            make_demand("large", "a", "c", 80.0),
        ),
        capacity_mbps=100.0,
    )

    state = evaluate(twin, _assumptions())
    by_name = {demand.name: demand for demand in state.demands}
    loads = {link.link_id: link.load_mbps for link in state.links}

    assert by_name["large"].served is True
    assert by_name["small"].served is False
    assert by_name["small"].reason == "insufficient capacity"
    assert by_name["small"].blocked_path_device_ids == ("a", "b", "c")
    assert by_name["small"].blocked_link_ids == ("ab", "bc")
    assert by_name["small"].bottleneck_link_id == "ab"
    assert by_name["small"].bottleneck_available_mbps == 20.0
    assert loads == {"ab": 80.0, "bc": 80.0}
    assert state.served_demand_mbps == 80.0


def test_demand_order_is_largest_first_then_id() -> None:
    first = line_twin(
        demands=(
            make_demand("z-second", "a", "c", 60.0),
            make_demand("a-first", "a", "c", 60.0),
        ),
        capacity_mbps=100.0,
    )
    reversed_twin = line_twin(
        demands=(
            make_demand("a-first", "a", "c", 60.0),
            make_demand("z-second", "a", "c", 60.0),
        ),
        capacity_mbps=100.0,
    )

    states = [evaluate(twin, _assumptions()) for twin in (first, reversed_twin)]
    served_names = [
        {demand.name for demand in state.demands if demand.served} for state in states
    ]

    assert served_names == [{"a-first"}, {"a-first"}]


def test_undirectional_traffic_shares_one_undirected_capacity_pool() -> None:
    topology = make_topology(
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", capacity_mbps=100.0),
            make_link("bc", "b", "c", capacity_mbps=100.0),
        ],
    )
    twin = make_twin(
        topology,
        (
            make_demand("forward", "a", "c", 60.0),
            make_demand("reverse", "c", "a", 60.0),
        ),
    )

    state = evaluate(twin, _assumptions())
    by_name = {demand.name: demand for demand in state.demands}

    assert by_name["forward"].served is True
    assert by_name["reverse"].served is False
    assert by_name["reverse"].reason == "insufficient capacity"
    assert by_name["reverse"].bottleneck_available_mbps == 40.0
    assert all(link.load_mbps == 60.0 for link in state.links)


def test_capacity_aware_chooses_first_affordable_equal_cost_path() -> None:
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0, capacity_mbps=15.0),
            make_link("bd", "b", "d", cost=1.0, capacity_mbps=15.0),
            make_link("ac", "a", "c", cost=1.0, capacity_mbps=100.0),
            make_link("cd", "c", "d", cost=1.0, capacity_mbps=100.0),
        ],
    )
    twin = make_twin(topology, (make_demand("a-to-d", "a", "d", 30.0),))

    state = evaluate(twin, _assumptions())

    assert state.demands[0].served is True
    assert state.demands[0].path_device_ids == ("a", "c", "d")
    loads = {link.link_id: link.load_mbps for link in state.links}
    assert loads == {"ab": 0.0, "bd": 0.0, "ac": 30.0, "cd": 30.0}


def test_compare_modes_evaluates_one_scenario_state_side_by_side() -> None:
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0, capacity_mbps=30.0),
            make_link("bd", "b", "d", cost=1.0, capacity_mbps=30.0),
            make_link("ac", "a", "c", cost=1.0, capacity_mbps=30.0),
            make_link("cd", "c", "d", cost=1.0, capacity_mbps=30.0),
        ],
    )
    twin = make_twin(topology, (make_demand("a-to-d", "a", "d", 40.0),))
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bd"],
    )
    expected_twin = build_scenario_twin(twin, scenario)

    comparison = compare_routing_modes(
        twin,
        SimulationAssumptions(),
        scenario=scenario,
    )
    states = {result.mode: result.state for result in comparison.results}

    assert comparison.scenario_id == scenario.id
    assert comparison.twin.fingerprint == twin_fingerprint(expected_twin)
    assert [result.mode for result in comparison.results] == [
        RoutingMode.single_path,
        RoutingMode.ecmp,
        RoutingMode.capacity_aware,
    ]
    assert states[RoutingMode.single_path].served_demand_count == 1
    assert states[RoutingMode.ecmp].served_demand_count == 1
    assert states[RoutingMode.capacity_aware].served_demand_count == 0
    assert states[RoutingMode.capacity_aware].unserved_demands[0].reason == (
        "insufficient capacity"
    )


def test_legacy_unserved_reasons_omit_additive_blocked_fields() -> None:
    twin = line_twin(demands=())
    payload = evaluate(twin).model_dump(mode="json")

    assert "blocked_path_device_ids" not in payload
    assert "bottleneck_link_id" not in payload
