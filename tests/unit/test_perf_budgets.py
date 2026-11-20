"""Opt-in timing budgets for the V2 hot paths.

These tests are excluded from default and smoke runs by ``pytest.ini``. They are
allowed to be slower than unit tests because they build the configured maximum
topology and twin. Thresholds use at least a 2x margin over the measured
after-change numbers in ``docs/PERFORMANCE.md``.
"""

from __future__ import annotations

import time

import pytest

from network.routing import reachability_matrix
from optimization import Algorithm, run_optimization
from scripts.profile_phase12 import (
    _max_topology,
    _max_twin,
    _optimization_settings,
)
from simulation import evaluate

pytestmark = pytest.mark.perf

ALL_PAIRS_BUDGET_SECONDS = 0.20
EVALUATE_BUDGET_SECONDS = 0.25
GA_SEARCH_SECONDS = 5.0
MIN_GA_EVALUATIONS_PER_SECOND = 5.0


def test_all_pairs_routing_budget() -> None:
    topology = _max_topology()

    started = time.perf_counter()
    reachability_matrix(topology)
    elapsed = time.perf_counter() - started

    assert elapsed < ALL_PAIRS_BUDGET_SECONDS, elapsed


def test_max_demand_evaluation_budget() -> None:
    twin = _max_twin(_max_topology())

    started = time.perf_counter()
    evaluate(twin)
    elapsed = time.perf_counter() - started

    assert elapsed < EVALUATE_BUDGET_SECONDS, elapsed


def test_ga_throughput_budget() -> None:
    settings = _optimization_settings().model_copy(
        update={
            "seed": 42,
            "max_runtime_seconds": GA_SEARCH_SECONDS,
            "max_evaluations": 20_000,
            "max_iterations": 1_000,
        }
    )

    started = time.perf_counter()
    run = run_optimization(_max_twin(_max_topology()), settings, Algorithm.genetic)
    elapsed = time.perf_counter() - started
    rate = run.evaluations / elapsed if elapsed else 0.0

    assert rate >= MIN_GA_EVALUATIONS_PER_SECOND, (rate, run.evaluations, elapsed)
