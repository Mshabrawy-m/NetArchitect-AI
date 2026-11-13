"""Bounded, reproducible multi-objective optimization.

The package is pure Python: no Streamlit, no LLM client, and no new dependency.
GA, NSGA-II, and the deterministic greedy baseline use only Python and NumPy.
Every value is a modeled estimate from stated assumptions. A heuristic result
is never a claim of a global optimum.
"""

from .evaluator import (
    EvaluationCache,
    deadline_expired,
    evaluate_candidate,
    resolve_deadline,
)
from .greedy import run_greedy
from .models import (
    COST_NOTE,
    DEFAULT_TIERS,
    OBJECTIVE_DEFINITIONS,
    SEARCH_NOTE,
    Algorithm,
    Candidate,
    CandidateEvaluation,
    CandidateMetrics,
    CandidateRecord,
    CapacityTier,
    ConstraintResult,
    CostModel,
    HardConstraints,
    ObjectiveDefinition,
    ObjectiveDirection,
    ObjectiveKind,
    ObjectiveSpec,
    ObjectiveValue,
    OptimizationLimits,
    OptimizationRun,
    OptimizationSettings,
    StopReason,
    candidate_hash,
)
from .objectives import (
    infrastructure_cost_proxy,
    normalize_value,
    objective_value,
    weighted_score,
)
from .space import build_candidate_twin, candidate_changes

__all__ = [
    "COST_NOTE",
    "DEFAULT_TIERS",
    "OBJECTIVE_DEFINITIONS",
    "SEARCH_NOTE",
    "Algorithm",
    "Candidate",
    "CandidateEvaluation",
    "CandidateMetrics",
    "CandidateRecord",
    "CapacityTier",
    "ConstraintResult",
    "CostModel",
    "EvaluationCache",
    "HardConstraints",
    "ObjectiveDefinition",
    "ObjectiveDirection",
    "ObjectiveKind",
    "ObjectiveSpec",
    "ObjectiveValue",
    "OptimizationLimits",
    "OptimizationRun",
    "OptimizationSettings",
    "StopReason",
    "build_candidate_twin",
    "candidate_changes",
    "candidate_hash",
    "deadline_expired",
    "evaluate_candidate",
    "infrastructure_cost_proxy",
    "normalize_value",
    "objective_value",
    "resolve_deadline",
    "run_greedy",
    "weighted_score",
]
