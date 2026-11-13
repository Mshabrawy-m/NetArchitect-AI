"""Shared builders and known-value fixtures for optimization tests."""

from __future__ import annotations

from core.schemas.network import Link
from digital_twin import DigitalTwin
from optimization import (
    Candidate,
    CapacityTier,
    CostModel,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationSettings,
)
from tests.unit.simulation.helpers import (
    make_demand,
    make_link,
    make_topology,
    make_twin,
)

TIER_SMALL = CapacityTier(
    name="small",
    capacity_mbps=100.0,
    link_cost_proxy=10.0,
)
TIER_LARGE = CapacityTier(
    name="large",
    capacity_mbps=1_000.0,
    link_cost_proxy=100.0,
)


def tiny_twin(*, capacity_mbps: float = 100.0) -> DigitalTwin:
    """Four devices a-b-c plus an unconnected d, one demand a->d."""
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", capacity_mbps=capacity_mbps),
            make_link("bc", "b", "c", capacity_mbps=capacity_mbps),
        ],
    )
    return make_twin(topology, (make_demand("a-to-d", "a", "d", 50.0),))


def pool_links() -> tuple[Link, ...]:
    """Three candidate links; cd is the cheapest way to connect d."""
    return (
        make_link("cd", "c", "d", cost=1.0),
        make_link("ad", "a", "d", cost=2.0),
        make_link("bd", "b", "d", cost=3.0),
    )


def two_tier_model(*, device_cost: float = 0.0) -> CostModel:
    return CostModel(
        tiers=(TIER_SMALL, TIER_LARGE),
        device_cost_proxy=device_cost,
    )


def link_count_objective(
    *, lower: float = 2.0, upper: float = 5.0
) -> ObjectiveSpec:
    return ObjectiveSpec(
        kind=ObjectiveKind.link_count,
        weight=1.0,
        lower_bound=lower,
        upper_bound=upper,
    )


def settings(
    *,
    objectives: tuple[ObjectiveSpec, ...] | None = None,
    constraints: HardConstraints | None = None,
    pool: tuple[Link, ...] | None = None,
    cost_model: CostModel | None = None,
    cost_multiplier_options: tuple[float, ...] = (),
    max_iterations: int = 10,
    max_evaluations: int = 200,
    max_runtime_seconds: float = 30.0,
) -> OptimizationSettings:
    return OptimizationSettings(
        candidate_pool=pool_links() if pool is None else pool,
        cost_model=two_tier_model() if cost_model is None else cost_model,
        objectives=(link_count_objective(),) if objectives is None else objectives,
        constraints=(
            HardConstraints(min_served_demand_ratio=1.0)
            if constraints is None
            else constraints
        ),
        seed=7,
        population_size=20,
        max_iterations=max_iterations,
        max_evaluations=max_evaluations,
        max_runtime_seconds=max_runtime_seconds,
        cost_multiplier_options=cost_multiplier_options,
    )


def connect_cd() -> Candidate:
    """Add cd at the small tier."""
    return Candidate(
        selected_link_ids=("cd",),
        tier_assignments=(("cd", "small"),),
    )
