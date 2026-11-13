"""Deterministic greedy hill-climb baseline optimizer.

The optimizer starts from the empty candidate (the baseline design), then adds
one pool link or changes one capacity tier per step. It accepts the single
neighbor with the best weighted score only if it is feasible and strictly
improves the current score. Cost-multiplier moves are available only when
``OptimizationSettings.cost_multiplier_options`` is non-empty.

This is a local search baseline, not a claim of optimality.
"""

from __future__ import annotations

from collections.abc import Iterator

from core.exceptions import OptimizationRuntimeExceeded
from digital_twin import DigitalTwin

from .evaluator import (
    EvaluationCache,
    deadline_expired,
    evaluate_candidate,
    resolve_deadline,
)
from .models import (
    Algorithm,
    Candidate,
    CandidateEvaluation,
    CandidateRecord,
    OptimizationRun,
    OptimizationSettings,
    StopReason,
)
from .space import baseline_link_index, pool_index


def _candidate(
    selected: set[str],
    assignments: dict[str, str],
    multipliers: dict[str, float],
) -> Candidate:
    return Candidate(
        selected_link_ids=tuple(sorted(selected)),
        tier_assignments=tuple(sorted(assignments.items())),
        cost_multipliers=tuple(sorted(multipliers.items())),
    )


def _neighbors(
    current: Candidate,
    settings: OptimizationSettings,
    baseline: DigitalTwin,
) -> Iterator[Candidate]:
    """Yield deterministic one-change neighbors of ``current``."""
    pool = pool_index(settings)
    baseline_links = baseline_link_index(baseline)
    selected = set(current.selected_link_ids)
    assignments = dict(current.tier_assignments)
    multipliers = dict(current.cost_multipliers)
    seen: set[str] = set()

    def emit(candidate: Candidate) -> Candidate | None:
        if candidate == current:
            return None
        key = candidate.model_dump_json()
        if key in seen:
            return None
        seen.add(key)
        return candidate

    for link_id in sorted(pool):
        if link_id in selected:
            continue
        for tier in settings.cost_model.tiers:
            next_selected = set(selected)
            next_selected.add(link_id)
            next_assignments = dict(assignments)
            next_assignments[link_id] = tier.name
            candidate = emit(
                _candidate(next_selected, next_assignments, multipliers)
            )
            if candidate is not None:
                yield candidate

    for link_id in sorted(selected):
        current_tier = assignments.get(
            link_id,
            settings.cost_model.tiers[0].name,
        )
        for tier in settings.cost_model.tiers:
            if tier.name == current_tier:
                continue
            next_assignments = dict(assignments)
            next_assignments[link_id] = tier.name
            candidate = emit(
                _candidate(selected, next_assignments, multipliers)
            )
            if candidate is not None:
                yield candidate

    for link_id, link in sorted(baseline_links.items()):
        for tier in settings.cost_model.tiers:
            if tier.capacity_mbps == link.capacity_mbps:
                continue
            next_assignments = dict(assignments)
            next_assignments[link_id] = tier.name
            candidate = emit(
                _candidate(selected, next_assignments, multipliers)
            )
            if candidate is not None:
                yield candidate

    for link_id in sorted(set(baseline_links) | selected):
        for option in settings.cost_multiplier_options:
            next_multipliers = dict(multipliers)
            next_multipliers[link_id] = float(option)
            candidate = emit(_candidate(selected, assignments, next_multipliers))
            if candidate is not None:
                yield candidate


def _best_feasible(
    records: dict[str, CandidateEvaluation],
) -> CandidateRecord | None:
    feasible = [
        evaluation for evaluation in records.values() if evaluation.feasible
    ]
    if not feasible:
        return None
    best = min(feasible, key=lambda item: (item.weighted_score, item.candidate_hash))
    return CandidateRecord(evaluation=best)


def run_greedy(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    *,
    deadline: float | None = None,
) -> OptimizationRun:
    """Run the deterministic greedy hill-climb baseline optimizer."""
    cache = EvaluationCache()
    # Baseline metrics are always recorded; the search-phase deadline starts
    # after the baseline evaluation so a tiny search budget can still be
    # reported cleanly.
    baseline = evaluate_candidate(
        baseline_twin,
        Candidate(),
        settings,
        cache=cache,
        deadline=float("inf"),
    )
    search_deadline = resolve_deadline(settings, deadline)
    records: dict[str, CandidateEvaluation] = {
        baseline.candidate_hash: baseline
    }
    current = baseline
    stop_reason: StopReason | None = None

    for _ in range(settings.max_iterations):
        if deadline_expired(search_deadline):
            stop_reason = StopReason.runtime_limit
            break
        if cache.misses >= settings.max_evaluations:
            stop_reason = StopReason.max_evaluations
            break

        best_neighbor: CandidateEvaluation | None = None
        for neighbor in _neighbors(current.candidate, settings, baseline_twin):
            if deadline_expired(search_deadline):
                stop_reason = StopReason.runtime_limit
                break
            if cache.misses >= settings.max_evaluations:
                stop_reason = StopReason.max_evaluations
                break
            try:
                evaluation = evaluate_candidate(
                    baseline_twin,
                    neighbor,
                    settings,
                    cache=cache,
                    deadline=search_deadline,
                )
            except OptimizationRuntimeExceeded:
                stop_reason = StopReason.runtime_limit
                break
            records.setdefault(evaluation.candidate_hash, evaluation)
            if not evaluation.feasible:
                continue
            if best_neighbor is None or (
                evaluation.weighted_score,
                evaluation.candidate_hash,
            ) < (
                best_neighbor.weighted_score,
                best_neighbor.candidate_hash,
            ):
                best_neighbor = evaluation

        if stop_reason is not None:
            break
        if best_neighbor is None:
            stop_reason = StopReason.no_improvement
            break
        if current.feasible and (
            best_neighbor.weighted_score >= current.weighted_score - 1e-12
        ):
            stop_reason = StopReason.no_improvement
            break
        # An infeasible baseline or intermediate design may move to any
        # feasible neighbor, even if that neighbor scores worse on the weighted
        # objectives, because infeasible designs are never recommendations.
        current = best_neighbor

    if stop_reason is None:
        stop_reason = StopReason.max_iterations

    return OptimizationRun(
        algorithm=Algorithm.greedy,
        seed=settings.seed,
        settings=settings,
        limits=settings.limits(),
        evaluations=cache.misses,
        cache_hits=cache.hits,
        stop_reason=stop_reason,
        baseline=baseline,
        candidates=tuple(
            CandidateRecord(evaluation=evaluation)
            for evaluation in records.values()
        ),
        best=_best_feasible(records),
    )


__all__ = ["run_greedy"]
