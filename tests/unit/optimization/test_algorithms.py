"""GA/NSGA-II behaviour: feasibility, limits, determinism, and immutability."""

from __future__ import annotations

import numpy as np
import pytest

from optimization import (
    Algorithm,
    Candidate,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationSettings,
    StopReason,
    candidate_space_size,
    crossover,
    dominates,
    enumerate_candidates,
    genome_space,
    mutate,
    non_dominated_sort,
    random_genome,
    run_genetic,
    run_nsga2,
    run_optimization,
)
from simulation import twin_fingerprint
from tests.unit.optimization.helpers import settings, tiny_twin


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_runs_are_reproducible_for_identical_seed_and_settings(runner) -> None:
    config = settings(max_iterations=6, max_evaluations=300)
    first = runner(tiny_twin(), config)
    second = runner(tiny_twin(), config)
    assert first.model_dump() == second.model_dump()


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_algorithm_never_mutates_the_baseline(runner) -> None:
    baseline = tiny_twin()
    before = twin_fingerprint(baseline)
    runner(baseline, settings(max_iterations=3))
    assert twin_fingerprint(baseline) == before
    assert len(baseline.topology.links) == 2


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_algorithm_stops_at_max_evaluations(runner) -> None:
    run = runner(tiny_twin(), settings(max_evaluations=3, max_iterations=20))
    assert run.stop_reason is StopReason.max_evaluations
    assert run.evaluations == 3


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_algorithm_stops_at_runtime_limit(runner) -> None:
    run = runner(
        tiny_twin(),
        settings(max_runtime_seconds=1e-9, max_evaluations=500),
    )
    assert run.stop_reason is StopReason.runtime_limit
    assert run.evaluations == 1
    assert run.baseline.metrics.link_count == 2


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_algorithm_stops_at_max_iterations(runner) -> None:
    run = runner(
        tiny_twin(),
        settings(max_iterations=1, max_evaluations=1_000),
    )
    assert run.stop_reason is StopReason.max_iterations


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_algorithm_never_recommends_infeasible_candidates(runner) -> None:
    config = settings(
        pool=(),
        constraints=HardConstraints(
            require_connectivity=True,
            min_served_demand_ratio=1.0,
        ),
        max_iterations=4,
    )
    run = runner(tiny_twin(), config)
    assert run.best is None
    assert run.candidates
    assert all(not record.evaluation.feasible for record in run.candidates)
    assert run.pareto_front == ()


@pytest.mark.parametrize("runner", [run_genetic, run_nsga2])
def test_recommendation_is_the_best_feasible_weighted_candidate(runner) -> None:
    run = runner(tiny_twin(), settings(max_iterations=5, max_evaluations=400))
    feasible = [
        record.evaluation
        for record in run.candidates
        if record.evaluation.feasible
    ]
    assert run.best is not None
    assert run.best.evaluation.feasible
    assert run.best.evaluation.weighted_score == pytest.approx(
        min(item.weighted_score for item in feasible)
    )


def test_algorithm_enum_has_no_unsound_pso() -> None:
    assert {algorithm.value for algorithm in Algorithm} == {
        "greedy",
        "genetic",
        "nsga2",
    }


def test_dispatch_runs_every_listed_algorithm() -> None:
    config = settings(max_iterations=3, max_evaluations=200)
    for algorithm in Algorithm:
        run = run_optimization(tiny_twin(), config, algorithm)
        assert run.algorithm is algorithm
        assert run.seed == config.seed
        assert run.limits == config.limits()
        assert run.baseline.candidate_hash


