"""Unit tests for ``core.schemas.optimization``."""

import pytest
from pydantic import ValidationError

import config.limits
from core.schemas.optimization import (
    Constraint,
    ConstraintKind,
    Objective,
    ObjectiveDirection,
    OptimizationConfig,
)


def test_objective_valid() -> None:
    obj = Objective(name="cost", direction=ObjectiveDirection.minimize, weight=2.0)
    assert obj.direction is ObjectiveDirection.minimize
    assert obj.weight == 2.0


def test_objective_default_weight() -> None:
    obj = Objective(name="cost", direction="maximize")
    assert obj.weight == 1.0


def test_objective_negative_weight_invalid() -> None:
    with pytest.raises(ValidationError):
        Objective(name="cost", direction=ObjectiveDirection.minimize, weight=-1.0)


def test_constraint_hard_kind_valid() -> None:
    constraint = Constraint(name="capacity", kind=ConstraintKind.hard)
    assert constraint.kind is ConstraintKind.hard


def test_constraint_soft_kind_valid() -> None:
    constraint = Constraint(name="latency", kind="soft", tolerance=0.1)
    assert constraint.kind is ConstraintKind.soft
    assert constraint.tolerance == 0.1


def test_optimization_config_valid() -> None:
    opt_config = OptimizationConfig(
        objectives=[Objective(name="cost", direction="minimize")],
        constraints=[Constraint(name="capacity", kind="hard")],
        seed=42,
        max_iterations=100,
        population_size=50,
    )
    assert opt_config.seed == 42
    assert opt_config.max_iterations == 100


def test_optimization_config_max_iterations_over_limit_invalid() -> None:
    with pytest.raises(ValidationError):
        OptimizationConfig(
            max_iterations=config.limits.MAX_OPTIMIZATION_ITERATIONS + 1,
            population_size=10,
        )


def test_optimization_config_population_size_over_limit_invalid() -> None:
    with pytest.raises(ValidationError):
        OptimizationConfig(
            max_iterations=10,
            population_size=config.limits.MAX_POPULATION + 1,
        )


def test_optimization_config_max_iterations_zero_invalid() -> None:
    with pytest.raises(ValidationError):
        OptimizationConfig(max_iterations=0, population_size=10)


def test_optimization_config_seed_round_trip() -> None:
    opt_config = OptimizationConfig(
        objectives=[
            Objective(name="cost", direction=ObjectiveDirection.minimize, weight=2.0)
        ],
        constraints=[Constraint(name="capacity", kind=ConstraintKind.hard, tolerance=0.05)],
        seed=7,
        max_iterations=500,
        population_size=100,
    )
    restored = OptimizationConfig.model_validate_json(opt_config.model_dump_json())
    assert restored == opt_config
    assert restored.seed == 7
