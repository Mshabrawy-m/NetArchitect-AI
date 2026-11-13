"""Shared evaluation budget for the population-based algorithms.

The baseline design is evaluated before the search phase so a run always has
baseline metrics even when the search budget is exhausted immediately. The
search phase then stops cleanly at the evaluation or wall-clock limit with a
typed :class:`~optimization.models.StopReason`.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.exceptions import OptimizationRuntimeExceeded
from digital_twin import DigitalTwin

from ..evaluator import (
    EvaluationCache,
    deadline_expired,
    evaluate_candidate,
    resolve_deadline,
)
from ..models import (
    Candidate,
    CandidateEvaluation,
    OptimizationSettings,
    StopReason,
)


@dataclass
class SearchBudget:
    """Evaluation and wall-clock budget shared by one algorithm run."""

    settings: OptimizationSettings
    cache: EvaluationCache
    deadline: float
    stop_reason: StopReason | None = None

    @classmethod
    def start(
        cls,
        settings: OptimizationSettings,
        cache: EvaluationCache,
        deadline: float | None,
    ) -> SearchBudget:
        """Create a budget whose clock starts after baseline evaluation."""
        return cls(
            settings=settings,
            cache=cache,
            deadline=resolve_deadline(settings, deadline),
        )

    @property
    def exhausted(self) -> bool:
        """Return whether the search must stop."""
        return self.stop_reason is not None

    def check(self) -> bool:
        """Return whether another evaluation is allowed, recording any stop."""
        if self.stop_reason is not None:
            return False
        if deadline_expired(self.deadline):
            self.stop_reason = StopReason.runtime_limit
            return False
        if self.cache.misses >= self.settings.max_evaluations:
            self.stop_reason = StopReason.max_evaluations
            return False
        return True

    def evaluate(
        self,
        baseline_twin: DigitalTwin,
        candidate: Candidate,
    ) -> CandidateEvaluation | None:
        """Evaluate ``candidate`` if budget remains, else return ``None``."""
        if not self.check():
            return None
        try:
            return evaluate_candidate(
                baseline_twin,
                candidate,
                self.settings,
                cache=self.cache,
                deadline=self.deadline,
            )
        except OptimizationRuntimeExceeded:
            self.stop_reason = StopReason.runtime_limit
            return None


__all__ = ["SearchBudget"]
