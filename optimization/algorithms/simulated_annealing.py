"""Seeded, bounded simulated annealing over the discrete design space.

This algorithm uses the same integer genome, evaluator, hard constraints, and
search budget as GA/NSGA-II, but it walks one candidate at a time. It is a
heuristic modeled search, not a claim of a global optimum.

Hybrid starts
-------------
Callers may pass ``initial_candidates`` (keyword-only). The candidates are
evaluated in order under this run's own budget, and the best feasible design
under :func:`~optimization.algorithms.common.constraint_key` becomes the walking
start. Passing the best candidate from :func:`optimization.run_greedy` produces
a deterministic greedy-to-annealing hybrid; passing nothing starts from the
empty baseline candidate. Caller candidates never bypass feasibility checks, and
the recommendation is still the best feasible design found in this run.

Acceptance rule
---------------
A neighbor is always accepted when its constraint-first key improves. A
neighbor with the same feasibility status and the same violation count may be
accepted with the Metropolis probability ``exp(-delta / temperature)``, where
``delta`` is the increase in normalized weighted score. A neighbor that is
infeasible where the current design is feasible, or that violates more hard
constraints, is rejected. The temperature decays deterministically from 1.0 to
0.01 across ``max_iterations``, so identical seeds reproduce identical walks.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from config.limits import MAX_SA_INITIAL_CANDIDATES
from core.exceptions import LimitsExceededError
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
    genome_space,
    mutate,
    mutation_rate,
    record_for,
)

INITIAL_TEMPERATURE = 1.0
FINAL_TEMPERATURE = 0.01
NEIGHBOR_ATTEMPTS = 16


def _temperature(iteration: int, max_iterations: int) -> float:
    """Return the deterministic annealing temperature for one iteration."""
    if max_iterations <= 1:
        return FINAL_TEMPERATURE
    progress = min(1.0, max(0.0, iteration / (max_iterations - 1)))
    return INITIAL_TEMPERATURE * (
        FINAL_TEMPERATURE / INITIAL_TEMPERATURE
    ) ** progress


def _validated_starts(
    initial_candidates: Sequence[Candidate],
) -> tuple[Candidate, ...]:
    """Validate and bound the optional hybrid-start candidates."""
    if len(initial_candidates) > MAX_SA_INITIAL_CANDIDATES:
        raise LimitsExceededError(
            f"Simulated annealing accepts at most {MAX_SA_INITIAL_CANDIDATES} "
            f"hybrid-start candidates; got {len(initial_candidates)}."
        )
    starts: list[Candidate] = []
    seen: set[str] = set()
    for item in initial_candidates:
        candidate = (
            item
            if isinstance(item, Candidate)
            else Candidate.model_validate(item)
        )
        key = candidate.model_dump_json()
        if key not in seen:
            seen.add(key)
            starts.append(candidate)
    return tuple(starts)


def _neighbor_candidate(
    rng: np.random.Generator,
    space,
    settings: OptimizationSettings,
    current: Candidate,
    rate: float,
) -> Candidate | None:
    """Return one mutated candidate that actually differs from ``current``.

    Some genome positions decode to the same design (for example, a tier gene on
    an unselected pool link), so a plain mutation can be a no-op. The retry loop
    is bounded and consumes only local randomness; no candidate is evaluated
    until a distinct design is produced.
    """
    current_key = current.model_dump_json()
    for _ in range(NEIGHBOR_ATTEMPTS):
        genome = mutate(space.encode(current), rng, space, rate)
        candidate = space.decode(genome, settings)
        if candidate.model_dump_json() != current_key:
            return candidate
    return None


def _evaluate_start(
    budget: SearchBudget,
    baseline_twin: DigitalTwin,
    candidate: Candidate,
    records: dict[str, CandidateEvaluation],
) -> CandidateEvaluation | None:
    evaluation = budget.evaluate(baseline_twin, candidate)
    if evaluation is None:
        return None
    records.setdefault(evaluation.candidate_hash, evaluation)
    return evaluation


def run_simulated_annealing(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    *,
    deadline: float | None = None,
    initial_candidates: Sequence[Candidate] = (),
) -> OptimizationRun:
    """Run seeded simulated annealing with an optional hybrid start.

    The run is bit-for-bit reproducible for identical settings and starts. Work
    is bounded by the shared evaluation/wall-clock budget and by
    ``settings.max_iterations``. The baseline is always evaluated first so a
    clean stop reason and full traceability are available even when the search
    budget is exhausted immediately.
    """
    starts = _validated_starts(initial_candidates)
    cache = EvaluationCache.for_run(baseline_twin, settings)
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
    space = genome_space(
        baseline_twin,
        settings,
        pool=cache.pool,
        baseline_links=cache.baseline_links,
    )
    budget = SearchBudget.start(settings, cache, deadline)
    current = baseline

    for start_candidate in starts:
        if budget.exhausted:
            break
        evaluation = _evaluate_start(budget, baseline_twin, start_candidate, records)
        if evaluation is None:
            break
        if constraint_key(evaluation) < constraint_key(current):
            current = evaluation

    rate = mutation_rate(space)
    stagnant = False
    for iteration in range(settings.max_iterations):
        if not budget.check():
            break
        candidate = _neighbor_candidate(rng, space, settings, current.candidate, rate)
        if candidate is None:
            stagnant = True
            break
        evaluation = budget.evaluate(baseline_twin, candidate)
        if evaluation is None:
            break
        records.setdefault(evaluation.candidate_hash, evaluation)

        current_key = constraint_key(current)
        neighbor_key = constraint_key(evaluation)
        if neighbor_key <= current_key:
            current = evaluation
            continue
        same_feasibility = neighbor_key[0] == current_key[0]
        same_violations = neighbor_key[1] == current_key[1]
        if not (same_feasibility and same_violations):
            continue
        delta = neighbor_key[2] - current_key[2]
        temperature = _temperature(iteration, settings.max_iterations)
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            current = evaluation

    if budget.stop_reason is not None:
        stop_reason = budget.stop_reason
    elif stagnant:
        stop_reason = StopReason.no_improvement
    else:
        stop_reason = StopReason.max_iterations
    evaluations = list(records.values())
    best = best_feasible(evaluations)
    return OptimizationRun(
        algorithm=Algorithm.simulated_annealing,
        seed=settings.seed,
        settings=settings,
        limits=settings.limits(),
        evaluations=cache.misses,
        cache_hits=cache.hits,
        stop_reason=stop_reason,
        baseline=baseline,
        candidates=tuple(record_for(evaluation) for evaluation in evaluations),
        best=best,
    )


__all__ = [
    "FINAL_TEMPERATURE",
    "INITIAL_TEMPERATURE",
    "NEIGHBOR_ATTEMPTS",
    "run_simulated_annealing",
]
