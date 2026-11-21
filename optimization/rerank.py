"""Instant, pure Pareto re-ranking from an existing optimization run.

Changing objective weights does not change Pareto membership: dominance uses
raw objective values and their directions, not weights. It can change the weighted
order of the evaluated front and therefore which feasible design is recommended.
This module recomputes only those derived values from evaluations already stored
on a run. It performs no simulation, uses no randomness, and never mutates the
source run.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.csv_safe import neutralize_cell
from simulation.models import MODEL_NOTE

from .algorithms.common import pareto_front
from .models import (
    SEARCH_NOTE,
    Algorithm,
    CandidateEvaluation,
    ObjectiveKind,
    OptimizationRun,
)

RERANK_NOTE = (
    "Pareto membership is unchanged because it depends on raw objectives and "
    "directions, not weights. Only stored weighted scores and order were "
    "recomputed; no candidate was re-evaluated."
)


class RerankedCandidate(BaseModel):
    """One evaluated Pareto candidate under a new weighting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, description="1 is the best weighted score.")
    candidate_hash: str = Field(min_length=64, max_length=64)
    evaluation: CandidateEvaluation
    source_rank: int | None = Field(
        default=None,
        description="Pareto rank recorded by the source run, if any.",
    )
    crowding_distance: float | None = Field(default=None, ge=0)


class ParetoReranking(BaseModel):
    """Pure derived view of one run's Pareto front under new weights."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_algorithm: Algorithm
    source_seed: int = Field(ge=0)
    source_baseline_hash: str = Field(min_length=64, max_length=64)
    source_evaluations: int = Field(ge=0)
    weights: tuple[tuple[str, float], ...]
    weight_note: str
    items: tuple[RerankedCandidate, ...]
    recommended_candidate_hash: str | None = Field(
        default=None,
        description="Best feasible re-ranked candidate, or None if none exists.",
    )
    model_note: str = Field(default=MODEL_NOTE)
    search_note: str = Field(default=SEARCH_NOTE)
    rerank_note: str = Field(default=RERANK_NOTE)


def _resolve_weights(
    run: OptimizationRun,
    weights: Mapping[ObjectiveKind, float] | None,
) -> dict[ObjectiveKind, float]:
    configured = {objective.kind: objective.weight for objective in run.settings.objectives}
    if not configured:
        raise ValueError("The source run has no objectives to re-rank.")
    if weights is None:
        resolved = configured
    else:
        missing = sorted(kind.value for kind in configured if kind not in weights)
        extra = sorted(kind.value for kind in weights if kind not in configured)
        if missing or extra:
            detail: list[str] = []
            if missing:
                detail.append("missing: " + ", ".join(missing))
            if extra:
                detail.append("unknown: " + ", ".join(extra))
            raise ValueError(
                "Re-ranking weights must name exactly the source objectives ("
                + "; ".join(detail)
                + ")."
            )
        resolved = {kind: float(weights[kind]) for kind in configured}
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
        for value in resolved.values()
    ):
        raise ValueError("Re-ranking weights must be finite and non-negative.")
    total = sum(resolved.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"Re-ranking weights must sum to 1; got {total:.12g}")
    return resolved


def _reweighted(
    evaluation: CandidateEvaluation,
    weights: dict[ObjectiveKind, float],
) -> CandidateEvaluation:
    objectives = tuple(
        value.model_copy(
            update={
                "weight": weights[value.kind],
                "contribution": value.normalized_value * weights[value.kind],
            }
        )
        for value in evaluation.objectives
    )
    score = sum(value.contribution for value in objectives)
    return evaluation.model_copy(
        update={"objectives": objectives, "weighted_score": score}
    )


def _source_front(run: OptimizationRun) -> list[tuple[CandidateEvaluation, int | None, float | None]]:
    if run.pareto_front:
        return [
            (record.evaluation, record.rank, record.crowding_distance)
            for record in run.pareto_front
        ]
    evaluations = [record.evaluation for record in run.candidates]
    return [(evaluation, None, None) for evaluation in pareto_front(evaluations)]


def rerank_pareto_front(
    run: OptimizationRun,
    weights: Mapping[ObjectiveKind, float] | None = None,
) -> ParetoReranking:
    """Return a new weighted order over ``run``'s evaluated Pareto front.

    ``weights`` maps every selected :class:`ObjectiveKind` to a finite,
    non-negative value summing to 1. Passing ``None`` reuses the source run's
    weights, which yields the same order as the stored result. The source run is
    never changed and no evaluation is performed.
    """
    resolved = _resolve_weights(run, weights)
    rankable: list[tuple[CandidateEvaluation, int | None, float | None]] = []
    for evaluation, source_rank, crowding in _source_front(run):
        if not evaluation.feasible:
            continue
        rankable.append((_reweighted(evaluation, resolved), source_rank, crowding))
    rankable.sort(
        key=lambda item: (item[0].weighted_score, item[0].candidate_hash)
    )
    items = tuple(
        RerankedCandidate(
            rank=index + 1,
            candidate_hash=evaluation.candidate_hash,
            evaluation=evaluation,
            source_rank=source_rank,
            crowding_distance=crowding,
        )
        for index, (evaluation, source_rank, crowding) in enumerate(rankable)
    )
    weight_note = (
        "Re-ranking weights: "
        + ", ".join(
            f"{kind.value}={value:g}" for kind, value in resolved.items()
        )
        + ". This is an order over evaluated feasible candidates only, not a "
        "global optimum."
    )
    return ParetoReranking(
        source_algorithm=run.algorithm,
        source_seed=run.seed,
        source_baseline_hash=run.baseline.candidate_hash,
        source_evaluations=run.evaluations,
        weights=tuple((kind.value, value) for kind, value in resolved.items()),
        weight_note=weight_note,
        items=items,
        recommended_candidate_hash=items[0].candidate_hash if items else None,
    )


def reranking_to_json(reranking: ParetoReranking, *, indent: int | None = None) -> str:
    """Serialize one re-ranking deterministically; no timestamp is added."""
    return json.dumps(
        reranking.model_dump(mode="json"),
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
    )


def reranking_to_csv(reranking: ParetoReranking) -> str:
    """Serialize one re-ranking to spreadsheet-safe CSV."""
    columns = (
        "rank",
        "candidate_hash",
        "weighted_score",
        "source_rank",
        "crowding_distance",
        "source_algorithm",
        "source_seed",
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)

    def cell(value: Any) -> str:
        return neutralize_cell(value)

    for item in reranking.items:
        writer.writerow(
            [
                cell(item.rank),
                cell(item.candidate_hash),
                cell(f"{item.evaluation.weighted_score:.12g}"),
                cell(item.source_rank),
                cell(item.crowding_distance),
                cell(reranking.source_algorithm.value),
                cell(reranking.source_seed),
            ]
        )
    return buffer.getvalue()


__all__ = [
    "RERANK_NOTE",
    "ParetoReranking",
    "RerankedCandidate",
    "rerank_pareto_front",
    "reranking_to_csv",
    "reranking_to_json",
]
