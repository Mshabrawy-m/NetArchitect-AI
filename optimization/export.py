"""Deterministic JSON and CSV exports for optimization runs.

Exports contain only values already stored on the run, including the seed and
every setting. No timestamp is added, so exporting the same run always produces
identical bytes. JSON keys are sorted and CSV output uses ``\\n`` line endings.
"""

from __future__ import annotations

import csv
import io
import json

from .models import CandidateEvaluation, OptimizationRun


def run_to_json(run: OptimizationRun, *, indent: int | None = 2) -> str:
    """Serialize a complete run, including seed, settings, and candidates."""
    return json.dumps(
        run.model_dump(mode="json"),
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
    )


def run_to_json_bytes(run: OptimizationRun) -> bytes:
    """Return the compact UTF-8 JSON encoding of a run."""
    return run_to_json(run, indent=None).encode("utf-8")


CSV_COLUMNS: tuple[str, ...] = (
    "row_kind",
    "algorithm",
    "seed",
    "population_size",
    "max_iterations",
    "max_evaluations",
    "max_runtime_seconds",
    "stop_reason",
    "rank",
    "feasible",
    "violated_constraints",
    "weighted_score",
    "candidate_hash",
    "selected_link_ids",
    "tier_assignments",
    "cost_multipliers",
    "device_count",
    "link_count",
    "demand_count",
    "served_demand_count",
    "served_demand_ratio",
    "max_utilization_percent",
    "mean_path_cost",
    "total_path_cost",
    "infrastructure_cost_proxy",
    "spof_count",
    "min_edge_disjoint_paths",
)


def _base_row(run: OptimizationRun, evaluation: CandidateEvaluation) -> dict[str, object]:
    metrics = evaluation.metrics
    return {
        "algorithm": run.algorithm.value,
        "seed": run.seed,
        "population_size": run.settings.population_size,
        "max_iterations": run.settings.max_iterations,
        "max_evaluations": run.settings.max_evaluations,
        "max_runtime_seconds": run.settings.max_runtime_seconds,
        "stop_reason": run.stop_reason.value,
        "feasible": evaluation.feasible,
        "violated_constraints": "; ".join(evaluation.violated_constraints),
        "weighted_score": evaluation.weighted_score,
        "candidate_hash": evaluation.candidate_hash,
        "selected_link_ids": "; ".join(evaluation.candidate.selected_link_ids),
        "tier_assignments": "; ".join(
            f"{link_id}={tier}"
            for link_id, tier in evaluation.candidate.tier_assignments
        ),
        "cost_multipliers": "; ".join(
            f"{link_id}={value:g}"
            for link_id, value in evaluation.candidate.cost_multipliers
        ),
        "device_count": metrics.device_count,
        "link_count": metrics.link_count,
        "demand_count": metrics.demand_count,
        "served_demand_count": metrics.served_demand_count,
        "served_demand_ratio": metrics.served_demand_ratio,
        "max_utilization_percent": metrics.max_utilization_percent,
        "mean_path_cost": metrics.mean_path_cost,
        "total_path_cost": metrics.total_path_cost,
        "infrastructure_cost_proxy": metrics.infrastructure_cost_proxy,
        "spof_count": metrics.spof_count,
        "min_edge_disjoint_paths": metrics.min_edge_disjoint_paths,
    }


def run_to_csv(run: OptimizationRun) -> str:
    """Return one baseline row plus one row per evaluated candidate.

    Objective raw values are added as ``objective_<kind>`` columns. Rank and
    crowding columns are included when the algorithm recorded them.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    objective_kinds = [value.kind.value for value in run.baseline.objectives]
    columns = [
        *CSV_COLUMNS,
        "crowding_distance",
        *(f"objective_{kind}" for kind in objective_kinds),
    ]
    writer.writerow(columns)

    def write_row(kind: str, evaluation: CandidateEvaluation, record) -> None:
        row = _base_row(run, evaluation)
        row["row_kind"] = kind
        row["rank"] = None if record is None else record.rank
        row["crowding_distance"] = (
            None if record is None else record.crowding_distance
        )
        for value in evaluation.objectives:
            row[f"objective_{value.kind.value}"] = value.raw_value
        writer.writerow([row.get(column) for column in columns])

    write_row("baseline", run.baseline, None)
    for record in run.candidates:
        write_row("candidate", record.evaluation, record)
    return buffer.getvalue()


__all__ = ["CSV_COLUMNS", "run_to_csv", "run_to_json", "run_to_json_bytes"]
