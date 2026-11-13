"""Seeded Genetic Algorithm with a weighted-sum fitness.

Feasibility handling
--------------------
Hard constraints are never folded into a numeric penalty. Tournament selection
uses :func:`optimization.algorithms.common.constraint_key`, which orders
candidates by:

1. feasible before infeasible,
2. fewer violated hard constraints,
3. lower weighted sum of normalized objectives.

Elitism keeps the best candidates under the same order, so a feasible design is
never displaced by an infeasible one. Infeasible candidates are still evaluated
and recorded, but the recommendation is always the best *feasible* candidate or
``None``. This is a heuristic; no global optimum is claimed.
"""

from __future__ import annotations

import numpy as np

from digital_twin import DigitalTwin

from ..evaluator import EvaluationCache, evaluate_candidate
from ..models import (
    Algorithm,
    Candidate,
    CandidateEvaluation,
    OptimizationRun,
    OptimizationSettings,
    StopReason,
)
from .budget import SearchBudget
from .common import (
    best_feasible,
    constraint_key,
    crossover,
    genome_space,
    mutate,
    mutation_rate,
    random_genome,
    record_for,
    tournament,
)


def _seed_population(
    budget: SearchBudget,
    baseline_twin: DigitalTwin,
    space,
    rng: np.random.Generator,
    records: dict[str, CandidateEvaluation],
    population: list[CandidateEvaluation],
) -> list[CandidateEvaluation]:
    """Fill the initial population with distinct random candidates."""
    seen = {evaluation.candidate_hash for evaluation in population}
    target = budget.settings.population_size
    attempts = 0
    attempt_limit = max(target * 20, 20)
    while len(population) < target and attempts < attempt_limit:
        if not budget.check():
            break
        attempts += 1
        candidate = space.decode(random_genome(rng, space), budget.settings)
        evaluation = budget.evaluate(baseline_twin, candidate)
        if evaluation is None:
            break
        records.setdefault(evaluation.candidate_hash, evaluation)
        if evaluation.candidate_hash in seen:
            continue
        seen.add(evaluation.candidate_hash)
        population.append(evaluation)
    return population


def _breed(
    population: list[CandidateEvaluation],
    space,
    rng: np.random.Generator,
    rate: float,
    settings: OptimizationSettings,
) -> Candidate:
    """Select two parents and return one mutated child candidate."""
    left = tournament(population, rng, None)
    right = tournament(population, rng, None)
    child = crossover(
        space.encode(left.candidate),
        space.encode(right.candidate),
        rng,
    )
    child = mutate(child, rng, space, rate)
    return space.decode(child, settings)


def run_genetic(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    *,
    deadline: float | None = None,
) -> OptimizationRun:
    """Run a seeded Genetic Algorithm with elitism.

    For identical settings (including ``seed``) the run is bit-for-bit
    reproducible. ``max_iterations`` bounds generations, ``population_size``
    bounds each generation, and the shared budget bounds evaluations and wall
    clock time. The run stops with ``completed`` only when the population has
    collapsed to one distinct design; otherwise it stops at a stated limit.
    """
    cache = EvaluationCache()
    baseline = evaluate_candidate(
        baseline_twin,
        Candidate(),
        settings,
        cache=cache,
        deadline=float("inf"),
    )
    records: dict[str, CandidateEvaluation] = {
        baseline.candidate_hash: baseline
    }
    rng = np.random.default_rng(settings.seed)
    space = genome_space(baseline_twin, settings)
    budget = SearchBudget.start(settings, cache, deadline)

    population = _seed_population(
        budget,
        baseline_twin,
        space,
        rng,
        records,
        [baseline],
    )
    elite_count = max(1, settings.population_size // 10)
    rate = mutation_rate(space)
    converged = False

    if not budget.exhausted:
        for _ in range(settings.max_iterations):
            if not budget.check():
                break
            population.sort(key=constraint_key)
            elites = population[:elite_count]
            next_population = list(elites)
            seen = {evaluation.candidate_hash for evaluation in next_population}
            attempts = 0
            attempt_limit = max(settings.population_size * 20, 20)
            while (
                len(next_population) < settings.population_size
                and attempts < attempt_limit
            ):
                if not budget.check():
                    break
                attempts += 1
                candidate = _breed(population, space, rng, rate, settings)
                evaluation = budget.evaluate(baseline_twin, candidate)
                if evaluation is None:
                    break
                records.setdefault(evaluation.candidate_hash, evaluation)
                if evaluation.candidate_hash in seen:
                    continue
                seen.add(evaluation.candidate_hash)
                next_population.append(evaluation)
            population = next_population
            if budget.exhausted:
                break
            if len({evaluation.candidate_hash for evaluation in population}) == 1:
                converged = True
                break

    if budget.stop_reason is not None:
        stop_reason = budget.stop_reason
    elif converged:
        stop_reason = StopReason.completed
    else:
        stop_reason = StopReason.max_iterations

    evaluations = list(records.values())
    best = best_feasible(evaluations)
    return OptimizationRun(
        algorithm=Algorithm.genetic,
        seed=settings.seed,
        settings=settings,
        limits=settings.limits(),
        evaluations=cache.misses,
        cache_hits=cache.hits,
        stop_reason=stop_reason,
        baseline=baseline,
        candidates=tuple(
            record_for(evaluation) for evaluation in evaluations
        ),
        best=best,
    )


__all__ = ["run_genetic"]
