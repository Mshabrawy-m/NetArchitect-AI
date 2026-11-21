"""Bounded demand/capacity sensitivity for an existing optimization run.

Every number here is a modeled estimate. The analysis re-evaluates a small,
deterministic subset of an existing run's candidates against perturbed copies of
the source twin. It never mutates the source twin or run, uses no randomness,
writes no files, and stops at a bounded wall-clock deadline.

Robust definition
-----------------
A candidate is reported as **robust** only when all of the following hold:

1. it is feasible in the source run (including the nominal scenario);
2. it was evaluated and feasible in *every* configured perturbation scenario;
3. in every perturbation scenario its recomputed weighted score is no more than
   ``ROBUST_SCORE_TOLERANCE`` (0.05) above the perturbed baseline's recomputed
   weighted score; and
4. the report completed all configured scenarios.

The score comparison uses the same 0..1 normalized weighted score as the source
run, so the tolerance is an absolute score difference, not a percent change.
If any condition fails, the candidate is not robust. If no candidate is robust,
the report recommends none rather than relaxing the definition.
"""

from __future__ import annotations

import csv
import io
import json
import time
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.limits import (
    DEFAULT_SENSITIVITY_RUNTIME_SECONDS,
    MAX_SENSITIVITY_CANDIDATES,
    MAX_SENSITIVITY_RUNTIME_SECONDS,
    MAX_SENSITIVITY_SCENARIOS,
)
from core.csv_safe import neutralize_cell
from core.exceptions import LimitsExceededError, OptimizationRuntimeExceeded
from digital_twin import DigitalTwin
from simulation import twin_fingerprint
from simulation.models import MODEL_NOTE

from .evaluator import EvaluationCache, evaluate_candidate
from .models import (
    Algorithm,
    CandidateEvaluation,
    OptimizationRun,
    StopReason,
)

ROBUST_SCORE_TOLERANCE = 0.05

ROBUST_DEFINITION = (
    "Robust means feasible in the source run and in every perturbation scenario, "
    "with a recomputed weighted score at most 0.05 above the perturbed baseline "
    "in every scenario; an incomplete report marks no candidate robust."
)

class SensitivityScenario(BaseModel):
    """One bounded multiplicative demand/capacity perturbation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, description="Stable scenario identifier.")
    label: str = Field(min_length=1, description="Human-readable scenario label.")
    demand_multiplier: float = Field(
        default=1.0,
        gt=0,
        le=2.0,
        description="Multiplier applied to every demand bandwidth.",
    )
    capacity_multiplier: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Multiplier applied to every baseline link capacity.",
    )
    rationale: str = Field(
        default="Modeled perturbation of stated demand or capacity assumptions.",
        description="Why this perturbation is included.",
    )


# Defined after the model so the default tuple is correctly typed.
DEFAULT_SENSITIVITY_SCENARIOS = (
    SensitivityScenario(
        id="demand_plus_25",
        label="Demand +25%",
        demand_multiplier=1.25,
    ),
    SensitivityScenario(
        id="demand_plus_50",
        label="Demand +50%",
        demand_multiplier=1.5,
    ),
    SensitivityScenario(
        id="capacity_minus_20",
        label="Capacity -20%",
        capacity_multiplier=0.8,
    ),
    SensitivityScenario(
        id="combined_stress",
        label="Demand +50%, capacity -20%",
        demand_multiplier=1.5,
        capacity_multiplier=0.8,
    ),
)


class SensitivityCase(BaseModel):
    """One candidate's modeled evaluation under one perturbation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_hash: str = Field(min_length=64, max_length=64)
    feasible: bool
    weighted_score: float = Field(ge=0)
    served_demand_ratio: float = Field(ge=0, le=1)
    max_utilization_percent: float = Field(ge=0)
    violated_constraints: tuple[str, ...] = Field(default_factory=tuple)


class SensitivityScenarioResult(BaseModel):
    """Perturbed baseline plus candidate cases for one scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: SensitivityScenario
    twin_fingerprint: str = Field(min_length=64, max_length=64)
    baseline: SensitivityCase
    cases: tuple[SensitivityCase, ...]


class SensitivityReport(BaseModel):
    """Deterministic, bounded sensitivity result with explicit provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_algorithm: Algorithm
    source_seed: int = Field(ge=0)
    source_evaluations: int = Field(ge=0)
    source_baseline_hash: str = Field(min_length=64, max_length=64)
    source_twin_fingerprint: str = Field(min_length=64, max_length=64)
    evaluated_candidates: int = Field(ge=0)
    evaluations: int = Field(ge=0)
    stop_reason: StopReason
    score_tolerance: float = Field(default=ROBUST_SCORE_TOLERANCE, ge=0)
    scenarios: tuple[SensitivityScenarioResult, ...]
    robust_candidate_hashes: tuple[str, ...] = Field(default_factory=tuple)
    recommended_candidate_hash: str | None = None
    subset_note: str = ""
    model_note: str = Field(default=MODEL_NOTE)
    robust_definition: str = Field(default=ROBUST_DEFINITION)

    @model_validator(mode="after")
    def _validate_result(self) -> SensitivityReport:
        if self.evaluated_candidates > MAX_SENSITIVITY_CANDIDATES:
            raise ValueError("A sensitivity report exceeds the candidate bound.")
        if len(self.scenarios) > MAX_SENSITIVITY_SCENARIOS:
            raise ValueError("A sensitivity report exceeds the scenario bound.")
        if (
            self.recommended_candidate_hash is not None
            and self.recommended_candidate_hash not in self.robust_candidate_hashes
        ):
            raise ValueError("A recommendation must be one of the robust candidates.")
        return self


