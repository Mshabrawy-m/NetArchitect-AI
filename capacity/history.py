"""Bounded in-session history of capacity runs.

The store keeps deterministic :class:`~capacity.models.CapacityRun` objects in
creation order and enforces ``MAX_CAPACITY_RUNS`` without dropping old results
silently. The UI holds one store under one session key.
"""

from __future__ import annotations

from config.limits import MAX_CAPACITY_RUNS
from core.exceptions import LimitsExceededError

from .models import CapacityRun


class CapacityHistory:
    """A bounded, ordered collection of capacity runs."""

    def __init__(self, *, max_runs: int = MAX_CAPACITY_RUNS) -> None:
        if max_runs < 1:
            raise ValueError(f"max_runs must be at least 1, got {max_runs}")
        self.max_runs = max_runs
        self._runs: list[CapacityRun] = []

    @property
    def runs(self) -> tuple[CapacityRun, ...]:
        """Return retained runs in creation order."""
        return tuple(self._runs)

    def __len__(self) -> int:
        return len(self._runs)

    def add(self, run: CapacityRun) -> None:
        """Append one run, enforcing the count bound."""
        if len(self._runs) + 1 > self.max_runs:
            raise LimitsExceededError(
                "Cannot retain another capacity run; the limit is "
                f"{self.max_runs} capacity runs"
            )
        self._runs.append(run)

    def remove(self, index: int) -> CapacityRun:
        """Remove and return the run at ``index``."""
        if index < 0 or index >= len(self._runs):
            raise IndexError(
                f"Capacity run index {index} is outside 0..{len(self._runs) - 1}"
            )
        return self._runs.pop(index)

    def clear(self) -> None:
        """Remove every retained run."""
        self._runs.clear()


__all__ = ["CapacityHistory"]
