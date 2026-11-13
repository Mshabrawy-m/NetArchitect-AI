"""Bounded in-session history of optimization runs.

The store keeps immutable :class:`~optimization.models.OptimizationRun` objects
in creation order and enforces ``MAX_OPTIMIZATION_RUNS``. It raises
:class:`~core.exceptions.LimitsExceededError` instead of dropping the oldest run
silently. Persistence is the caller's responsibility; the UI stores one store
under one session key.
"""

from __future__ import annotations

from config.limits import MAX_OPTIMIZATION_RUNS
from core.exceptions import LimitsExceededError

from .models import OptimizationRun


class OptimizationHistory:
    """A bounded, ordered collection of optimization runs."""

    def __init__(self, *, max_runs: int = MAX_OPTIMIZATION_RUNS) -> None:
        if max_runs < 1:
            raise ValueError(f"max_runs must be at least 1, got {max_runs}")
        self.max_runs = max_runs
        self._runs: list[OptimizationRun] = []

    @property
    def runs(self) -> tuple[OptimizationRun, ...]:
        """Return retained runs in creation order."""
        return tuple(self._runs)

    def __len__(self) -> int:
        return len(self._runs)

    def add(self, run: OptimizationRun) -> None:
        """Append a run, enforcing the count bound."""
        if len(self._runs) + 1 > self.max_runs:
            raise LimitsExceededError(
                f"Cannot retain optimization run {run.algorithm.value!r}: the "
                f"limit is {self.max_runs} runs"
            )
        self._runs.append(run)

    def remove(self, index: int) -> OptimizationRun:
        """Remove and return the run at ``index``."""
        if index < 0 or index >= len(self._runs):
            raise IndexError(
                f"Optimization run index {index} is outside "
                f"0..{len(self._runs) - 1}"
            )
        return self._runs.pop(index)

    def clear(self) -> None:
        """Remove every retained run."""
        self._runs.clear()


__all__ = ["OptimizationHistory"]
