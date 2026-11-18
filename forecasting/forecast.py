"""Deterministic statistical forecasts and chronological model selection.

No machine learning is used. Every rule is an explicit formula implemented with
NumPy, and every result is a modeled projection from stated assumptions.

Model formulas (``y_0..y_{n-1}`` are the training values):

* naive: ``y_hat_{n-1+h} = y_{n-1}``.
* moving average: mean of the last ``window`` training values.
* linear trend: ordinary least squares ``y = a + b*t`` with
  ``b = sum((t-tbar)*(y-ybar)) / sum((t-tbar)**2)`` and ``a = ybar - b*tbar``;
  future points use ``t = n, n+1, ...``.
* Holt linear exponential smoothing (additive): initialize ``L_0 = y_0`` and
  ``T_0 = y_1 - y_0``; for each observed point
  ``L_t = alpha*y_t + (1-alpha)*(L_{t-1}+T_{t-1})`` and
  ``T_t = beta*(L_t-L_{t-1}) + (1-beta)*T_{t-1}``. Future points are
  ``L_last + h*T_last``. ``alpha`` and ``beta`` are selected by a deterministic
  grid search over ``{0.05, 0.10, ..., 0.95}`` minimizing one-step training SSE.
* seasonal naive (only with at least two full periods):
  ``y_hat_{n-1+h} = y_{n-period + ((h-1) mod period)}``.

Selection uses one chronological split: the last 20 percent (at least two
points) is held out. Models are fit on the earlier points only, then scored on
the held-out points. There is no shuffling. MAE is the primary criterion; RMSE
and sMAPE are always reported. sMAPE is
``mean(200*|actual-forecast| / ((|actual|+|forecast|)/2))``; when both values
are zero the term is defined as zero, and when exactly one is zero the term is
200. Equivalently this is ``100*|actual-forecast| / ((|actual|+|forecast|)/2)``.
The naive baseline is always evaluated; a model is preferred only when it has
strictly lower held-out MAE, otherwise naive is returned with an explicit note.

Prediction intervals are approximate: ``forecast +/- 1.96*sigma*sqrt(h)``,
clamped at zero on the lower side, where ``sigma`` is the standard deviation of
the chosen model's held-out residuals. They are not calibrated guarantees.
"""

from __future__ import annotations

import itertools
import math
from datetime import timedelta

import numpy as np

from config.limits import (
    MAX_FORECAST_HORIZON_RATIO,
    MAX_FORECAST_HORIZON_STEPS,
    MIN_FORECAST_POINTS,
)
from core.exceptions import ForecastLimitError, ForecastValidationError

from .models import (
    APPROX_INTERVAL_NOTE,
    INTERVAL_Z,
    MODEL_NOTE,
    DataProvenance,
    EvaluationMetrics,
    ForecastModelKind,
    ForecastPoint,
    ForecastResult,
    HistorySummary,
    ModelEvaluation,
    TimeSeries,
)

GRID_VALUES: tuple[float, ...] = tuple(round(0.05 * step, 2) for step in range(1, 19))
MODEL_ORDER: tuple[ForecastModelKind, ...] = (
    ForecastModelKind.moving_average,
    ForecastModelKind.linear_trend,
    ForecastModelKind.holt,
    ForecastModelKind.seasonal_naive,
)


def _array(series: TimeSeries) -> np.ndarray:
    return np.array([observation.value for observation in series.observations], dtype=float)


def history_summary(series: TimeSeries) -> HistorySummary:
    """Return a descriptive summary and the timestamp step used for forecasts."""
    observations = series.observations
    if not observations:
        return HistorySummary(count=0, unit=series.unit)
    values = _array(series)
    deltas = [
        (later.timestamp - earlier.timestamp).total_seconds()
        for earlier, later in itertools.pairwise(observations)
    ]
    positive = [delta for delta in deltas if delta > 0]
    step_seconds = float(np.median(positive)) if positive else 86_400.0
    irregular = bool(positive and any(delta != positive[0] for delta in positive))
    return HistorySummary(
        count=len(observations),
        first_timestamp=observations[0].timestamp,
        last_timestamp=observations[-1].timestamp,
        min_value=float(np.min(values)),
        max_value=float(np.max(values)),
        mean_value=float(np.mean(values)),
        unit=series.unit,
        step_seconds=step_seconds,
        irregular_spacing=irregular,
    )


