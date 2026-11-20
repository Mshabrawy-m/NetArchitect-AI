"""Byte-for-byte objective-vector regression for the V2 hot-path change.

``v2_objective_vectors.json`` was captured from commit ``3e31a41`` (before the
sparse routing and per-run caching changes) with the seeded fixtures below.
The sparse paths and caches must not change any objective value.
"""

from __future__ import annotations

import json
from pathlib import Path

from optimization import Algorithm, run_optimization
from tests.unit.optimization.helpers import settings, tiny_twin

FIXTURE = (Path(__file__).with_name("v2_objective_vectors.json")).read_bytes()


def _vector(evaluation) -> dict[str, object]:
    return {
        "hash": evaluation.candidate_hash,
        "objectives": [
            {
                "kind": value.kind.value,
                "raw": f"{value.raw_value!r}",
                "normalized": f"{value.normalized_value!r}",
                "contribution": f"{value.contribution!r}",
            }
            for value in evaluation.objectives
        ],
        "score": f"{evaluation.weighted_score!r}",
    }


def _payload() -> dict[str, object]:
    config = settings(max_iterations=4, max_evaluations=40)
    payload: dict[str, object] = {}
    for algorithm in (Algorithm.genetic, Algorithm.nsga2):
        run = run_optimization(tiny_twin(), config, algorithm)
        payload[algorithm.value] = {
            "baseline": _vector(run.baseline),
            "candidates": [ _vector(record.evaluation) for record in run.candidates ],
            "evaluations": run.evaluations,
            "stop_reason": run.stop_reason.value,
        }
    return payload


def test_seeded_ga_and_nsga2_objective_vectors_are_byte_identical() -> None:
    actual = json.dumps(_payload(), sort_keys=True, separators=(",", ":")).encode()

    assert actual == FIXTURE
