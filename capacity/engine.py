"""Bounded capacity evaluation on scenario copies of one digital twin.

The evaluator from :mod:`simulation` is reused unchanged. Only demand bandwidths
on copied twins are changed; topology, state, and the baseline twin are never
mutated. A run is limited by evaluation count, projected steps, and wall-clock
time, and every run records why it stopped.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from config.limits import (
    MAX_CAPACITY_EVALUATIONS,
    MAX_CAPACITY_HORIZON_STEPS,
    MAX_CAPACITY_RUNTIME_SECONDS,
)
from core.exceptions import (
    CapacityLimitError,
    CapacityValidationError,
    SimulationRuntimeExceeded,
)
from core.schemas.routing import TrafficDemand
from digital_twin.models import DigitalTwin
from forecasting.models import ForecastRun
from optimization.models import CostModel
from simulation.evaluator import evaluate, twin_fingerprint
from simulation.models import (
    CongestionLevel,
    LinkLoad,
    NetworkState,
    SimulationAssumptions,
)

from .demand import project_demands
from .models import (
    CAPACITY_METHOD_NOTE,
    Bottleneck,
    CapacityBounds,
    CapacityFinding,
    CapacityFindingCode,
    CapacityGap,
    CapacityRun,
    CapacityStopReason,
    Crossing,
    DemandMapping,
    DemandProjection,
    StepState,
    UpgradeRecommendation,
)

_LEVEL_RANK: dict[CongestionLevel, int] = {
    CongestionLevel.normal: 0,
    CongestionLevel.warning: 1,
    CongestionLevel.critical: 2,
    CongestionLevel.overloaded: 3,
}


def _resolve_limits(
    max_evaluations: int | None,
    max_runtime_seconds: float | None,
) -> tuple[int, float]:
    evaluations = (
        MAX_CAPACITY_EVALUATIONS if max_evaluations is None else int(max_evaluations)
    )
    runtime = (
        MAX_CAPACITY_RUNTIME_SECONDS
        if max_runtime_seconds is None
        else float(max_runtime_seconds)
    )
    if evaluations < 1 or evaluations > MAX_CAPACITY_EVALUATIONS:
        raise CapacityLimitError(
            f"Requested {evaluations} capacity evaluations; the allowed range is "
            f"1..{MAX_CAPACITY_EVALUATIONS}."
        )
    if runtime <= 0 or runtime > MAX_CAPACITY_RUNTIME_SECONDS:
        raise CapacityLimitError(
            f"Requested a {runtime:g}s capacity budget; the allowed range is "
            f"(0, {MAX_CAPACITY_RUNTIME_SECONDS:g}]."
        )
    return evaluations, runtime


def _scenario_twin(
    twin: DigitalTwin,
    projection: DemandProjection,
    step: int,
) -> DigitalTwin:
    """Return a copy with only the mapped demand bandwidths replaced."""
    projected = {demand.name: demand.point_for(step) for demand in projection.demands}
    demands: list[TrafficDemand] = []
    for demand in twin.demands:
        point = projected.get(demand.name)
        if point is None:
            demands.append(demand)
            continue
        demands.append(
            demand.model_copy(update={"bandwidth_mbps": point.bandwidth_mbps})
        )
    return twin.model_copy(update={"demands": tuple(demands)})


def _crossings(states: Sequence[StepState]) -> tuple[Crossing, ...]:
    seen: set[tuple[str, CongestionLevel]] = set()
    crossings: list[Crossing] = []
    bands = (
        CongestionLevel.warning,
        CongestionLevel.critical,
        CongestionLevel.overloaded,
    )
    for state in states:
        for load in state.state.links:
            reached = _LEVEL_RANK[load.level]
            for level in bands:
                if _LEVEL_RANK[level] > reached or (load.link_id, level) in seen:
                    continue
                seen.add((load.link_id, level))
                crossings.append(
                    Crossing(
                        link_id=load.link_id,
                        level=level,
                        step=state.step,
                        timestamp=state.timestamp,
                        utilization_percent=float(load.utilization_percent),
                    )
                )
    return tuple(
        sorted(
            crossings,
            key=lambda item: (
                -_LEVEL_RANK[item.level],
                item.step,
                item.link_id,
            ),
        )
    )


def _bottlenecks(
    baseline: NetworkState,
    states: Sequence[StepState],
    crossings: tuple[Crossing, ...],
) -> tuple[Bottleneck, ...]:
    baseline_links = {load.link_id: load for load in baseline.links}
    ordered_ids: list[str] = list(baseline_links)
    for state in states:
        for load in state.state.links:
            if load.link_id not in ordered_ids:
                ordered_ids.append(load.link_id)

    by_link_crossings: dict[str, list[Crossing]] = {}
    for crossing in crossings:
        by_link_crossings.setdefault(crossing.link_id, []).append(crossing)

    results: list[Bottleneck] = []
    for link_id in ordered_ids:
        usable: list[tuple[int, LinkLoad]] = []
        if link_id in baseline_links:
            usable.append((0, baseline_links[link_id]))
        usable.extend(
            (state.step, load)
            for state in states
            for load in state.state.links
            if load.link_id == link_id
        )
        if not usable:
            continue
        peak_step, peak_load = max(
            usable,
            key=lambda pair: (float(pair[1].utilization_percent), -pair[0]),
        )
        _, horizon_load = usable[-1]
        capacity = float(peak_load.capacity_mbps)
        results.append(
            Bottleneck(
                link_id=link_id,
                endpoints=tuple(horizon_load.endpoints),
                capacity_mbps=capacity,
                peak_utilization_percent=float(peak_load.utilization_percent),
                peak_step=peak_step,
                horizon_end_load_mbps=float(horizon_load.load_mbps),
                headroom_mbps=capacity - float(horizon_load.load_mbps),
                crossings=tuple(by_link_crossings.get(link_id, ())),
            )
        )
    return tuple(
        sorted(
            results,
            key=lambda item: (
                -item.peak_utilization_percent,
                item.headroom_mbps,
                item.link_id,
            ),
        )
    )


def _recommend(
    bottlenecks: Sequence[Bottleneck],
    *,
    assumptions: SimulationAssumptions,
    cost_model: CostModel,
) -> tuple[tuple[UpgradeRecommendation, ...], tuple[CapacityGap, ...]]:
    warning = float(assumptions.thresholds.warning_percent)
    tiers = sorted(cost_model.tiers, key=lambda tier: tier.capacity_mbps)
    largest = tiers[-1].capacity_mbps
    recommendations: list[UpgradeRecommendation] = []
    gaps: list[CapacityGap] = []
    for bottleneck in bottlenecks:
        if bottleneck.peak_utilization_percent < warning:
            continue
        load = bottleneck.horizon_end_load_mbps
        if load <= 0:
            continue
        required = load * 100.0 / warning
        candidates = [
            tier
            for tier in tiers
            if tier.capacity_mbps > bottleneck.capacity_mbps
            and tier.capacity_mbps > required
        ]
        endpoints = tuple(bottleneck.endpoints)
        if not candidates:
            gaps.append(
                CapacityGap(
                    link_id=bottleneck.link_id,
                    endpoints=endpoints,
                    horizon_end_load_mbps=load,
                    required_capacity_mbps=required,
                    largest_available_capacity_mbps=largest,
                    note=(
                        "No configured capacity tier keeps the horizon-end "
                        "modeled utilization strictly below the warning "
                        "threshold; escalate to the Optimization Center."
                    ),
                )
            )
            continue
        tier = candidates[0]
        current = cost_model.tier_for_capacity(bottleneck.capacity_mbps)
        delta = (
            max(0.0, tier.link_cost_proxy - current.link_cost_proxy)
            if current is not None
            else tier.link_cost_proxy
        )
        recommendations.append(
            UpgradeRecommendation(
                link_id=bottleneck.link_id,
                endpoints=endpoints,
                current_capacity_mbps=bottleneck.capacity_mbps,
                target_tier_name=tier.name,
                target_capacity_mbps=tier.capacity_mbps,
                horizon_end_load_mbps=load,
                projected_utilization_percent=load / tier.capacity_mbps * 100.0,
                warning_threshold_percent=warning,
                cost_delta=float(delta),
                cost_unit=cost_model.unit,
            )
        )
    return tuple(recommendations), tuple(gaps)


def evaluate_capacity(
    twin: DigitalTwin,
    forecast_run: ForecastRun,
    mapping: DemandMapping,
    *,
    assumptions: SimulationAssumptions | None = None,
    cost_model: CostModel | None = None,
    max_evaluations: int | None = None,
    max_runtime_seconds: float | None = None,
) -> CapacityRun:
    """Evaluate bounded projected demand scenarios on copies of ``twin``.

    ``max_evaluations`` and ``max_runtime_seconds`` may only lower the
    configured limits. The baseline is always evaluated first and counts toward
    the evaluation budget.
    """
    evaluations, runtime = _resolve_limits(max_evaluations, max_runtime_seconds)
    resolved_assumptions = (
        SimulationAssumptions() if assumptions is None else assumptions
    )
    if not isinstance(resolved_assumptions, SimulationAssumptions):
        raise CapacityValidationError(
            "assumptions must be a SimulationAssumptions instance."
        )
    cost = CostModel() if cost_model is None else cost_model
    if not isinstance(cost, CostModel):
        raise CapacityValidationError("cost_model must be a CostModel instance.")

    started = time.perf_counter()
    deadline = started + runtime
    try:
        projection = project_demands(twin, forecast_run, mapping)
    except ValueError as exc:
        raise CapacityValidationError(f"Invalid demand mapping: {exc}") from exc

    requested_steps = projection.horizon
    effective_steps = min(
        requested_steps,
        MAX_CAPACITY_HORIZON_STEPS,
        evaluations - 1,
    )
    if effective_steps < requested_steps:
        projection = projection.model_copy(
            update={
                "findings": (
                    *projection.findings,
                    CapacityFinding(
                        code=CapacityFindingCode.horizon_clipped,
                        message=(
                            f"Requested horizon {requested_steps} was clipped to "
                            f"{effective_steps} modeled steps by configured bounds."
                        ),
                    ),
                )
            }
        )

    try:
        baseline = evaluate(twin, resolved_assumptions, _deadline=deadline)
    except SimulationRuntimeExceeded as exc:
        raise CapacityLimitError(
            "Capacity evaluation exceeded its runtime budget before the "
            "baseline could be evaluated."
        ) from exc
    used = 1

    states: list[StepState] = []
    stop_reason = CapacityStopReason.completed
    if effective_steps == 0 or not projection.demands:
        stop_reason = CapacityStopReason.no_projection
    else:
        for step in range(1, effective_steps + 1):
            if used >= evaluations:
                stop_reason = CapacityStopReason.evaluation_limit
                break
            if time.perf_counter() >= deadline:
                stop_reason = CapacityStopReason.runtime_limit
                break
            if step > len(projection.step_timestamps):
                stop_reason = CapacityStopReason.incomplete_projection
                break
            try:
                state = evaluate(
                    _scenario_twin(twin, projection, step),
                    resolved_assumptions,
                    _deadline=deadline,
                )
            except SimulationRuntimeExceeded:
                stop_reason = CapacityStopReason.runtime_limit
                break
            used += 1
            timestamp = projection.step_timestamps[step - 1]
            states.append(StepState(step=step, timestamp=timestamp, state=state))

    crossings = _crossings(states)
    bottlenecks = _bottlenecks(baseline, states, crossings)
    recommendations, gaps = _recommend(
        bottlenecks,
        assumptions=resolved_assumptions,
        cost_model=cost,
    )
    assumptions_note = (
        *projection.assumptions,
        CAPACITY_METHOD_NOTE,
        (
            f"Congestion thresholds: warning {resolved_assumptions.thresholds.warning_percent:g}%, "
            f"critical {resolved_assumptions.thresholds.critical_percent:g}%, "
            f"overload {resolved_assumptions.thresholds.overload_percent:g}%."
        ),
        cost.note,
    )
    return CapacityRun(
        twin_fingerprint=twin_fingerprint(twin),
        projection=projection,
        baseline=baseline,
        steps=tuple(states),
        crossings=crossings,
        bottlenecks=bottlenecks,
        recommendations=recommendations,
        gaps=gaps,
        bounds=CapacityBounds(
            max_evaluations=evaluations,
            max_horizon_steps=MAX_CAPACITY_HORIZON_STEPS,
            max_runtime_seconds=runtime,
            used_evaluations=used,
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            stop_reason=stop_reason,
        ),
        assumptions=tuple(assumptions_note),
    )


__all__ = ["evaluate_capacity"]
