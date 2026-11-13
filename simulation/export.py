"""Deterministic JSON and CSV exports for scenario runs.

Exports contain only values already stored on the run. No timestamp is added,
so exporting the same run always produces identical bytes. JSON keys are
sorted and CSV output uses the standard library writer with ``\\n`` line
endings.
"""

from __future__ import annotations

import csv
import io
import json

from .scenarios import ScenarioRun
from .tables import metric_rows


def run_to_json(run: ScenarioRun, *, indent: int | None = 2) -> str:
    """Serialize a complete run, including both states and traceability."""
    return json.dumps(
        run.model_dump(mode="json"),
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
    )


def run_to_json_bytes(run: ScenarioRun) -> bytes:
    """Return the compact UTF-8 JSON encoding of a run."""
    return run_to_json(run, indent=None).encode("utf-8")


def run_to_csv(run: ScenarioRun) -> str:
    """Return the before/after headline metrics as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    rows = metric_rows(run.baseline_state, run.scenario_state)
    writer.writerow(["Metric", "Baseline", "Scenario", "Delta"])
    for row in rows:
        writer.writerow(
            [row["Metric"], row["Baseline"], row["Scenario"], row["Delta"]]
        )
    return buffer.getvalue()


__all__ = ["run_to_csv", "run_to_json", "run_to_json_bytes"]
