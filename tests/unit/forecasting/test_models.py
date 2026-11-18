"""Hand-computed statistical model tests."""

from __future__ import annotations

import numpy as np
import pytest

from core.exceptions import ForecastValidationError
from forecasting import (
    ForecastModelKind,
    allowed_horizon,
    error_metrics,
    fit_holt,
    forecast_series,
    holt_forecast,
    linear_trend_fit,
    linear_trend_forecast,
    moving_average_forecast,
    naive_forecast,
    seasonal_naive_forecast,
)
from tests.unit.forecasting.helpers import make_series

VALUES = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0]  # y = 10 + 2t


def test_linear_trend_recovers_slope_intercept_and_exact_forecast() -> None:
    # For y = 10 + 2t, tbar = 3.5, ybar = 17, so b = 2 and a = 10.
    intercept, slope = linear_trend_fit(np.array(VALUES))
    assert intercept == pytest.approx(10.0)
    assert slope == pytest.approx(2.0)

    # With eight observed points, future indices are 8, 9, 10 -> 26, 28, 30.
    np.testing.assert_allclose(
        linear_trend_forecast(np.array(VALUES), 3),
        np.array([26.0, 28.0, 30.0]),
    )

    result = forecast_series(make_series(VALUES), horizon=3)
    assert result.model is ForecastModelKind.linear_trend
    assert [point.value for point in result.forecast_points] == pytest.approx([26.0, 28.0, 30.0])
    assert result.beats_naive


def test_naive_and_moving_average_hand_outputs() -> None:
    values = np.array([1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 7.0, 8.0])
    # Naive repeats the last value: 8.
    np.testing.assert_array_equal(naive_forecast(values, 2), np.array([8.0, 8.0]))
    # Moving average over 6, 7, 8: (6 + 7 + 8) / 3 = 7.
    np.testing.assert_array_equal(
        moving_average_forecast(values, 2, window=3),
        np.array([7.0, 7.0]),
    )
    with pytest.raises(ForecastValidationError):
        moving_average_forecast(values[:2], 1, window=3)


def test_holt_hand_computed_recursion() -> None:
    # alpha = beta = 0.5 on [2, 4, 6, 8]:
    # L0=2, T0=2. After 4: L=4, T=2. After 6: L=6, T=2. After 8: L=8, T=2.
    # Forecasts: 8 + 1*2 = 10, 8 + 2*2 = 12.
    values = np.array([2.0, 4.0, 6.0, 8.0])
    np.testing.assert_allclose(holt_forecast(values, 2, 0.5, 0.5), [10.0, 12.0])
    alpha, beta, sse = fit_holt(values)
    assert 0.05 <= alpha <= 0.95
    assert 0.05 <= beta <= 0.95
    assert sse >= 0.0


def test_sMAPE_zero_handling() -> None:
    # sMAPE = 100 * |actual-pred| / ((|actual|+|pred|)/2), 0 when both are 0.
    # Terms: 0 vs 0 -> 0; 10 vs 5 -> 100*5/7.5 = 66.666...; 0 vs 10 -> 200.
    metrics = error_metrics(
        np.array([0.0, 10.0, 0.0]),
        np.array([0.0, 5.0, 10.0]),
    )
    assert metrics.smape == pytest.approx((0.0 + 66.66666666666667 + 200.0) / 3.0)
    assert metrics.mae == pytest.approx(5.0)
    zeros = error_metrics(np.array([0.0, 10.0, 0.0]), np.zeros(3))
    assert zeros.smape == pytest.approx(200.0 / 3.0)


def test_seasonal_series_where_seasonal_naive_wins() -> None:
    # Two-point season [1, 5] repeated; with period 2 the held-out [1, 5] is
    # reproduced exactly, while naive/moving-average/linear all miss.
    values = [1.0, 5.0] * 4
    np.testing.assert_array_equal(
        seasonal_naive_forecast(np.array(values), 2, 2),
        np.array([1.0, 5.0]),
    )
    result = forecast_series(make_series(values), horizon=2, seasonal_period=2)

    assert result.model is ForecastModelKind.seasonal_naive
    assert [point.value for point in result.forecast_points] == pytest.approx([1.0, 5.0])
    assert "Selected seasonal_naive" in result.selection_note


def test_pure_noise_prefers_naive_and_says_so() -> None:
    # Constant history gives every rule zero or positive held-out error; naive
    # is retained when nothing improves on it strictly.
    result = forecast_series(make_series([5.0] * 8), horizon=2)
    assert result.model is ForecastModelKind.naive
    assert not result.beats_naive
    assert "Naive baseline retained" in result.selection_note


def test_chronological_split_never_uses_held_out_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forecasting.forecast as forecast_module

    calls: list[tuple[np.ndarray, np.ndarray]] = []
    original = forecast_module._split

    def recording_split(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        train, test = original(values)
        calls.append((train.copy(), test.copy()))
        return train, test

    monkeypatch.setattr(forecast_module, "_split", recording_split)
    result = forecast_series(make_series(VALUES), horizon=2)

    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][0], np.array(VALUES[:6]))
    np.testing.assert_array_equal(calls[0][1], np.array(VALUES[6:]))
    # Naive's held-out prediction is the last training value, 20: errors 2 and 4.
    assert result.naive_evaluation.metrics.mae == pytest.approx(3.0)


def test_horizon_limit_refusal() -> None:
    # Eight observations and the documented 0.5 ratio permit four steps.
    assert allowed_horizon(make_series(VALUES)) == 4
    with pytest.raises(Exception, match="limit is 4"):
        forecast_series(make_series(VALUES), horizon=5)


def test_fill_report_and_synthetic_label_travel_into_result() -> None:
    from forecasting import DataProvenance, GapPolicy

    series = make_series(
        VALUES,
        provenance=DataProvenance.synthetic,
    ).model_copy(
        update={
            "fill_report": parsing_fill_report(),
        }
    )
    result = forecast_series(series, horizon=2)

    assert result.data_label == "SYNTHETIC"
    assert result.provenance is DataProvenance.synthetic
    assert result.fill_report.policy is GapPolicy.linear_interpolate
    assert result.fill_report.filled_points == 2
    assert any("2 missing value" in warning for warning in result.warnings)
    assert any("SYNTHETIC" in text for text in result.assumptions)


def parsing_fill_report() -> object:
    from forecasting import FillReport, GapPolicy

    return FillReport(
        policy=GapPolicy.linear_interpolate,
        filled_points=2,
        unfilled_points=0,
        details=("row 3", "row 4"),
    )
