"""Bounded model invariants for the additive routing modes."""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from simulation.evaluator import evaluate
from simulation.models import RoutingMode, SimulationAssumptions
from tests.property.config import BOUNDED
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def _equal_cost_diamond(bandwidth: float):
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("ac", "a", "c", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
        ],
    )
    return make_twin(topology, (make_demand("d", "a", "d", bandwidth),))


@BOUNDED
@given(
    bandwidth=st.floats(
        min_value=0.01,
        max_value=1_000.0,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_ecmp_split_loads_conserve_total_demand(bandwidth: float) -> None:
    state = evaluate(
        _equal_cost_diamond(bandwidth),
        SimulationAssumptions(routing_mode=RoutingMode.ecmp),
    )
    evaluation = state.demands[0]
    split_total = sum(split.bandwidth_mbps for split in evaluation.splits)

    assert math.isclose(split_total, bandwidth, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(state.served_demand_mbps, bandwidth, rel_tol=1e-9)
    assert math.isclose(
        sum(split.share_percent for split in evaluation.splits),
        100.0,
        rel_tol=1e-9,
    )
    for link in state.links:
        assert math.isclose(link.load_mbps, bandwidth / 2, rel_tol=1e-9)
