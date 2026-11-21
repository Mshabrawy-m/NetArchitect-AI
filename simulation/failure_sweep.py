"""Bounded N-1/N-2 failure sweeps with deterministic impact ranking.

Every result is a modeled estimate from the supplied twin and assumptions. The
sweep never changes the baseline twin, uses no randomness, and shares one
runtime deadline and router cache across all evaluated cases.

Model rules
-----------
* N-1 plans one case per link and one per device, bounded by ``MAX_EDGES`` and
  ``MAX_NODES``.
* N-2 plans pairs only from the caller's chosen subset. The full pair count is
  reported even when only the first ``MAX_N2_PAIRS`` pairs are evaluated.
* A shared-risk group is a failure-domain annotation. Targeting any member
  marks every device and link in that group down; the group id is recorded on
  the case for provenance.
* Impact is a deterministic modeled score, not a measured availability figure.
  It combines served-demand loss (50%), served-bandwidth loss (30%), and
  utilization increase (20%), each normalized to 0..1. Ranking uses descending
  score, then newly unserved count, then case id.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import math
from collections.abc import Callable, Sequence
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from config.limits import (
    MAX_EDGES,
    MAX_N2_PAIRS,
    MAX_NODES,
)
from core.csv_safe import neutralize_cell
from core.exceptions import (
    LimitsExceededError,
    ScenarioValidationError,
    SimulationRuntimeExceeded,
)
from digital_twin import DigitalTwin, apply_failure
from network.routing.sparse import SparseRouter

from .evaluator import _check_deadline, _resolve_deadline, evaluate, twin_reference
from .models import (
    MODEL_NOTE,
    NetworkState,
    SimulationAssumptions,
    TwinReference,
)


class FailureSweepDepth(str, Enum):
    """Supported failure depth."""

    n1 = "n1"  # One link or device at a time.
    n2 = "n2"  # Pairs from a caller-chosen subset.


class FailureSweepStopReason(str, Enum):
    """Why a sweep or slice stopped, independent of how many cases it evaluated."""

    completed = "completed"
    case_limit = "case_limit"
    cancelled = "cancelled"
    runtime_limit = "runtime_limit"
    no_failures = "no_failures"


class FailureCasePlan(BaseModel):
    """One deterministic failure case before evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(description="Stable identifier for this case.")
    depth: FailureSweepDepth
    target_link_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Links explicitly targeted by this case.",
    )
    target_device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Devices explicitly targeted by this case.",
    )
    failed_link_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Links actually marked down after shared-risk expansion.",
    )
    failed_device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Devices actually marked down after shared-risk expansion.",
    )
    shared_risk_group_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Groups that expanded this case beyond its explicit targets.",
    )


class FailureSweepPlan(BaseModel):
    """The bounded case list used by one sweep or slice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    depth: FailureSweepDepth
    max_pairs: int = Field(ge=1)
    cases: tuple[FailureCasePlan, ...]
    total_cases: int = Field(
        ge=0,
        description="Full case count before slicing or the N-2 pair cap.",
    )
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class FailureImpact(BaseModel):
    """Deterministic modeled impact of one failure case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    served_demand_delta: int = Field(
        description="Baseline served demands minus case served demands."
    )
    served_ratio_delta: float = Field(
        description="Baseline served ratio minus case served ratio."
    )
    served_mbps_delta: float = Field(
        description="Baseline served Mbps minus case served Mbps."
    )
    max_utilization_delta: float = Field(
        description="Case maximum utilization minus baseline, in percentage points."
    )
    newly_unserved_count: int = Field(ge=0)
    overloaded_link_delta: int = Field(
        description="Case overloaded links minus baseline."
    )
    impact_score: float = Field(
        ge=0,
        le=100,
        description="Weighted modeled impact score on a 0..100 scale.",
    )


class FailureCase(BaseModel):
    """One evaluated failure case and its modeled impact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, description="Impact rank within the evaluated cases.")
    plan: FailureCasePlan
    state: NetworkState
    impact: FailureImpact


class FailureSweepResult(BaseModel):
    """Deterministic result of one sweep or one bounded slice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline: TwinReference
    assumptions: SimulationAssumptions
    depth: FailureSweepDepth
    max_pairs: int = Field(ge=1)
    total_cases: int = Field(ge=0)
    start: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=1)
    evaluated_cases: int = Field(ge=0)
    stop_reason: FailureSweepStopReason
    cases: tuple[FailureCase, ...]
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    model_note: str = Field(default=MODEL_NOTE)

    @property
    def shown_cases(self) -> int:
        """Number of evaluated cases included in this result."""
        return len(self.cases)


