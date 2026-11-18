"""Free-tier default-limit assertions added in Phase 14.0."""

from __future__ import annotations

from config.limits import (
    DEFAULT_OPTIMIZATION_RUNTIME_SECONDS,
    MAX_OPTIMIZATION_RUNTIME_SECONDS,
    MAX_SCENARIOS,
)
from optimization import OptimizationSettings
from tests.unit.optimization.helpers import settings


def test_free_tier_defaults_keep_user_override_range() -> None:
    # Hand-computed expectations from the owner's 14.0c decision:
    # retained scenarios 50 -> 20; optimization default 30 -> 20 s; the
    # hard cap remains 60 s so a user can deliberately raise the budget.
    assert MAX_SCENARIOS == 20
    assert DEFAULT_OPTIMIZATION_RUNTIME_SECONDS == 20
    assert MAX_OPTIMIZATION_RUNTIME_SECONDS == 60
    assert OptimizationSettings.model_fields["max_runtime_seconds"].default == 20
    assert settings().max_runtime_seconds == 20.0
    assert settings(max_runtime_seconds=60.0).max_runtime_seconds == 60.0
