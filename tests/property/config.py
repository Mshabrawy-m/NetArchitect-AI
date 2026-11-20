"""Shared Hypothesis settings for bounded, reproducible property tests."""

from __future__ import annotations

from hypothesis import HealthCheck, settings

BOUNDED = settings(
    max_examples=50,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
