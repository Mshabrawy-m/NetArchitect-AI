"""Algorithm dispatch for one bounded optimization run."""

from __future__ import annotations

from collections.abc import Sequence

from digital_twin import DigitalTwin

from ..models import Algorithm, Candidate, OptimizationRun, OptimizationSettings
from .genetic import run_genetic
from .nsga2 import run_nsga2
from .simulated_annealing import run_simulated_annealing


def run_optimization(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    algorithm: Algorithm,
    *,
    deadline: float | None = None,
    initial_candidates: Sequence[Candidate] = (),
) -> OptimizationRun:
    """Run ``algorithm`` with a shared result shape and budget policy.

    ``initial_candidates`` is the deterministic hybrid-start hook for simulated
    annealing only. GA/NSGA-II keep their exact seeded random paths, so passing
    a non-empty start to either of them is rejected rather than silently changing
    those byte-stable results. PSO remains deliberately absent.
    """
    if algorithm is Algorithm.simulated_annealing:
        return run_simulated_annealing(
            baseline_twin,
            settings,
            deadline=deadline,
            initial_candidates=initial_candidates,
        )
    if initial_candidates:
        raise ValueError(
            "initial_candidates is only supported by simulated annealing"
        )
    if algorithm is Algorithm.genetic:
        return run_genetic(baseline_twin, settings, deadline=deadline)
    if algorithm is Algorithm.nsga2:
        return run_nsga2(baseline_twin, settings, deadline=deadline)
    if algorithm is Algorithm.greedy:
        from ..greedy import run_greedy

        return run_greedy(baseline_twin, settings, deadline=deadline)
    raise ValueError(f"Unsupported optimization algorithm: {algorithm!r}")


__all__ = ["run_optimization"]
