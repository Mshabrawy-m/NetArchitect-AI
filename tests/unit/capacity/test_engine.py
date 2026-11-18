"""Capacity evaluation, crossing, recommendation, and limit tests."""

from __future__ import annotations

import pytest

from capacity import (
    CapacityRun,
    CapacityStopReason,
    DemandMapping,
    engine,
    evaluate_capacity,
)
from core.exceptions import CapacityLimitError
from forecasting import ForecastRun, GapPolicy, forecast_series
from optimization.models import CapacityTier, CostModel
from simulation import twin_fingerprint
from simulation.models import CongestionLevel
from tests.unit.capacity.helpers import constant_run, line_capacity_twin
from tests.unit.forecasting.helpers import make_series


def _run(constant: float = 30.0, horizon: int = 2, *, capacity: float = 20.0):
    twin = line_capacity_twin(bandwidth=10.0, capacity=capacity)
    run = constant_run(constant, horizon)
    mapping = DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0)
    return twin, run, mapping


def test_crossings_ranking_and_unchanged_baseline() -> None:
    twin, run, mapping = _run()
    before = twin_fingerprint(twin)
    result = evaluate_capacity(twin, run, mapping)

    assert twin_fingerprint(twin) == before
    assert result.twin_fingerprint == before
    assert result.baseline.links[0].utilization_percent == pytest.approx(50.0)
    assert [state.step for state in result.steps] == [1, 2]
    assert result.steps[0].state.links[0].utilization_percent == pytest.approx(150.0)

    assert len(result.crossings) == 6
    assert {crossing.level for crossing in result.crossings} == {
        CongestionLevel.warning,
        CongestionLevel.critical,
        CongestionLevel.overloaded,
    }
    assert result.bottlenecks[0].peak_utilization_percent == pytest.approx(150.0)
    assert result.bottlenecks[0].headroom_mbps == pytest.approx(-10.0)
    assert result.bounds.stop_reason is CapacityStopReason.completed
    assert result.bounds.used_evaluations == 3


def test_recommendation_uses_smallest_tier_and_positive_cost_delta() -> None:
    twin, run, mapping = _run()
    cost = CostModel(
        tiers=(
            CapacityTier(name="20", capacity_mbps=20.0, link_cost_proxy=20.0),
            CapacityTier(name="50", capacity_mbps=50.0, link_cost_proxy=50.0),
            CapacityTier(name="100", capacity_mbps=100.0, link_cost_proxy=200.0),
        )
    )
    result = evaluate_capacity(twin, run, mapping, cost_model=cost)

    assert len(result.recommendations) == 2
    assert {item.target_tier_name for item in result.recommendations} == {"50"}
    assert result.recommendations[0].cost_delta == pytest.approx(30.0)
    assert result.recommendations[0].projected_utilization_percent == pytest.approx(60.0)
    assert result.total_cost_delta == pytest.approx(60.0)


def test_no_tier_suffices_reports_a_gap() -> None:
    twin, run, mapping = _run()
    cost = CostModel(
        tiers=(
            CapacityTier(name="20", capacity_mbps=20.0, link_cost_proxy=20.0),
            CapacityTier(name="40", capacity_mbps=40.0, link_cost_proxy=40.0),
        )
    )
    result = evaluate_capacity(twin, run, mapping, cost_model=cost)

    assert result.recommendations == ()
    assert len(result.gaps) == 2
    assert result.gaps[0].required_capacity_mbps == pytest.approx(3000.0 / 70.0)
    assert result.gaps[0].largest_available_capacity_mbps == pytest.approx(40.0)


def test_evaluation_budget_stops_before_projected_steps() -> None:
    twin, run, mapping = _run()
    result = evaluate_capacity(twin, run, mapping, max_evaluations=1)

    assert result.steps == ()
    assert result.bounds.used_evaluations == 1
    assert result.bounds.stop_reason is CapacityStopReason.no_projection


def test_horizon_is_clipped_and_reported() -> None:
    twin = line_capacity_twin(bandwidth=10.0)
    run = ForecastRun(
        results=(forecast_series(make_series([20.0] * 30), horizon=13),),
        horizon=13,
        gap_policy=GapPolicy.reject,
    )
    mapping = DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0)
    result = evaluate_capacity(twin, run, mapping)

    assert len(result.steps) == 12
    assert {item.code.value for item in result.projection.findings} >= {"horizon_clipped"}
    assert result.bounds.used_evaluations == 13
    assert result.bounds.stop_reason is CapacityStopReason.completed


def test_runtime_budget_is_reported_as_a_typed_stop_reason(monkeypatch) -> None:
    twin, run, mapping = _run()
    baseline = evaluate_capacity(
        twin,
        ForecastRun(
            results=run.results,
            horizon=1,
            gap_policy=GapPolicy.reject,
        ),
        mapping,
    ).baseline
    times = iter([0.0, 10.0, 10.0])
    monkeypatch.setattr(engine.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(engine, "evaluate", lambda *_args, **_kwargs: baseline)

    result = evaluate_capacity(twin, run, mapping, max_runtime_seconds=1.0)
    assert result.bounds.stop_reason is CapacityStopReason.runtime_limit
    assert result.steps == ()


def test_invalid_budgets_raise_typed_errors() -> None:
    twin, run, mapping = _run()
    with pytest.raises(CapacityLimitError, match="allowed range"):
        evaluate_capacity(twin, run, mapping, max_evaluations=0)
    with pytest.raises(CapacityLimitError, match="allowed range"):
        evaluate_capacity(twin, run, mapping, max_runtime_seconds=31.0)


def test_result_is_serializable_with_provenance() -> None:
    twin, run, mapping = _run()
    result: CapacityRun = evaluate_capacity(twin, run, mapping)
    payload = result.model_dump(mode="json")

    assert payload["projection"]["demands"][0]["data_label"] == "USER-SUPPLIED"
    assert payload["bounds"]["stop_reason"] == "completed"
    assert "not measurements or guarantees" in payload["note"]
