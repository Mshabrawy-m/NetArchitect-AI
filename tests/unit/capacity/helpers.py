"""Builders for capacity-planning unit tests."""

from __future__ import annotations

from forecasting import (
    DataProvenance,
    ForecastRun,
    GapPolicy,
    SeriesUnit,
    forecast_series,
)
from tests.unit.forecasting.helpers import make_series
from tests.unit.simulation.helpers import line_twin


def forecast_run(
    values: list[float],
    horizon: int,
    *,
    series_id: str = "s1",
    unit: SeriesUnit = SeriesUnit.users,
    provenance: DataProvenance = DataProvenance.user_supplied,
) -> ForecastRun:
    """Build a real forecast run from a simple series."""
    series = make_series(values, series_id=series_id, unit=unit, provenance=provenance)
    result = forecast_series(series, horizon=horizon)
    return ForecastRun(
        results=(result,),
        horizon=horizon,
        gap_policy=GapPolicy.reject,
    )


def constant_run(
    value: float,
    horizon: int = 2,
    *,
    series_id: str = "s1",
    unit: SeriesUnit = SeriesUnit.users,
    provenance: DataProvenance = DataProvenance.user_supplied,
) -> ForecastRun:
    """Build a constant-history forecast run with ten observations."""
    return forecast_run(
        [value] * 10,
        horizon,
        series_id=series_id,
        unit=unit,
        provenance=provenance,
    )


def line_capacity_twin(*, bandwidth: float = 10.0, capacity: float = 20.0):
    """A three-device line with one demand spanning both links."""
    from tests.unit.simulation.helpers import make_demand

    return line_twin(
        demands=(make_demand("call", "a", "c", bandwidth),),
        capacity_mbps=capacity,
    )
