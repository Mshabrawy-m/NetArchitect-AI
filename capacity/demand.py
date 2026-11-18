"""Mapping forecast series onto demands already present in the digital twin.

This module never invents a demand, a source, a destination, or a historical
measurement. It only replaces the bandwidth assumption of an existing demand
with a modeled projection and records every mapping decision as a finding.
"""

from __future__ import annotations

from digital_twin.models import DigitalTwin
from forecasting.models import (
    APPROX_INTERVAL_NOTE,
    MODEL_NOTE,
    ForecastResult,
    ForecastRun,
    SeriesUnit,
)

from .models import (
    CapacityFinding,
    CapacityFindingCode,
    DemandMapping,
    DemandProjection,
    ProjectedDemand,
    ProjectedDemandPoint,
)


def project_demands(
    twin: DigitalTwin,
    forecast_run: ForecastRun,
    mapping: DemandMapping,
) -> DemandProjection:
    """Project mapped twin demands from the supplied forecast run.

    Series without a mapping, mappings to demands absent from the twin, and
    user-count series without ``per_user_mbps`` are reported as findings and
    skipped. The twin itself is not changed.
    """
    findings: list[CapacityFinding] = []
    known_demands = {demand.name: demand for demand in twin.demands}
    results = {result.series_id: result for result in forecast_run.results}
    horizon = forecast_run.horizon

    for series_id in sorted(set(results) - set(mapping.series_to_demand)):
        findings.append(
            CapacityFinding(
                code=CapacityFindingCode.unmapped_series,
                message=(
                    f"Forecast series {series_id!r} has no demand mapping; it is "
                    "not applied to the twin."
                ),
                series_id=series_id,
            )
        )

    demands: list[ProjectedDemand] = []
    uses_users = False
    for series_id, demand_name in sorted(mapping.series_to_demand.items()):
        result: ForecastResult | None = results.get(series_id)
        if result is None:
            findings.append(
                CapacityFinding(
                    code=CapacityFindingCode.unmapped_series,
                    message=(
                        f"Mapped series {series_id!r} is absent from the forecast "
                        "run; the demand keeps its stated bandwidth."
                    ),
                    series_id=series_id,
                    demand_name=demand_name,
                )
            )
            continue
        if demand_name not in known_demands:
            findings.append(
                CapacityFinding(
                    code=CapacityFindingCode.unknown_demand,
                    message=(
                        f"Mapped demand {demand_name!r} does not exist in the "
                        "current twin; no projection was applied."
                    ),
                    series_id=series_id,
                    demand_name=demand_name,
                )
            )
            continue
        if result.unit is SeriesUnit.users and mapping.per_user_mbps is None:
            findings.append(
                CapacityFinding(
                    code=CapacityFindingCode.missing_per_user_assumption,
                    message=(
                        f"Series {series_id!r} is measured in users but no "
                        "per_user_mbps assumption was supplied; the demand keeps "
                        "its stated bandwidth."
                    ),
                    series_id=series_id,
                    demand_name=demand_name,
                )
            )
            continue
        if result.unit is SeriesUnit.users:
            uses_users = True

        if len(result.forecast_points) < horizon:
            findings.append(
                CapacityFinding(
                    code=CapacityFindingCode.short_forecast,
                    message=(
                        f"Series {series_id!r} supplied "
                        f"{len(result.forecast_points)} of {horizon} requested "
                        "steps; later steps keep the stated demand bandwidth."
                    ),
                    series_id=series_id,
                    demand_name=demand_name,
                )
            )

        points = tuple(
            ProjectedDemandPoint(
                step=point.step,
                timestamp=point.timestamp,
                series_id=series_id,
                unit=result.unit,
                projected_value=float(point.value),
                bandwidth_mbps=(
                    float(point.value) * float(mapping.per_user_mbps)
                    if result.unit is SeriesUnit.users
                    else float(point.value)
                ),
                data_label=result.data_label,
            )
            for point in result.forecast_points
            if point.step <= horizon
        )
        demands.append(
            ProjectedDemand(
                name=demand_name,
                series_id=series_id,
                provenance=result.provenance,
                data_label=result.data_label,
                unit=result.unit,
                points=points,
            )
        )

    assumptions: list[str] = [
        MODEL_NOTE,
        APPROX_INTERVAL_NOTE,
        "Capacity evaluation uses point forecasts only; interval bounds are not applied to demand.",
    ]
    if uses_users and mapping.per_user_mbps is not None:
        assumptions.append(
            f"User-count forecasts are converted at {mapping.per_user_mbps:g} "
            "Mbps per user, supplied by the user."
        )
    elif mapping.per_user_mbps is not None:
        findings.append(
            CapacityFinding(
                code=CapacityFindingCode.unused_per_user_assumption,
                message=(
                    "per_user_mbps was supplied but no mapped user-count series "
                    "used it."
                ),
            )
        )
    if not demands:
        findings.append(
            CapacityFinding(
                code=CapacityFindingCode.no_mapped_demand,
                message=(
                    "No forecast series was mapped to an existing twin demand; "
                    "only the baseline state was evaluated."
                ),
            )
        )

    first_result = forecast_run.results[0] if forecast_run.results else None
    step_timestamps = (
        tuple(point.timestamp for point in first_result.forecast_points[:horizon])
        if first_result is not None
        else ()
    )
    return DemandProjection(
        horizon=horizon,
        per_user_mbps=mapping.per_user_mbps,
        step_timestamps=step_timestamps,
        demands=tuple(demands),
        findings=tuple(findings),
        assumptions=tuple(assumptions),
    )


__all__ = ["project_demands"]