def allowed_horizon(series: TimeSeries) -> int:
    """Return the maximum projected steps permitted for this history length."""
    by_ratio = math.floor(len(series.observations) * MAX_FORECAST_HORIZON_RATIO)
    return max(1, min(by_ratio, MAX_FORECAST_HORIZON_STEPS))


def _check_horizon(series: TimeSeries, horizon: int) -> None:
    limit = allowed_horizon(series)
    if horizon < 1:
        raise ForecastValidationError("Forecast horizon must be at least 1 step.")
    if len(series.observations) < MIN_FORECAST_POINTS:
        raise ForecastValidationError(
            f"Series {series.series_id!r} has {len(series.observations)} points; "
            f"the minimum is {MIN_FORECAST_POINTS}."
        )
    if horizon > limit:
        raise ForecastLimitError(
            f"Series {series.series_id!r}: requested {horizon} forecast steps but "
            f"the limit is {limit} (history length {len(series.observations)} x "
            f"{MAX_FORECAST_HORIZON_RATIO:g}, capped at "
            f"{MAX_FORECAST_HORIZON_STEPS}). Shorten the horizon or supply more "
            "history."
        )


def naive_forecast(values: np.ndarray, horizon: int) -> np.ndarray:
    """Repeat the last observed value."""
    if len(values) == 0:
        raise ForecastValidationError("Naive forecast needs at least one value.")
    return np.full(horizon, float(values[-1]), dtype=float)


def moving_average_forecast(
    values: np.ndarray,
    horizon: int,
    window: int = 3,
) -> np.ndarray:
    """Project the mean of the most recent ``window`` values."""
    if window < 1 or window > len(values):
        raise ForecastValidationError(
            f"Moving-average window {window} must be between 1 and {len(values)}."
        )
    return np.full(horizon, float(np.mean(values[-window:])), dtype=float)


def linear_trend_fit(values: np.ndarray) -> tuple[float, float]:
    """Return ``(intercept, slope)`` via ordinary least squares on step index."""
    y = np.asarray(values, dtype=float)
    t = np.arange(len(y), dtype=float)
    t_mean = float(np.mean(t))
    y_mean = float(np.mean(y))
    denominator = float(np.sum((t - t_mean) ** 2))
    if denominator == 0:
        return y_mean, 0.0
    slope = float(np.sum((t - t_mean) * (y - y_mean)) / denominator)
    return float(y_mean - slope * t_mean), slope


def linear_trend_forecast(values: np.ndarray, horizon: int) -> np.ndarray:
    """Project the fitted line at future step indices."""
    intercept, slope = linear_trend_fit(values)
    future = np.arange(len(values), len(values) + horizon, dtype=float)
    return intercept + slope * future


def _holt_one_step(
    values: np.ndarray,
    alpha: float,
    beta: float,
) -> tuple[np.ndarray, float, float]:
    """Return one-step fitted values and final (level, trend)."""
    y = np.asarray(values, dtype=float)
    if len(y) < 2:
        raise ForecastValidationError("Holt smoothing needs at least two values.")
    level = float(y[0])
    trend = float(y[1] - y[0])
    fitted: list[float] = []
    for observed in y[1:]:
        prediction = level + trend
        fitted.append(prediction)
        updated = alpha * float(observed) + (1.0 - alpha) * prediction
        trend = beta * (updated - level) + (1.0 - beta) * trend
        level = updated
    return np.array(fitted, dtype=float), level, trend


def holt_forecast(
    values: np.ndarray,
    horizon: int,
    alpha: float,
    beta: float,
) -> np.ndarray:
    """Project from the final Holt level and trend."""
    _, level, trend = _holt_one_step(values, alpha, beta)
    return np.array([level + step * trend for step in range(1, horizon + 1)])


def fit_holt(values: np.ndarray) -> tuple[float, float, float]:
    """Return ``(alpha, beta, sse)`` from the deterministic grid search."""
    y = np.asarray(values, dtype=float)
    best: tuple[float, float, float] | None = None
    for alpha in GRID_VALUES:
        for beta in GRID_VALUES:
            fitted, _, _ = _holt_one_step(y, alpha, beta)
            sse = float(np.sum((y[1:] - fitted) ** 2))
            if best is None or sse < best[2]:
                best = (alpha, beta, sse)
    assert best is not None
    return best


