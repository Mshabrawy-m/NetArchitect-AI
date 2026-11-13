"""Algorithm dispatch for one bounded optimization run."""

from __future__ import annotations

from digital_twin import DigitalTwin

from ..models import Algorithm, OptimizationRun, OptimizationSettings
from .genetic import run_genetic
from .nsga2 import run_nsga2


def run_optimization(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    algorithm: Algorithm,
    *,
    deadline: float | None = None,
) -> OptimizationRun:
    """Run ``algorithm`` with a shared result shape and budget policy.

    PSO is deliberately absent: :class:`~optimization.models.Algorithm` exposes
    only the algorithms with a sound mapping onto this discrete design space.
    """
    if algorithm is Algorithm.genetic:
        return run_genetic(baseline_twin, settings, deadline=deadline)
    if algorithm is Algorithm.nsga2:
        return run_nsga2(baseline_twin, settings, deadline=deadline)
    if algorithm is Algorithm.greedy:
        from ..greedy import run_greedy

        return run_greedy(baseline_twin, settings, deadline=deadline)
    raise ValueError(f"Unsupported optimization algorithm: {algorithm!r}")


__all__ = ["run_optimization"]
