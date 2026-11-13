"""Hard-constraint rejection tests for every enforced constraint."""

from __future__ import annotations

from optimization import (
    Candidate,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    evaluate_candidate,
)
from tests.unit.optimization.helpers import connect_cd, settings, tiny_twin
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def _constraint_state(candidate, *, constraints, pool=None):
    config = settings(constraints=constraints, pool=pool)
    return evaluate_candidate(tiny_twin(), candidate, config)


def _violated(evaluation) -> set[str]:
    return set(evaluation.violated_constraints)


def test_connectivity_rejects_disconnected_device() -> None:
    evaluation = _constraint_state(
        Candidate(),
        constraints=HardConstraints(require_connectivity=True),
    )
    assert "connectivity" in _violated(evaluation)
    assert not evaluation.feasible


def test_served_ratio_rejects_unserved_demand() -> None:
    evaluation = _constraint_state(
        Candidate(),
        constraints=HardConstraints(
            require_connectivity=False,
            min_served_demand_ratio=1.0,
        ),
    )
    assert "served_demand_ratio" in _violated(evaluation)


def test_max_utilization_rejects_overloaded_link() -> None:
    topology = make_topology(
        ["a", "b"],
        [make_link("ab", "a", "b", capacity_mbps=100.0)],
    )
    twin = make_twin(topology, (make_demand("a-to-b", "a", "b", 150.0),))
    config = settings(
        pool=(),
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            max_utilization_percent=100.0,
        ),
    )
    evaluation = evaluate_candidate(twin, Candidate(), config)
    assert evaluation.metrics.max_utilization_percent == 150.0
    assert "max_utilization" in _violated(evaluation)


def test_budget_rejects_over_cap_candidate() -> None:
    evaluation = _constraint_state(
        connect_cd(),
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            max_budget_proxy=0.0,
        ),
    )
    assert "budget" in _violated(evaluation)


def test_max_edges_rejects_extra_link() -> None:
    evaluation = _constraint_state(
        connect_cd(),
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            max_edges=2,
        ),
    )
    assert "max_edges" in _violated(evaluation)


def test_max_nodes_rejects_too_many_devices() -> None:
    evaluation = _constraint_state(
        Candidate(),
        constraints=HardConstraints(
            require_connectivity=False,
            max_nodes=3,
        ),
    )
    assert "max_nodes" in _violated(evaluation)


def test_redundancy_rejects_single_path_design() -> None:
    topology = make_topology(
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b"),
            make_link("bc", "b", "c"),
        ],
    )
    twin = make_twin(topology, (make_demand("a-to-c", "a", "c", 10.0),))
    config = settings(
        pool=(),
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            min_edge_disjoint_paths=2,
        ),
    )
    evaluation = evaluate_candidate(twin, Candidate(), config)
    assert evaluation.metrics.min_edge_disjoint_paths == 1
    assert "redundancy" in _violated(evaluation)


def test_redundancy_passes_with_two_disjoint_paths() -> None:
    candidate = Candidate(
        selected_link_ids=("ad", "cd"),
        tier_assignments=(("ad", "small"), ("cd", "small")),
    )
    evaluation = _constraint_state(
        candidate,
        constraints=HardConstraints(
            min_served_demand_ratio=1.0,
            min_edge_disjoint_paths=2,
        ),
    )
    assert evaluation.metrics.min_edge_disjoint_paths == 2
    assert "redundancy" not in _violated(evaluation)


def test_disabled_constraints_are_recorded_as_not_enforced() -> None:
    config = settings(
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.link_count,
                weight=1.0,
                lower_bound=0,
                upper_bound=10,
            ),
        ),
        constraints=HardConstraints(
            require_connectivity=False,
            min_served_demand_ratio=None,
            max_utilization_percent=None,
            max_budget_proxy=None,
        ),
    )
    evaluation = evaluate_candidate(tiny_twin(), Candidate(), config)
    by_name = {result.name: result for result in evaluation.constraints}
    assert by_name["connectivity"].enforced is False
    assert by_name["served_demand_ratio"].enforced is False
    assert by_name["max_utilization"].enforced is False
    assert by_name["budget"].enforced is False
    assert by_name["redundancy"].enforced is False
