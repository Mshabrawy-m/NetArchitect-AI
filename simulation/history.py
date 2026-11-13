"""Bounded in-session history of scenario runs.

The store keeps deterministic :class:`~simulation.scenarios.ScenarioRun`
objects in creation order. It enforces ``MAX_SCENARIOS`` and raises
:class:`~core.exceptions.LimitsExceededError` instead of dropping the oldest
result silently. Persistence is the caller's responsibility; the UI stores one
store under one session key.
"""

from __future__ import annotations

from config.limits import MAX_SCENARIOS
from core.exceptions import LimitsExceededError

from .scenarios import ScenarioRun


class ScenarioHistory:
    """A bounded, ordered collection of scenario runs."""

    def __init__(self, *, max_runs: int = MAX_SCENARIOS) -> None:
        if max_runs < 1:
            raise ValueError(f"max_runs must be at least 1, got {max_runs}")
        self.max_runs = max_runs
        self._runs: list[ScenarioRun] = []

    @property
    def runs(self) -> tuple[ScenarioRun, ...]:
        """Return retained runs in creation order."""
        return tuple(self._runs)

    def __len__(self) -> int:
        return len(self._runs)

    def add(self, run: ScenarioRun) -> None:
        """Append a run, enforcing the count bound."""
        if len(self._runs) + 1 > self.max_runs:
            raise LimitsExceededError(
                f"Cannot retain scenario {run.scenario.name!r}: the limit is "
                f"{self.max_runs} scenario runs"
            )
        self._runs.append(run)

    def remove(self, index: int) -> ScenarioRun:
        """Remove and return the run at ``index``."""
        if index < 0 or index >= len(self._runs):
            raise IndexError(
                f"Scenario run index {index} is outside 0..{len(self._runs) - 1}"
            )
        return self._runs.pop(index)

    def clear(self) -> None:
        """Remove every retained run."""
        self._runs.clear()


__all__ = ["ScenarioHistory"]
