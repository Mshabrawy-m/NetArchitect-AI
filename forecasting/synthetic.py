"""Deterministic, always-labelled SYNTHETIC time-series generator.

The generator creates illustration data only. It never reads a network, a
measurement archive, or a monitoring system. Every generated series stores
``provenance=synthetic`` and the uppercase ``SYNTHETIC`` label.

Documented formula, for step ``i`` starting at zero::

    raw_i = base * (1 + growth_rate) ** i
            + seasonality * sin(2 * pi * i / period)
            + noise * N_i

``N_i`` is a standard-normal draw from NumPy's PCG64 generator seeded with the
caller's seed. The result is clamped at zero (negative traffic is not a valid
value) and rounded to six decimal places so exports and tests are stable.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.limits import MAX_FORECAST_POINTS, MIN_FORECAST_POINTS

from .models import (
    SYNTHETIC_LABEL,
    DataProvenance,
    Observation,
    SeriesUnit,
    TimeSeries,
)

DEFAULT_START = datetime(2026, 1, 1)


class SyntheticSpec(BaseModel):
    """All user-editable parameters of one synthetic series."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_id: str = Field(min_length=1)
    unit: SeriesUnit = SeriesUnit.users
    base: float = Field(ge=0, description="Starting value in the series unit.")
    growth_rate: float = Field(
        default=0.0,
        description="Per-step proportional growth; 0.02 means two percent per step.",
    )
    seasonality: float = Field(
        default=0.0,
        ge=0,
        description="Amplitude of the additive sine wave in the series unit.",
    )
    period: int = Field(default=4, ge=2, description="Sine period in steps.")
    noise: float = Field(
        default=0.0,
        ge=0,
        description="Standard deviation of additive normal noise in the series unit.",
    )
    seed: int = Field(default=0, ge=0, description="Seed for NumPy PCG64.")
    points: int = Field(
        default=MIN_FORECAST_POINTS,
        ge=MIN_FORECAST_POINTS,
        le=MAX_FORECAST_POINTS,
    )
    start: datetime = DEFAULT_START

    @model_validator(mode="after")
    def _finite(self) -> SyntheticSpec:
        if not all(
            math.isfinite(value)
            for value in (self.base, self.growth_rate, self.seasonality, self.noise)
        ):
            raise ValueError("Synthetic parameters must be finite numbers.")
        if self.growth_rate <= -1:
            raise ValueError("growth_rate must be greater than -1.")
        return self

    def assumptions(self) -> tuple[str, ...]:
        """Return the stated assumptions carried into results and reports."""
        description = (
            f"SYNTHETIC data: base={self.base:g}, growth_rate={self.growth_rate:g} "
            f"per step, seasonality amplitude={self.seasonality:g} with period "
            f"{self.period}, noise sigma={self.noise:g}, seed={self.seed}."
        )
        return (
            description,
            "Synthetic observations are illustration inputs, not measurements.",
        )


def generate_synthetic(spec: SyntheticSpec) -> TimeSeries:
    """Generate one deterministic SYNTHETIC series from ``spec``."""
    rng = np.random.default_rng(spec.seed)
    steps = np.arange(spec.points, dtype=float)
    trend = spec.base * (1.0 + spec.growth_rate) ** steps
    seasonal = spec.seasonality * np.sin(2.0 * np.pi * steps / spec.period)
    noise = spec.noise * rng.standard_normal(spec.points)
    values = np.maximum(0.0, trend + seasonal + noise)
    observations = tuple(
        Observation(
            timestamp=spec.start + timedelta(days=int(step)),
            value=round(float(value), 6),
        )
        for step, value in zip(steps, values)
    )
    return TimeSeries(
        series_id=spec.series_id,
        unit=spec.unit,
        provenance=DataProvenance.synthetic,
        observations=observations,
    )


__all__ = ["DEFAULT_START", "SYNTHETIC_LABEL", "SyntheticSpec", "generate_synthetic"]