def seasonal_naive_forecast(
    values: np.ndarray,
    horizon: int,
    period: int,
) -> np.ndarray:
    """Repeat the most recent value from the same season."""
    if period < 2:
        raise ForecastValidationError("Seasonal period must be at least 2.")
    if len(values) < 2 * period:
        raise ForecastValidationError(
            f"Seasonal naive needs at least {2 * period} values, got {len(values)}."
        )
    start = len(values) - period
    return np.array(
        [values[start + ((step - 1) % period)] for step in range(1, horizon + 1)],
        dtype=float,
    )


def error_metrics(actual: np.ndarray, predicted: np.ndarray) -> EvaluationMetrics:
    """Compute MAE, RMSE, and the documented zero-safe sMAPE."""
    if len(actual) != len(predicted):
        raise ForecastValidationError("Metric arrays must have equal length.")
    if len(actual) == 0:
        return EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0, sample_count=0)
    errors = np.abs(actual - predicted)
    denominator = (np.abs(actual) + np.abs(predicted)) / 2.0
    smape_terms = np.where(
        denominator == 0,
        0.0,
        errors / np.where(denominator == 0, 1.0, denominator) * 100.0,
    )
    return EvaluationMetrics(
        mae=float(np.mean(errors)),
        rmse=float(np.sqrt(np.mean(errors**2))),
        smape=float(np.mean(smape_terms)),
        sample_count=len(actual),
    )


def _predictions(
    kind: ForecastModelKind,
    train: np.ndarray,
    horizon: int,
    parameters: dict[str, float | int | str],
) -> np.ndarray:
    if kind is ForecastModelKind.naive:
        return naive_forecast(train, horizon)
    if kind is ForecastModelKind.moving_average:
        return moving_average_forecast(train, horizon, int(parameters["window"]))
    if kind is ForecastModelKind.linear_trend:
        return linear_trend_forecast(train, horizon)
    if kind is ForecastModelKind.holt:
        return holt_forecast(
            train,
            horizon,
            float(parameters["alpha"]),
            float(parameters["beta"]),
        )
    return seasonal_naive_forecast(train, horizon, int(parameters["period"]))


def _parameters(
    values: np.ndarray,
    kind: ForecastModelKind,
    *,
    moving_window: int,
    seasonal_period: int,
) -> dict[str, float | int | str]:
    if kind is ForecastModelKind.moving_average:
        return {"window": moving_window}
    if kind is ForecastModelKind.holt:
        alpha, beta, sse = fit_holt(values)
        return {"alpha": alpha, "beta": beta, "training_sse": sse}
    if kind is ForecastModelKind.seasonal_naive:
        return {"period": seasonal_period}
    return {}


def _evaluate_candidate(
    kind: ForecastModelKind,
    train: np.ndarray,
    test: np.ndarray,
    *,
    moving_window: int,
    seasonal_period: int,
) -> ModelEvaluation:
    parameters = _parameters(
        train,
        kind,
        moving_window=moving_window,
        seasonal_period=seasonal_period,
    )
    predicted = _predictions(kind, train, len(test), parameters)
    return ModelEvaluation(
        model=kind,
        parameters=parameters,
        metrics=error_metrics(test, predicted),
    )


