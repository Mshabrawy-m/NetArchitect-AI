"""Bounded invariants for deterministic failure sweeps."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from simulation.failure_sweep import (
    FailureSweepDepth,
    failure_sweep_to_json,
    run_failure_sweep,
)
from simulation.models import RoutingMode, SimulationAssumptions
from tests.property.config import BOUNDED
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)

_DIAMOND_LINKS = ("ab", "bd", "ac", "cd")


def _diamond_twin(capacity: float = 100.0):
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0, capacity_mbps=capacity),
            make_link("bd", "b", "d", cost=1.0, capacity_mbps=capacity),
            make_link("ac", "a", "c", cost=1.0, capacity_mbps=capacity),
            make_link("cd", "c", "d", cost=1.0, capacity_mbps=capacity),
        ],
    )
    return make_twin(
        topology,
        (
            make_demand("one", "a", "d", 30.0),
            make_demand("two", "a", "d", 40.0),
        ),
    )


@BOUNDED
@given(
    selected=st.lists(
        st.sampled_from(_DIAMOND_LINKS),
        min_size=0,
        max_size=len(_DIAMOND_LINKS),
        unique=True,
    ).flatmap(st.permutations)
)
def test_n2_output_is_independent_of_subset_order(selected: tuple[str, ...]) -> None:
    twin = _diamond_twin()
    assumptions = SimulationAssumptions()

    forward = run_failure_sweep(
        twin,
        assumptions,
        depth=FailureSweepDepth.n2,
        selected_link_ids=selected,
    )
    reverse = run_failure_sweep(
        twin,
        assumptions,
        depth=FailureSweepDepth.n2,
        selected_link_ids=tuple(reversed(selected)),
    )

    assert failure_sweep_to_json(forward) == failure_sweep_to_json(reverse)


@BOUNDED
@given(
    capacity=st.floats(
        min_value=20.0,
        max_value=120.0,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_capacity_aware_sweep_cases_never_exceed_capacity(capacity: float) -> None:
    twin = _diamond_twin(capacity)
    result = run_failure_sweep(
        twin,
        SimulationAssumptions(routing_mode=RoutingMode.capacity_aware),
        limit=4,
    )

    assert result.evaluated_cases == 4
    for case in result.cases:
        for link in case.state.links:
            assert link.load_mbps <= link.capacity_mbps + 1e-6
