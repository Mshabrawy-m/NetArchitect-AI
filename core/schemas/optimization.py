"""Optimization domain models.

Objectives, constraints, and the configuration that bounds an optimization
run. The upper bounds on iterations and population come from
:mod:`config.limits` so the application stays within resource limits.
"""

from enum import Enum

from pydantic import BaseModel, Field

import config.limits


class ObjectiveDirection(str, Enum):
    """Whether an objective should be minimized or maximized."""

    minimize = "minimize"  # Lower values are better.
    maximize = "maximize"  # Higher values are better.


class Objective(BaseModel):
    """A single optimization objective with a weight and optional expression."""

    name: str = Field(description="Human-readable objective name.")
    description: str = Field(
        default="",
        description="Free-form description of the objective.",
    )
    direction: ObjectiveDirection = Field(
        description="Whether to minimize or maximize."
    )
    weight: float = Field(
        default=1.0,
        description="Relative weight of the objective (non-negative).",
        ge=0,
    )
    unit: str = Field(
        default="",
        description="Unit the objective is measured in, if applicable.",
    )
    expression: str = Field(
        default="",
        description="Optional symbolic expression for the objective.",
    )


class ConstraintKind(str, Enum):
    """Whether a constraint is mandatory (hard) or a preference (soft)."""

    hard = "hard"  # Must be satisfied; a violation invalidates the solution.
    soft = "soft"  # A preference; violations are penalized, not forbidden.


class Constraint(BaseModel):
    """A single optimization constraint (hard or soft)."""

    name: str = Field(description="Human-readable constraint name.")
    description: str = Field(
        default="",
        description="Free-form description of the constraint.",
    )
    kind: ConstraintKind = Field(description="Whether the constraint is hard or soft.")
    expression: str = Field(
        default="",
        description="Optional symbolic expression for the constraint.",
    )
    threshold: float | None = Field(
        default=None,
        description="Optional threshold the expression is bounded by.",
    )
    tolerance: float = Field(
        default=0.0,
        description="Tolerance band around the threshold (non-negative).",
        ge=0,
    )


class OptimizationConfig(BaseModel):
    """Configuration bounding a single optimization run.

    Iteration and population caps come from :mod:`config.limits` so runs
    cannot exceed Streamlit Community Cloud Free resource limits.
    """

    objectives: list[Objective] = Field(
        default_factory=list,
        description="Objectives the optimizer pursues.",
    )
    constraints: list[Constraint] = Field(
        default_factory=list,
        description="Constraints the solution must respect.",
    )
    seed: int = Field(
        default=0,
        description="Random seed for reproducible optimization runs (non-negative).",
        ge=0,
    )
    max_iterations: int = Field(
        description="Maximum iterations for the run (1..MAX_OPTIMIZATION_ITERATIONS).",
        ge=1,
        le=config.limits.MAX_OPTIMIZATION_ITERATIONS,
    )
    population_size: int = Field(
        default=50,
        description="Population size for population-based algorithms (1..MAX_POPULATION).",
        ge=1,
        le=config.limits.MAX_POPULATION,
    )
