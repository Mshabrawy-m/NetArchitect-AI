"""Bounded session history for capacity runs."""

from __future__ import annotations

import pytest

from capacity import CapacityHistory, DemandMapping, evaluate_capacity
from config.limits import MAX_CAPACITY_RUNS
from core.exceptions import LimitsExceededError
from tests.unit.capacity.helpers import constant_run, line_capacity_twin


def _run(value: float):
    twin = line_capacity_twin()
    forecast = constant_run(value)
    mapping = DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0)
    return evaluate_capacity(twin, forecast, mapping)


def test_history_preserves_order_and_enforces_the_count_bound() -> None:
    history = CapacityHistory(max_runs=2)
    first = _run(20.0)
    second = _run(30.0)
    third = _run(40.0)

    history.add(first)
    history.add(second)
    assert history.runs == (first, second)
    assert len(history) == 2

    with pytest.raises(LimitsExceededError, match="limit is 2 capacity runs"):
        history.add(third)
    assert history.runs == (first, second)

    assert history.remove(0) is first
    assert history.runs == (second,)
    history.clear()
    assert history.runs == ()


def test_default_history_uses_the_configured_session_limit() -> None:
    assert CapacityHistory().max_runs == MAX_CAPACITY_RUNS