def _validate_inputs(
    scenarios: Sequence[SensitivityScenario],
    max_candidates: int,
    max_runtime_seconds: float,
) -> None:
    if not scenarios:
        raise ValueError("Sensitivity analysis needs at least one scenario.")
    if len(scenarios) > MAX_SENSITIVITY_SCENARIOS:
        raise LimitsExceededError(
            f"At most {MAX_SENSITIVITY_SCENARIOS} sensitivity scenarios are "
            f"allowed; got {len(scenarios)}."
        )
    if max_candidates < 1 or max_candidates > MAX_SENSITIVITY_CANDIDATES:
        raise LimitsExceededError(
            f"At most {MAX_SENSITIVITY_CANDIDATES} sensitivity candidates are "
            f"allowed; got {max_candidates}."
        )
    if max_runtime_seconds <= 0 or max_runtime_seconds > MAX_SENSITIVITY_RUNTIME_SECONDS:
        raise LimitsExceededError(
            "Sensitivity runtime must be between 0 and "
            f"{MAX_SENSITIVITY_RUNTIME_SECONDS} seconds."
        )
    ids = [scenario.id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("Sensitivity scenario ids must be unique.")


def _selected_evaluations(
    run: OptimizationRun,
    max_candidates: int,
) -> tuple[CandidateEvaluation, ...]:
    others = [
        record.evaluation
        for record in run.candidates
        if record.evaluation.candidate_hash != run.baseline.candidate_hash
    ]
    feasible = sorted(
        (item for item in others if item.feasible),
        key=lambda item: (item.weighted_score, item.candidate_hash),
    )
    infeasible = sorted(
        (item for item in others if not item.feasible),
        key=lambda item: (
            len(item.violated_constraints),
            item.weighted_score,
            item.candidate_hash,
        ),
    )
    return tuple((feasible + infeasible)[:max_candidates])


def _perturb_twin(
    baseline_twin: DigitalTwin,
    scenario: SensitivityScenario,
) -> DigitalTwin:
    demands = tuple(
        demand.model_copy(
            update={
                "bandwidth_mbps": demand.bandwidth_mbps * scenario.demand_multiplier
            }
        )
        for demand in baseline_twin.demands
    )
    links = [
        link.model_copy(
            update={
                "capacity_mbps": link.capacity_mbps * scenario.capacity_multiplier
            }
        )
        for link in baseline_twin.topology.links
    ]
    topology = baseline_twin.topology.model_copy(update={"links": links})
    return baseline_twin.model_copy(update={"topology": topology, "demands": demands})


def _case(evaluation: CandidateEvaluation) -> SensitivityCase:
    return SensitivityCase(
        candidate_hash=evaluation.candidate_hash,
        feasible=evaluation.feasible,
        weighted_score=evaluation.weighted_score,
        served_demand_ratio=evaluation.metrics.served_demand_ratio,
        max_utilization_percent=evaluation.metrics.max_utilization_percent,
        violated_constraints=evaluation.violated_constraints,
    )


def analyze_sensitivity(
    baseline_twin: DigitalTwin,
    run: OptimizationRun,
    *,
    scenarios: Sequence[SensitivityScenario] = DEFAULT_SENSITIVITY_SCENARIOS,
    max_candidates: int = MAX_SENSITIVITY_CANDIDATES,
    max_runtime_seconds: float = DEFAULT_SENSITIVITY_RUNTIME_SECONDS,
    deadline: float | None = None,
) -> SensitivityReport:
    """Re-evaluate a bounded candidate subset under bounded perturbations.

    ``deadline`` is an absolute monotonic deadline shared by all scenarios; when
    omitted, a fresh ``max_runtime_seconds`` budget is used. The report is
    deterministic for identical inputs, but wall-clock limits can make results
    machine-dependent, so any incomplete run is labeled ``runtime_limit`` and
    marks no candidate robust.
    """
    _validate_inputs(scenarios, max_candidates, max_runtime_seconds)
    selected = _selected_evaluations(run, max_candidates)
    resolved_deadline = (
        deadline
        if deadline is not None
        else time.perf_counter() + max_runtime_seconds
    )
    stop_reason = StopReason.completed
    scenario_results: list[SensitivityScenarioResult] = []
    total_evaluations = 0
    nominal_by_hash = {
        item.candidate_hash: item for item in selected
    }

    for scenario in scenarios:
        perturbed = _perturb_twin(baseline_twin, scenario)
        try:
            cache = EvaluationCache.for_run(perturbed, run.settings)
            baseline_case = _case(
                evaluate_candidate(
                    perturbed,
                    run.baseline.candidate,
                    run.settings,
                    cache=cache,
                    deadline=resolved_deadline,
                )
            )
            cases: list[SensitivityCase] = []
            for evaluation in selected:
                cases.append(
                    _case(
                        evaluate_candidate(
                            perturbed,
                            evaluation.candidate,
                            run.settings,
                            cache=cache,
                            deadline=resolved_deadline,
                        )
                    )
                )
        except OptimizationRuntimeExceeded:
            stop_reason = StopReason.runtime_limit
            break
        total_evaluations += cache.misses
        scenario_results.append(
            SensitivityScenarioResult(
                scenario=scenario,
                twin_fingerprint=twin_fingerprint(perturbed),
                baseline=baseline_case,
                cases=tuple(cases),
            )
        )

    robust: list[str] = []
    if stop_reason is StopReason.completed and len(scenario_results) == len(scenarios):
        for candidate_hash, nominal in nominal_by_hash.items():
            if not nominal.feasible:
                continue
            is_robust = True
            for result in scenario_results:
                case = next(
                    (
                        item
                        for item in result.cases
                        if item.candidate_hash == candidate_hash
                    ),
                    None,
                )
                if case is None or not case.feasible:
                    is_robust = False
                    break
                if case.weighted_score > (
                    result.baseline.weighted_score + ROBUST_SCORE_TOLERANCE + 1e-12
                ):
                    is_robust = False
                    break
            if is_robust:
                robust.append(candidate_hash)

    robust.sort(
        key=lambda candidate_hash: (
            nominal_by_hash[candidate_hash].weighted_score,
            candidate_hash,
        )
    )
    subset_note = (
        f"Evaluated {len(selected)} of {len(run.candidates)} stored candidates: "
        "feasible designs by weighted score first, then infeasible designs by "
        "violation count. The perturbed baseline is always re-evaluated and is "
        "not counted as a candidate."
    )
    return SensitivityReport(
        source_algorithm=run.algorithm,
        source_seed=run.seed,
        source_evaluations=run.evaluations,
        source_baseline_hash=run.baseline.candidate_hash,
        source_twin_fingerprint=twin_fingerprint(baseline_twin),
        evaluated_candidates=len(selected),
        evaluations=total_evaluations,
        stop_reason=stop_reason,
        scenarios=tuple(scenario_results),
        robust_candidate_hashes=tuple(robust),
        recommended_candidate_hash=robust[0] if robust else None,
        subset_note=subset_note,
    )


def sensitivity_to_json(
    report: SensitivityReport,
    *,
    indent: int | None = None,
) -> str:
    """Serialize one sensitivity report deterministically."""
    return json.dumps(
        report.model_dump(mode="json"),
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
    )


def sensitivity_to_csv(report: SensitivityReport) -> str:
    """Serialize one sensitivity report to spreadsheet-safe CSV."""
    columns = (
        "row_kind",
        "scenario_id",
        "scenario_label",
        "demand_multiplier",
        "capacity_multiplier",
        "candidate_hash",
        "feasible",
        "weighted_score",
        "served_demand_ratio",
        "max_utilization_percent",
        "violated_constraints",
        "source_algorithm",
        "source_seed",
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)

    def write(row_kind: str, scenario, case: SensitivityCase) -> None:
        writer.writerow(
            [
                neutralize_cell(value)
                for value in (
                    row_kind,
                    scenario.id,
                    scenario.label,
                    scenario.demand_multiplier,
                    scenario.capacity_multiplier,
                    case.candidate_hash,
                    case.feasible,
                    f"{case.weighted_score:.12g}",
                    f"{case.served_demand_ratio:.12g}",
                    f"{case.max_utilization_percent:.12g}",
                    "; ".join(case.violated_constraints),
                    report.source_algorithm.value,
                    report.source_seed,
                )
            ]
        )

    for result in report.scenarios:
        write("baseline", result.scenario, result.baseline)
        for case in result.cases:
            write("candidate", result.scenario, case)
    return buffer.getvalue()


__all__ = [
    "DEFAULT_SENSITIVITY_SCENARIOS",
    "ROBUST_DEFINITION",
    "ROBUST_SCORE_TOLERANCE",
    "SensitivityCase",
    "SensitivityReport",
    "SensitivityScenario",
    "SensitivityScenarioResult",
    "analyze_sensitivity",
    "sensitivity_to_csv",
    "sensitivity_to_json",
]
