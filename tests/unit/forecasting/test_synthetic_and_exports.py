"""Synthetic generator labelling, determinism, and export coverage."""

from __future__ import annotations

import json

from forecasting import (
    DataProvenance,
    ForecastRun,
    GapPolicy,
    SyntheticSpec,
    forecast_csv,
    forecast_json,
    forecast_series,
    generate_synthetic,
    series_csv,
)


def test_generator_is_deterministic_for_the_same_seed() -> None:
    spec = SyntheticSpec(
        series_id="synthetic-users",
        base=100.0,
        growth_rate=0.02,
        seasonality=5.0,
        period=4,
        noise=1.0,
        seed=7,
        points=12,
    )
    first = generate_synthetic(spec)
    second = generate_synthetic(spec)
    changed = generate_synthetic(spec.model_copy(update={"seed": 8}))

    assert first == second
    assert first != changed
    assert first.provenance is DataProvenance.synthetic
    assert first.label == "SYNTHETIC"
    # No fabrication: generated values are derived only from the stated formula.
    assert first.observations[0].value >= 0


def test_synthetic_label_is_present_in_results_and_exports() -> None:
    spec = SyntheticSpec(
        series_id="synthetic-load",
        unit="Mbps",  # type: ignore[arg-type]
        base=50.0,
        growth_rate=0.05,
        noise=0.5,
        seed=3,
        points=10,
    )
    series = generate_synthetic(spec)
    result = forecast_series(series, horizon=3, assumptions=spec.assumptions())
    run = ForecastRun(results=(result,), horizon=3, gap_policy=GapPolicy.reject)

    assert result.data_label == "SYNTHETIC"
    assert result.provenance.value == "synthetic"
    assert "SYNTHETIC" in forecast_csv(run).decode()
    assert "SYNTHETIC" in forecast_json(run).decode()
    assert "SYNTHETIC" in series_csv((series,)).decode()
    payload = json.loads(forecast_json(run))
    assert payload["results"][0]["provenance"] == "synthetic"
    assert payload["results"][0]["data_label"] == "SYNTHETIC"
    assert payload["results"][0]["assumptions"]


def test_exports_are_deterministic() -> None:
    spec = SyntheticSpec(series_id="stable", base=10.0, seed=1, points=8)
    result = forecast_series(generate_synthetic(spec), horizon=2)
    run = ForecastRun(results=(result,), horizon=2, gap_policy=GapPolicy.reject)

    assert forecast_json(run) == forecast_json(run)
    assert forecast_csv(run) == forecast_csv(run)