def _case_id(
    target_link_ids: Sequence[str],
    target_device_ids: Sequence[str],
) -> str:
    tokens = sorted(
        [
            *(f"device:{device_id}" for device_id in target_device_ids),
            *(f"link:{link_id}" for link_id in target_link_ids),
        ]
    )
    return json.dumps(tokens, separators=(",", ":"), ensure_ascii=False)


def _expand_shared_risk(
    twin: DigitalTwin,
    target_link_ids: Sequence[str],
    target_device_ids: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return failed links, failed devices, and expanded group ids."""
    links = set(target_link_ids)
    devices = set(target_device_ids)
    group_ids: set[str] = set()
    for group in twin.shared_risk_groups:
        group_links = set(group.link_ids)
        group_devices = set(group.device_ids)
        if links & group_links or devices & group_devices:
            links.update(group_links)
            devices.update(group_devices)
            group_ids.add(group.id)
    return (
        tuple(sorted(links)),
        tuple(sorted(devices)),
        tuple(sorted(group_ids)),
    )


def _validate_max_pairs(max_pairs: int) -> int:
    if max_pairs < 1 or max_pairs > MAX_N2_PAIRS:
        raise LimitsExceededError(
            f"Requested {max_pairs} N-2 pairs; the limit is {MAX_N2_PAIRS}."
        )
    return max_pairs


def _target_tokens(
    *,
    selected_link_ids: Sequence[str],
    selected_device_ids: Sequence[str],
    known_link_ids: set[str],
    known_device_ids: set[str],
) -> list[tuple[str, str]]:
    unknown_links = sorted(set(selected_link_ids) - known_link_ids)
    unknown_devices = sorted(set(selected_device_ids) - known_device_ids)
    if unknown_links:
        raise ScenarioValidationError(
            "Unknown N-2 link(s): " + ", ".join(unknown_links)
        )
    if unknown_devices:
        raise ScenarioValidationError(
            "Unknown N-2 device(s): " + ", ".join(unknown_devices)
        )
    return [
        *[("device", item) for item in sorted(set(selected_device_ids))],
        *[("link", item) for item in sorted(set(selected_link_ids))],
    ]


def plan_failure_sweep(
    twin: DigitalTwin,
    depth: FailureSweepDepth | str,
    *,
    selected_link_ids: Sequence[str] = (),
    selected_device_ids: Sequence[str] = (),
    max_pairs: int = MAX_N2_PAIRS,
) -> FailureSweepPlan:
    """Build the deterministic, bounded plan for one failure sweep.

    The caller may pass a string depth; unknown values raise
    :class:`ScenarioValidationError`. Shared-risk groups expand targets but do
    not create extra cases, so an N-1 sweep remains one case per element.
    """
    try:
        resolved_depth = FailureSweepDepth(depth)
    except ValueError as error:
        valid = ", ".join(item.value for item in FailureSweepDepth)
        raise ScenarioValidationError(
            f"Unknown failure sweep depth {depth!r}; expected one of: {valid}."
        ) from error
    resolved_max_pairs = _validate_max_pairs(max_pairs)
    link_ids = sorted(link.id for link in twin.topology.links)
    device_ids = sorted(device.id for device in twin.topology.devices)
    if len(link_ids) > MAX_EDGES:
        raise LimitsExceededError(
            f"Twin has {len(link_ids)} links; the failure-sweep limit is "
            f"{MAX_EDGES}."
        )
    if len(device_ids) > MAX_NODES:
        raise LimitsExceededError(
            f"Twin has {len(device_ids)} devices; the failure-sweep limit is "
            f"{MAX_NODES}."
        )

    warnings: list[str] = []
    if resolved_depth is FailureSweepDepth.n1:
        targets: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
            ((link_id,), ()) for link_id in link_ids
        ]
        targets.extend(((), (device_id,)) for device_id in device_ids)
        total_cases = len(targets)
    else:
        tokens = _target_tokens(
            selected_link_ids=selected_link_ids,
            selected_device_ids=selected_device_ids,
            known_link_ids=set(link_ids),
            known_device_ids=set(device_ids),
        )
        total_cases = math.comb(len(tokens), 2)
        if total_cases > resolved_max_pairs:
            warnings.append(
                f"The N-2 subset has {total_cases} pairs; only the first "
                f"{resolved_max_pairs} were planned."
            )
            pairs = itertools.islice(itertools.combinations(tokens, 2), resolved_max_pairs)
        else:
            pairs = itertools.combinations(tokens, 2)
        targets = [
            (
                tuple(item for kind, item in pair if kind == "link"),
                tuple(item for kind, item in pair if kind == "device"),
            )
            for pair in pairs
        ]
        if total_cases == 0:
            warnings.append(
                "An N-2 sweep requires a chosen subset of at least two entities."
            )

    cases: list[FailureCasePlan] = []
    for target_links, target_devices in targets:
        failed_links, failed_devices, group_ids = _expand_shared_risk(
            twin, target_links, target_devices
        )
        cases.append(
            FailureCasePlan(
                case_id=_case_id(target_links, target_devices),
                depth=resolved_depth,
                target_link_ids=tuple(sorted(target_links)),
                target_device_ids=tuple(sorted(target_devices)),
                failed_link_ids=failed_links,
                failed_device_ids=failed_devices,
                shared_risk_group_ids=group_ids,
            )
        )
    return FailureSweepPlan(
        depth=resolved_depth,
        max_pairs=resolved_max_pairs,
        cases=tuple(cases),
        total_cases=total_cases,
        warnings=tuple(warnings),
    )


def _normalized_loss(baseline: float, case: float) -> float:
    if baseline <= 0:
        return 0.0
    return min(1.0, max(0.0, (baseline - case) / baseline))


def _impact(baseline: NetworkState, case: NetworkState) -> FailureImpact:
    baseline_served = {
        demand.name for demand in baseline.demands if demand.served
    }
    case_served = {demand.name for demand in case.demands if demand.served}
    utilization_increase = case.max_utilization_percent - baseline.max_utilization_percent
    utilization_component = min(
        1.0,
        max(0.0, utilization_increase / max(100.0, baseline.max_utilization_percent)),
    )
    score = 100.0 * (
        0.5 * _normalized_loss(baseline.served_demand_ratio, case.served_demand_ratio)
        + 0.3
        * _normalized_loss(baseline.served_demand_mbps, case.served_demand_mbps)
        + 0.2 * utilization_component
    )
    return FailureImpact(
        served_demand_delta=baseline.served_demand_count - case.served_demand_count,
        served_ratio_delta=round(
            baseline.served_demand_ratio - case.served_demand_ratio, 6
        ),
        served_mbps_delta=round(
            baseline.served_demand_mbps - case.served_demand_mbps, 6
        ),
        max_utilization_delta=round(utilization_increase, 6),
        newly_unserved_count=len(baseline_served - case_served),
        overloaded_link_delta=(
            case.overloaded_link_count - baseline.overloaded_link_count
        ),
        impact_score=round(score, 6),
    )


def _empty_result(
    *,
    baseline_twin: DigitalTwin,
    assumptions: SimulationAssumptions,
    plan: FailureSweepPlan,
    start: int,
    limit: int | None,
    stop_reason: FailureSweepStopReason,
) -> FailureSweepResult:
    return FailureSweepResult(
        baseline=twin_reference(baseline_twin),
        assumptions=assumptions,
        depth=plan.depth,
        max_pairs=plan.max_pairs,
        total_cases=plan.total_cases,
        start=start,
        limit=limit,
        evaluated_cases=0,
        stop_reason=stop_reason,
        cases=(),
        warnings=plan.warnings,
    )


def run_failure_sweep(
    baseline_twin: DigitalTwin,
    assumptions: SimulationAssumptions | None = None,
    *,
    depth: FailureSweepDepth | str = FailureSweepDepth.n1,
    selected_link_ids: Sequence[str] = (),
    selected_device_ids: Sequence[str] = (),
    max_pairs: int = MAX_N2_PAIRS,
    start: int = 0,
    limit: int | None = None,
    max_runtime_seconds: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> FailureSweepResult:
    """Evaluate a bounded slice of one failure sweep.

    ``start`` and ``limit`` select cases from the deterministic plan. The full
    case count stays visible in ``total_cases``, and a partial slice reports
    ``case_limit`` unless cancellation or the runtime budget stops it first.
    ``should_cancel`` is checked between cases and is the only caller-supplied
    callback; no threads, timers, or disk access are used.
    """
    if start < 0:
        raise ValueError(f"start must be non-negative, got {start}")
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be positive, got {limit}")

    resolved = (
        SimulationAssumptions()
        if assumptions is None
        else assumptions
        if isinstance(assumptions, SimulationAssumptions)
        else SimulationAssumptions.model_validate(assumptions)
    )
    plan = plan_failure_sweep(
        baseline_twin,
        depth,
        selected_link_ids=selected_link_ids,
        selected_device_ids=selected_device_ids,
        max_pairs=max_pairs,
    )
    if plan.total_cases == 0:
        return _empty_result(
            baseline_twin=baseline_twin,
            assumptions=resolved,
            plan=plan,
            start=start,
            limit=limit,
            stop_reason=FailureSweepStopReason.no_failures,
        )

    selected_plans = plan.cases[start : None if limit is None else start + limit]
    stop_reason = (
        FailureSweepStopReason.case_limit
        if start + len(selected_plans) < plan.total_cases
        else FailureSweepStopReason.completed
    )
    if not selected_plans:
        return _empty_result(
            baseline_twin=baseline_twin,
            assumptions=resolved,
            plan=plan,
            start=start,
            limit=limit,
            stop_reason=stop_reason,
        )

    deadline = _resolve_deadline(max_runtime_seconds, None)
    router_cache: dict[tuple[object, ...], SparseRouter] = {}
    try:
        baseline_state = evaluate(
            baseline_twin,
            resolved,
            _deadline=deadline,
            _router_cache=router_cache,
        )
    except SimulationRuntimeExceeded:
        return _empty_result(
            baseline_twin=baseline_twin,
            assumptions=resolved,
            plan=plan,
            start=start,
            limit=limit,
            stop_reason=FailureSweepStopReason.runtime_limit,
        )

    cases: list[FailureCase] = []
    for case_plan in selected_plans:
        if should_cancel is not None and should_cancel():
            stop_reason = FailureSweepStopReason.cancelled
            break
        try:
            _check_deadline(deadline, "failure sweep case")
            failed_twin = apply_failure(
                baseline_twin,
                device_ids=case_plan.failed_device_ids,
                link_ids=case_plan.failed_link_ids,
            )
            state = evaluate(
                failed_twin,
                resolved,
                _deadline=deadline,
                _router_cache=router_cache,
            )
        except SimulationRuntimeExceeded:
            stop_reason = FailureSweepStopReason.runtime_limit
            break
        cases.append(
            FailureCase(
                rank=1,
                plan=case_plan,
                state=state,
                impact=_impact(baseline_state, state),
            )
        )

    ranked = sorted(
        cases,
        key=lambda case: (
            -case.impact.impact_score,
            -case.impact.newly_unserved_count,
            case.plan.case_id,
        ),
    )
    evaluated = tuple(
        case.model_copy(update={"rank": index + 1})
        for index, case in enumerate(ranked)
    )
    warnings = tuple(
        dict.fromkeys(
            [
                *plan.warnings,
                *baseline_state.warnings,
                *(warning for case in evaluated for warning in case.state.warnings),
            ]
        )
    )
    return FailureSweepResult(
        baseline=twin_reference(baseline_twin),
        assumptions=resolved,
        depth=plan.depth,
        max_pairs=plan.max_pairs,
        total_cases=plan.total_cases,
        start=start,
        limit=limit,
        evaluated_cases=len(evaluated),
        stop_reason=stop_reason,
        cases=evaluated,
        warnings=warnings,
    )


def _ids(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "none"


def failure_sweep_rows(result: FailureSweepResult) -> list[dict[str, object]]:
    """Return presentation-neutral rows ordered by impact rank."""
    rows: list[dict[str, object]] = []
    for case in result.cases:
        rows.append(
            {
                "Rank": case.rank,
                "Case": case.plan.case_id,
                "Targeted links": _ids(case.plan.target_link_ids),
                "Targeted devices": _ids(case.plan.target_device_ids),
                "Failed links": _ids(case.plan.failed_link_ids),
                "Failed devices": _ids(case.plan.failed_device_ids),
                "Shared-risk groups": _ids(case.plan.shared_risk_group_ids),
                "Served demands": case.state.served_demand_count,
                "Served demand loss": case.impact.served_demand_delta,
                "Served Mbps": round(case.state.served_demand_mbps, 2),
                "Served Mbps loss": round(case.impact.served_mbps_delta, 2),
                "Max utilization (%)": round(case.state.max_utilization_percent, 2),
                "Utilization increase (pp)": round(
                    case.impact.max_utilization_delta, 2
                ),
                "Newly unserved": case.impact.newly_unserved_count,
                "Impact score": round(case.impact.impact_score, 2),
            }
        )
    return rows


def failure_sweep_to_json(
    result: FailureSweepResult,
    *,
    indent: int | None = None,
) -> str:
    """Serialize a sweep deterministically; no elapsed time is recorded."""
    return json.dumps(
        result.model_dump(mode="json"),
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
    )


def failure_sweep_to_csv(result: FailureSweepResult) -> str:
    """Serialize impact-ranked sweep rows to spreadsheet-safe CSV."""
    rows = failure_sweep_rows(result)
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(rows[0]))
    for row in rows:
        writer.writerow([neutralize_cell(value) for value in row.values()])
    return buffer.getvalue()


__all__ = [
    "FailureCase",
    "FailureCasePlan",
    "FailureImpact",
    "FailureSweepDepth",
    "FailureSweepPlan",
    "FailureSweepResult",
    "FailureSweepStopReason",
    "failure_sweep_rows",
    "failure_sweep_to_csv",
    "failure_sweep_to_json",
    "plan_failure_sweep",
    "run_failure_sweep",
]