def _split(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    test_size = max(2, math.ceil(len(values) * 0.2))
    return values[:-test_size], values[-test_size:]


def _score(evaluation: ModelEvaluation) -> tuple[float, float, float, int]:
    """Rank by MAE, RMSE, sMAPE, then the documented simpler-model order."""
    metrics = evaluation.metrics
    return (
        metrics.mae,
        metrics.rmse,
        metrics.smape,
        MODEL_ORDER.index(evaluation.model),
    )


def forecast_series(
    series: TimeSeries,
    *,
    horizon: int,
    moving_window: int = 3,
    seasonal_period: int = 4,
    assumptions: tuple[str, ...] = (),
) -> ForecastResult:
    """Select a model chronologically and return one bounded forecast result."""
    _check_horizon(series, horizon)
    if moving_window < 1:
        raise ForecastValidationError("moving_window must be at least 1.")
    if seasonal_period < 2:
        raise ForecastValidationError("seasonal_period must be at least 2.")

    values = _array(series)
    train, test = _split(values)
    naive = _evaluate_candidate(
        ForecastModelKind.naive,
        train,
        test,
        moving_window=moving_window,
        seasonal_period=seasonal_period,
    )
    candidates: list[ModelEvaluation] = []
    for kind in MODEL_ORDER:
        if (
            kind is ForecastModelKind.seasonal_naive
            and (len(values) < 2 * seasonal_period or len(train) < 2 * seasonal_period)
        ):
            continue
        try:
            candidates.append(
                _evaluate_candidate(
                    kind,
                    train,
                    test,
                    moving_window=moving_window,
                    seasonal_period=seasonal_period,
                )
            )
        except ForecastValidationError:
            continue

    best = min(candidates, key=_score) if candidates else None
    chosen = best if best is not None and best.metrics.mae < naive.metrics.mae else naive
    if chosen.model is ForecastModelKind.naive:
        selection_note = (
            "Naive baseline retained: no candidate model had lower held-out MAE "
            f"({naive.metrics.mae:.6g})."
        )
    elif best is not None:
        selection_note = (
            f"Selected {chosen.model.value} because its held-out MAE "
            f"({chosen.metrics.mae:.6g}) is lower than naive "
            f"({naive.metrics.mae:.6g})."
        )
    else:  # pragma: no cover - guarded by the branch above
        selection_note = "Naive baseline retained."

    full_parameters = _parameters(
        values,
        chosen.model,
        moving_window=moving_window,
        seasonal_period=seasonal_period,
    )
    projected = _predictions(chosen.model, values, horizon, full_parameters)
    residuals = test - _predictions(chosen.model, train, len(test), chosen.parameters)
    sigma = float(np.std(residuals, ddof=0))
    summary = history_summary(series)
    step = timedelta(seconds=summary.step_seconds)
    last_timestamp = summary.last_timestamp
    assert last_timestamp is not None
    points: list[ForecastPoint] = []
    for step_number, value in enumerate(projected, start=1):
        margin = INTERVAL_Z * sigma * math.sqrt(step_number)
        points.append(
            ForecastPoint(
                step=step_number,
                timestamp=last_timestamp + step * step_number,
                value=float(value),
                lower=max(0.0, float(value) - margin),
                upper=float(value) + margin,
            )
        )

    warnings: list[str] = []
    if series.fill_report.filled_points:
        warnings.append(
            f"{series.fill_report.filled_points} missing value(s) were filled "
            f"using {series.fill_report.policy.value}; this affects the projection."
        )
    if summary.irregular_spacing:
        warnings.append(
            "Observation timestamps are irregularly spaced; forecast points use "
            "the median spacing and are not tied to real calendar events."
        )
    if sigma == 0.0:
        warnings.append("Held-out residuals are zero, so intervals collapse to the point forecast.")
    if chosen.model is ForecastModelKind.naive and candidates:
        warnings.append("The naive baseline was preferred over every candidate model.")

    note_lines = [MODEL_NOTE, APPROX_INTERVAL_NOTE]
    if series.provenance is DataProvenance.synthetic:
        note_lines.append("SYNTHETIC data: projection derived from generated illustration data.")
    return ForecastResult(
        series_id=series.series_id,
        provenance=series.provenance,
        data_label=series.label,
        unit=series.unit,
        model=chosen.model,
        parameters=full_parameters,
        history=summary,
        forecast_points=tuple(points),
        evaluation=chosen,
        naive_evaluation=naive,
        beats_naive=chosen.model is not ForecastModelKind.naive,
        selection_note=selection_note,
        fill_report=series.fill_report,
        assumptions=(*note_lines, *assumptions),
        warnings=tuple(warnings),
    )


# A descriptive alias used by the UI and tests.
select_model = forecast_series

__all__ = [
    "GRID_VALUES",
    "MODEL_ORDER",
    "allowed_horizon",
    "error_metrics",
    "fit_holt",
    "forecast_series",
    "history_summary",
    "holt_forecast",
    "linear_trend_fit",
    "linear_trend_forecast",
    "moving_average_forecast",
    "naive_forecast",
    "seasonal_naive_forecast",
    "select_model",
]
