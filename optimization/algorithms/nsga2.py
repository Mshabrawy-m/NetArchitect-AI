"""Seeded NSGA-II producing a true non-dominated front without weights.

Selection uses constrained domination: feasible candidates dominate infeasible
ones; between infeasible candidates, fewer violated hard constraints wins; only
then is objective Pareto dominance applied. Parents are chosen by binary
tournament on Pareto rank and crowding distance. Each generation combines
parents and offspring, ranks the union, and keeps the best ``population_size``
designs. Elitism is therefore part of the survival step rather than a separate
operator.

The reported Pareto front is the true rank-0 feasible front over *every*
candidate the run evaluated, not only the final population. It is a front over
the evaluated design space only; no global optimum is claimed. Weighted scores
are still recorded for comparability, but they do not drive NSGA-II selection.
"""

from __future__ import annotations

import numpy as np

from digital_twin import DigitalTwin

from ..evaluator import EvaluationCache, evaluate_candidate
from ..models import (
    Algorithm,
    Candidate,
    CandidateEvaluation,
    CandidateRecord,
    OptimizationRun,
    OptimizationSettings,
    StopReason,
)
from .budget import SearchBudget
from .common import (
    best_feasible,
    crossover,
    crowding_distance,
    dedupe,
    genome_space,
    mutate,
    mutation_rate,
    pareto_front,
    random_genome,
    rank_population,
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
    ranks: dict[str, tuple[int, float]],
    space,
    rng: np.random.Generator,
    rate: float,
    settings: OptimizationSettings,
) -> Candidate:
    """Select two parents by rank/crowding and return one child."""
    left = tournament(population, rng, ranks)
    right = tournament(population, rng, ranks)
    child = crossover(
        space.encode(left.candidate),
        space.encode(right.candidate),
        rng,
    )
    child = mutate(child, rng, space, rate)
    return space.decode(child, settings)


def _survival_key(
    evaluation: CandidateEvaluation,
    ranks: dict[str, tuple[int, float]],
) -> tuple[int, float, str]:
    rank, crowding = ranks.get(evaluation.candidate_hash, (10**9, -1.0))
    return (rank, -crowding, evaluation.candidate_hash)


def run_nsga2(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    *,
    deadline: float | None = None,
) -> OptimizationRun:
    """Run NSGA-II and report the final non-dominated feasible front.

    Identical settings (including ``seed``) produce identical results. The
    shared budget bounds evaluations and wall clock time; a run that exhausts a
    limit keeps its partial front and reports the matching
    :class:`~optimization.models.StopReason`.
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
    rate = mutation_rate(space)
    converged = False

    if not budget.exhausted:
        for _ in range(settings.max_iterations):
            if not budget.check():
                break
            ranks = rank_population(population)
            offspring: list[CandidateEvaluation] = []
            seen_offspring: set[str] = set()
            attempts = 0
            attempt_limit = max(settings.population_size * 20, 20)
            while (
                len(offspring) < settings.population_size
                and attempts < attempt_limit
            ):
                if not budget.check():
                    break
                attempts += 1
                candidate = _breed(
                    population,
                    ranks,
                    space,
                    rng,
                    rate,
                    settings,
                )
                evaluation = budget.evaluate(baseline_twin, candidate)
                if evaluation is None:
                    break
                records.setdefault(evaluation.candidate_hash, evaluation)
                if evaluation.candidate_hash in seen_offspring:
                    continue
                seen_offspring.add(evaluation.candidate_hash)
                offspring.append(evaluation)
            combined = dedupe([*population, *offspring])
            combined_ranks = rank_population(combined)
            population = sorted(
                combined,
                key=lambda item: _survival_key(item, combined_ranks),
            )[: settings.population_size]
            if budget.exhausted:
                break
            if seen_offspring.issubset(ranks):
                # Every child was already in the parent population.
                converged = True
                break

    final = dedupe(population)
    final_ranks = rank_population(final)
    front_evaluations = pareto_front(list(records.values()))
    front_distances = crowding_distance(front_evaluations)
    front = tuple(
        CandidateRecord(
            evaluation=evaluation,
            rank=0,
            crowding_distance=distance,
        )
        for evaluation, distance in zip(front_evaluations, front_distances)
    )

    if budget.stop_reason is not None:
        stop_reason = budget.stop_reason
    elif converged:
        stop_reason = StopReason.completed
    else:
        stop_reason = StopReason.max_iterations

    final_hashes = {evaluation.candidate_hash for evaluation in final}
    evaluations = list(records.values())
    best = best_feasible(evaluations)
    return OptimizationRun(
        algorithm=Algorithm.nsga2,
        seed=settings.seed,
        settings=settings,
        limits=settings.limits(),
        evaluations=cache.misses,
        cache_hits=cache.hits,
        stop_reason=stop_reason,
        baseline=baseline,
        candidates=tuple(
            record_for(
                evaluation,
                final_ranks if evaluation.candidate_hash in final_hashes else None,
            )
            for evaluation in evaluations
        ),
        pareto_front=tuple(front),
        best=best,
    )


__all__ = ["run_nsga2"]
