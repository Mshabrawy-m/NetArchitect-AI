"""Deterministic in-memory exports for forecast results."""

from __future__ import annotations

import csv
import io
import json

from .models import ForecastRun, TimeSeries


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def forecast_json(run: ForecastRun) -> bytes:
    """Return JSON that carries provenance, settings, and every assumption."""
    return _json_bytes(run.model_dump(mode="json"))


def forecast_csv(run: ForecastRun) -> bytes:
    """Return one row per forecast point with provenance on every row."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "series_id",
            "provenance",
            "data_label",
            "unit",
            "model",
            "beats_naive",
            "step",
            "timestamp",
            "value",
            "lower_approx",
            "upper_approx",
            "selection_note",
        ]
    )
    for result in run.results:
        for point in result.forecast_points:
            writer.writerow(
                [
                    result.series_id,
                    result.provenance.value,
                    result.data_label,
                    result.unit.value,
                    result.model.value,
                    str(result.beats_naive).lower(),
                    point.step,
                    point.timestamp.isoformat(),
                    f"{point.value:.6f}",
                    "" if point.lower is None else f"{point.lower:.6f}",
                    "" if point.upper is None else f"{point.upper:.6f}",
                    result.selection_note,
                ]
            )
    return buffer.getvalue().encode("utf-8")


def series_csv(series: tuple[TimeSeries, ...]) -> bytes:
    """Return the accepted input rows, including provenance, as CSV."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["timestamp", "series_id", "value", "unit", "provenance", "data_label"])
    for item in series:
        for observation in item.observations:
            writer.writerow(
                [
                    observation.timestamp.isoformat(),
                    item.series_id,
                    f"{observation.value:.6f}",
                    item.unit.value,
                    item.provenance.value,
                    item.label,
                ]
            )
    return buffer.getvalue().encode("utf-8")


__all__ = ["forecast_csv", "forecast_json", "series_csv"]
