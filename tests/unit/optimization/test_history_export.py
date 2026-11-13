"""Bounded optimization history and deterministic JSON/CSV exports."""

from __future__ import annotations

import json

import pytest

from core.exceptions import LimitsExceededError
from optimization import (
    OptimizationHistory,
    run_greedy,
    run_to_csv,
    run_to_json,
    run_to_json_bytes,
)
from tests.unit.optimization.helpers import settings, tiny_twin


def _run():
    return run_greedy(tiny_twin(), settings(max_iterations=3))


def test_history_retains_runs_in_creation_order() -> None:
    history = OptimizationHistory(max_runs=3)
    first = _run()
    second = _run()
    history.add(first)
    history.add(second)
    assert history.runs == (first, second)
    assert len(history) == 2
    assert history.remove(0) == first
    assert history.runs == (second,)


def test_history_enforces_the_count_bound() -> None:
    history = OptimizationHistory(max_runs=1)
    history.add(_run())
    with pytest.raises(LimitsExceededError, match="limit is 1 run"):
        history.add(_run())
    assert len(history) == 1


def test_history_remove_rejects_out_of_range_index() -> None:
    history = OptimizationHistory(max_runs=2)
    with pytest.raises(IndexError, match="outside"):
        history.remove(0)
    history.add(_run())
    with pytest.raises(IndexError, match="outside"):
        history.remove(1)


def test_history_requires_a_positive_bound() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        OptimizationHistory(max_runs=0)


def test_history_clear_removes_everything() -> None:
    history = OptimizationHistory(max_runs=2)
    history.add(_run())
    history.clear()
    assert history.runs == ()


def test_json_export_is_deterministic_and_contains_seed_and_settings() -> None:
    run = _run()
    first = run_to_json(run)
    second = run_to_json(run)
    assert first == second
    payload = json.loads(first)
    assert payload["seed"] == run.seed
    assert payload["settings"]["max_iterations"] == 3
    assert payload["settings"]["objectives"] == [
        objective.model_dump(mode="json") for objective in run.settings.objectives
    ]
    assert payload["algorithm"] == "greedy"
    assert "search_note" in payload
    assert run_to_json_bytes(run) == run_to_json(run, indent=None).encode("utf-8")


def test_csv_export_has_seed_settings_baseline_and_candidates() -> None:
    run = _run()
    first = run_to_csv(run)
    second = run_to_csv(run)
    assert first == second
    lines = first.strip().splitlines()
    header = lines[0].split(",")
    assert "seed" in header
    assert "max_iterations" in header
    assert "row_kind" in header
    assert header.count("rank") == 1
    assert "objective_link_count" in header
    rows = [line.split(",") for line in lines[1:]]
    baseline_rows = [row for row in rows if row[header.index("row_kind")] == "baseline"]
    candidate_rows = [
        row for row in rows if row[header.index("row_kind")] == "candidate"
    ]
    assert len(baseline_rows) == 1
    assert len(candidate_rows) == len(run.candidates)
    seed_index = header.index("seed")
    assert {row[seed_index] for row in rows} == {str(run.seed)}
    assert first.endswith("\n")
