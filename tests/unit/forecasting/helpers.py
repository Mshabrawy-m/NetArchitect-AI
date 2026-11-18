"""Helpers for forecasting tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from forecasting import DataProvenance, Observation, SeriesUnit, TimeSeries

START = datetime(2026, 1, 1)


def make_series(
    values: list[float] | np.ndarray,
    *,
    series_id: str = "s1",
    unit: SeriesUnit = SeriesUnit.users,
    provenance: DataProvenance = DataProvenance.user_supplied,
    start: datetime = START,
    step_days: int = 1,
) -> TimeSeries:
    return TimeSeries(
        series_id=series_id,
        unit=unit,
        provenance=provenance,
        observations=tuple(
            Observation(timestamp=start + timedelta(days=step_days * index), value=float(value))
            for index, value in enumerate(values)
        ),
    )


def csv_text(
    rows: list[tuple[str, str, str, str]],
    *,
    header: str = "timestamp,series_id,value,unit",
) -> str:
    lines = [header]
    lines.extend(",".join(row) for row in rows)
    return "\n".join(lines) + "\n"


def rows_for(
    values: list[str],
    *,
    series_id: str = "s1",
    unit: str = "users",
    start: datetime = START,
) -> list[tuple[str, str, str, str]]:
    return [
        (
            (start + timedelta(days=index)).isoformat(),
            series_id,
            value,
            unit,
        )
        for index, value in enumerate(values)
    ]
