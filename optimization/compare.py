"""Baseline-versus-algorithm comparison with explicit trade-offs.

The helper never declares a global optimum. It reports per-objective deltas for
each algorithm's best feasible candidate and the evaluated Pareto front. A
single "best" is named only as the best weighted score *under the stated
weights*, and the weights are listed in the report.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from simulation.models import MODEL_NOTE

from .models import (
    SEARCH_NOTE,
    Algorithm,
    CandidateEvaluation,
    CandidateRecord,
    ObjectiveDirection,
    ObjectiveKind,
    OptimizationRun,
    StopReason,
)


class ObjectiveDelta(BaseModel):
    """Raw and relative change of one objective from baseline to candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObjectiveKind
    label: str
    unit: str
    direction: ObjectiveDirection
    baseline_value: float
    candidate_value: float
    absolute_change: float = Field(
        description="candidate_value - baseline_value; sign follows the unit."
    )
    relative_change: float | None = Field(
        default=None,
        description=(
            "absolute_change divided by the absolute baseline value, or None "
            "when the baseline value is zero."
        ),
    )
    improved: bool = Field(
        description="True only when the candidate is strictly better."
    )
    weight: float | None = Field(
        default=None,
        description="Weighted-sum weight used in the compared run, if any.",
    )


class AlgorithmComparison(BaseModel):
    """One algorithm's best feasible result and Pareto set versus baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Algorithm
    stop_reason: StopReason
    evaluations: int = Field(ge=0)
    best: CandidateEvaluation | None = Field(
        default=None,
        description=(
            "Best feasible candidate by weighted score, or None when the run "
            "found no feasible candidate."
        ),
    )
    deltas: tuple[ObjectiveDelta, ...] = Field(default_factory=tuple)
    trade_offs: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Human-readable objectives that became worse than baseline.",
    )
    pareto_front: tuple[CandidateRecord, ...] = Field(
        default_factory=tuple,
        description="Evaluated non-dominated feasible set; empty for weighted-only runs.",
    )


class ComparisonReport(BaseModel):
    """Baseline plus one comparison entry per algorithm run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline: CandidateEvaluation
    comparisons: tuple[AlgorithmComparison, ...] = Field(default_factory=tuple)
    weighted_best_algorithm: Algorithm | None = Field(
        default=None,
        description=(
            "Algorithm whose best feasible candidate has the lowest weighted "
            "score under the stated weights; not a global-optimum claim."
        ),
    )
    weight_note: str = ""
    notes: tuple[str, ...] = Field(default_factory=tuple)


def _weight_for(run: OptimizationRun, kind: ObjectiveKind) -> float | None:
    for objective in run.settings.objectives:
        if objective.kind is kind:
            return objective.weight
    return None


def objective_deltas(
    baseline: CandidateEvaluation,
    candidate: CandidateEvaluation,
    *,
    weights: dict[ObjectiveKind, float] | None = None,
) -> tuple[ObjectiveDelta, ...]:
    """Return one delta per shared objective, in the baseline's order."""
    candidate_by_kind = {
        value.kind: value for value in candidate.objectives
    }
    deltas: list[ObjectiveDelta] = []
    for base in baseline.objectives:
        after = candidate_by_kind.get(base.kind)
        if after is None:  # pragma: no cover - same settings produce the same set
            continue
        change = after.raw_value - base.raw_value
        if base.raw_value == 0:
            relative = None
        else:
            relative = change / abs(base.raw_value)
        if base.direction is ObjectiveDirection.minimize:
            improved = after.raw_value < base.raw_value
        else:
            improved = after.raw_value > base.raw_value
        deltas.append(
            ObjectiveDelta(
                kind=base.kind,
                label=base.label,
                unit=base.unit,
                direction=base.direction,
                baseline_value=base.raw_value,
                candidate_value=after.raw_value,
                absolute_change=change,
                relative_change=relative,
                improved=improved,
                weight=None if weights is None else weights.get(base.kind),
            )
        )
    return tuple(deltas)


def trade_off_messages(
    deltas: Sequence[ObjectiveDelta],
) -> tuple[str, ...]:
    """Describe each objective that moved in the worse direction."""
    messages: list[str] = []
    for delta in deltas:
        if delta.improved or delta.absolute_change == 0:
            continue
        weight = (
            ""
            if delta.weight is None
            else f" (weight {delta.weight:g})"
        )
        messages.append(
            f"{delta.label} worsened from {delta.baseline_value:g} to "
            f"{delta.candidate_value:g} {delta.unit}{weight}"
        )
    return tuple(messages)


def _weight_note(run: OptimizationRun) -> str:
    if not run.settings.objectives:
        return "No weighted objective was configured."
    parts = [
        f"{objective.kind.value}={objective.weight:g}"
        for objective in run.settings.objectives
    ]
    return (
        "The weighted 'best' uses weights "
        + ", ".join(parts)
        + ". It is the best weighted score among the evaluated candidates for "
        "those weights, not a global optimum or an unconditional 'best overall'."
    )


def compare_runs(
    runs: Sequence[OptimizationRun],
) -> ComparisonReport:
    """Compare algorithm runs that share one baseline and one problem setting.

    Raises ``ValueError`` when runs do not share identical settings or baseline
    fingerprints, because differences would otherwise be unattributable.
    """
    if not runs:
        raise ValueError("compare_runs needs at least one optimization run.")
    first = runs[0]
    baseline_fingerprint = first.baseline.candidate_hash
    settings_dump = first.settings.model_dump(mode="json")
    for run in runs[1:]:
        if run.settings.model_dump(mode="json") != settings_dump:
            raise ValueError(
                "Runs can only be compared when their optimization settings "
                "are identical."
            )
        if run.baseline.candidate_hash != baseline_fingerprint:
            raise ValueError(
                "Runs can only be compared when they share the same baseline."
            )

    weights = {
        objective.kind: objective.weight
        for objective in first.settings.objectives
    }
    comparisons: list[AlgorithmComparison] = []
    for run in runs:
        if run.best is None:
            deltas: tuple[ObjectiveDelta, ...] = ()
            trade_offs: tuple[str, ...] = ()
        else:
            deltas = objective_deltas(
                run.baseline,
                run.best.evaluation,
                weights=weights,
            )
            trade_offs = trade_off_messages(deltas)
        comparisons.append(
            AlgorithmComparison(
                algorithm=run.algorithm,
                stop_reason=run.stop_reason,
                evaluations=run.evaluations,
                best=None if run.best is None else run.best.evaluation,
                deltas=deltas,
                trade_offs=trade_offs,
                pareto_front=run.pareto_front,
            )
        )

    scored = [
        comparison
        for comparison in comparisons
        if comparison.best is not None
    ]
    weighted_best = (
        min(
            scored,
            key=lambda item: (
                item.best.weighted_score,
                item.best.candidate_hash,
            ),
        ).algorithm
        if scored
        else None
    )
    notes = (
        MODEL_NOTE,
        SEARCH_NOTE,
        (
            "Pareto fronts contain evaluated candidates only; unevaluated "
            "designs cannot be ranked."
        ),
        (
            "Algorithm results are comparable only under identical settings, "
            "seeds, limits, and baseline."
        ),
    )
    return ComparisonReport(
        baseline=first.baseline,
        comparisons=tuple(comparisons),
        weighted_best_algorithm=weighted_best,
        weight_note=_weight_note(first),
        notes=notes,
    )


__all__ = [
    "AlgorithmComparison",
    "ComparisonReport",
    "ObjectiveDelta",
    "compare_runs",
    "objective_deltas",
    "trade_off_messages",
]
