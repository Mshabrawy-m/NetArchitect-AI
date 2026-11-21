"""Opt-in N-1 failure-sweep timing checks.

Excluded from default runs by ``pytest.ini``. Each check prints the measured
before (one direct scenario run per failure) and after (one shared-deadline
sweep) timings so the final report can quote both the medium and maximum
topology profiles. Budgets use at least a 2x margin over measured numbers.
"""

from __future__ import annotations

import time

import pytest

from core.schemas.scenario import ScenarioType
from network.topology.generators import generate_hierarchical_campus
from scripts.profile_phase12 import _max_topology, _max_twin
from simulation import run_failure_sweep, run_scenario
from simulation.models import SimulationAssumptions
from tests.unit.simulation.helpers import make_scenario

pytestmark = pytest.mark.perf

CASE_COUNT = 12
N1_MEDIUM_SWEEP_BUDGET_SECONDS = 0.30
N1_MAX_SWEEP_BUDGET_SECONDS = 1.50


def _medium_twin():
    topology = generate_hierarchical_campus(
        name="Failure sweep medium campus",
        distribution_count=5,
        access_per_distribution=20,
        redundant_uplinks=True,
        id_prefix="sweep-medium",
    )
    return _max_twin(topology)


def _measure(label: str, twin, *, max_topology: bool) -> None:
    assumptions = SimulationAssumptions()
    link_ids = sorted(link.id for link in twin.topology.links)[:CASE_COUNT]
    scenarios = tuple(
        make_scenario(
            ScenarioType.single_link_failure,
            scenario_id=f"sweep-{index:02d}",
            affected_links=[link_id],
        )
        for index, link_id in enumerate(link_ids)
    )

    started = time.perf_counter()
    runs = tuple(
        run_scenario(twin, scenario, assumptions) for scenario in scenarios
    )
    before = time.perf_counter() - started
    assert len(runs) == CASE_COUNT

    started = time.perf_counter()
    result = run_failure_sweep(twin, assumptions, limit=CASE_COUNT)
    after = time.perf_counter() - started
    assert result.evaluated_cases == CASE_COUNT
    assert result.stop_reason.value in {"completed", "case_limit"}

    budget = (
        N1_MAX_SWEEP_BUDGET_SECONDS if max_topology else N1_MEDIUM_SWEEP_BUDGET_SECONDS
    )
    size = "max" if max_topology else "medium"
    print(f"before_direct_n1_{size}_seconds={before:.6f}")
    print(f"after_sweep_n1_{size}_seconds={after:.6f}")
    assert after < budget, (size, after, budget)


def test_n1_medium_budget() -> None:
    _measure("medium", _medium_twin(), max_topology=False)


def test_n1_max_budget() -> None:
    _measure("max", _max_twin(_max_topology()), max_topology=True)