def test_genome_round_trip_preserves_decisions() -> None:
    baseline = tiny_twin()
    config = settings(cost_multiplier_options=(2.0,))
    space = genome_space(baseline, config)
    candidate = Candidate(
        selected_link_ids=("cd",),
        tier_assignments=(("cd", "large"), ("ab", "large")),
        cost_multipliers=(("bc", 2.0),),
    )
    encoded = space.encode(candidate)
    assert encoded.tolist() == space.encode(candidate).tolist()
    decoded = space.decode(encoded, config)
    assert decoded.selected_link_ids == ("cd",)
    assert decoded.tier_for("cd") == "large"
    assert decoded.tier_for("ab") == "large"
    assert decoded.multiplier_for("bc") == 2.0


def test_random_genomes_stay_within_bounds() -> None:
    baseline = tiny_twin()
    config = settings(cost_multiplier_options=(2.0,))
    space = genome_space(baseline, config)
    rng = np.random.default_rng(11)
    bounds = space.upper_bounds
    for _ in range(50):
        genome = random_genome(rng, space)
        assert genome.shape == bounds.shape
        assert all(0 <= int(value) < int(bound) for value, bound in zip(genome, bounds))


def test_crossover_takes_each_gene_from_a_parent() -> None:
    rng = np.random.default_rng(3)
    left = np.array([0, 1, 1, 0], dtype=np.int64)
    right = np.array([1, 0, 1, 1], dtype=np.int64)
    child = crossover(left, right, rng)
    assert child.shape == left.shape
    assert all(value in {int(a), int(b)} for value, a, b in zip(child, left, right))


def test_mutation_respects_gene_bounds() -> None:
    baseline = tiny_twin()
    config = settings(cost_multiplier_options=(2.0, 3.0))
    space = genome_space(baseline, config)
    rng = np.random.default_rng(5)
    genome = random_genome(rng, space)
    mutated = mutate(genome, rng, space, 1.0)
    bounds = space.upper_bounds
    assert all(0 <= int(value) < int(bound) for value, bound in zip(mutated, bounds))


def test_exhaustive_enumeration_is_complete_for_a_tiny_space() -> None:
    from tests.unit.optimization.helpers import pool_links

    config = settings(
        pool=(pool_links()[0],),
        max_iterations=2,
    )
    assert candidate_space_size(tiny_twin(), config) == 12
    candidates = enumerate_candidates(tiny_twin(), config, limit=100)
    assert len(candidates) == 12
    assert len({candidate.model_dump_json() for candidate in candidates}) == 12


def test_exhaustive_enumeration_refuses_an_oversized_space() -> None:
    from tests.unit.optimization.helpers import pool_links

    config = settings(pool=(pool_links()[0],))
    assert enumerate_candidates(tiny_twin(), config, limit=3) == ()


def test_non_dominated_sort_partitions_all_evaluations() -> None:
    from optimization import evaluate_candidate

    config = settings(
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.infrastructure_cost,
                weight=0.5,
                lower_bound=0,
                upper_bound=500,
            ),
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=0.5,
                lower_bound=0,
                upper_bound=200,
            ),
        )
    )
    candidates = enumerate_candidates(tiny_twin(), config, limit=100)
    evaluations = [
        evaluate_candidate(tiny_twin(), candidate, config)
        for candidate in candidates
    ]
    layers = non_dominated_sort(evaluations)
    flattened = [item.candidate_hash for layer in layers for item in layer]
    assert len(flattened) == len(evaluations)
    assert set(flattened) == {item.candidate_hash for item in evaluations}
    for index, layer in enumerate(layers):
        for left in layer:
            for right in layer:
                if left.candidate_hash == right.candidate_hash:
                    continue
                assert not dominates(left, right)
        if index + 1 < len(layers):
            for left in layer:
                for right in layers[index + 1]:
                    assert not dominates(right, left)


def test_genetic_can_run_without_a_candidate_pool() -> None:
    config = OptimizationSettings(
        candidate_pool=(),
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.link_count,
                weight=1.0,
                lower_bound=0,
                upper_bound=10,
            ),
        ),
        max_iterations=1,
    )
    run = run_genetic(tiny_twin(), config)
    assert run.stop_reason in {StopReason.completed, StopReason.max_iterations}
