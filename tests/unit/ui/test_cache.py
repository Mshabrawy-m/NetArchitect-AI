"""Tests for content-keyed UI caches."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capacity import DemandMapping, evaluate_capacity
from forecasting import GapPolicy
from optimization import CostModel
from simulation import SimulationAssumptions
from tests.unit.capacity.helpers import constant_run, line_capacity_twin
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.forecasting.helpers import make_series
from ui import cache
from ui.cache import (
    cached_capacity_run,
    cached_design_health,
    cached_forecast_run,
    cached_report,
    capacity_series_payload,
    capacity_source_payload,
    source_payload,
    twin_cache_key,
    twin_payload,
)


def test_twin_cache_key_is_stable_for_one_twin_and_changes_with_content() -> None:
    twin = make_twin()
    same = make_twin()

    assert twin_cache_key(twin) == twin_cache_key(same)
    assert twin_payload(twin) == twin_payload(same)

    changed = twin.model_copy(
        update={"metadata": twin.metadata.model_copy(update={"name": "Renamed"})}
    )
    assert twin_cache_key(changed) != twin_cache_key(twin)
    assert twin_payload(changed) != twin_payload(twin)


def test_source_payload_is_empty_only_for_no_source() -> None:
    assert source_payload(None) == ""


def test_cached_design_health_is_reused_until_the_twin_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = cache.build_design_health

    def spy(twin, **kwargs):
        calls.append(twin.metadata.name)
        return original(twin, **kwargs)

    monkeypatch.setattr(cache, "build_design_health", spy)
    cached_design_health.clear()

    first = make_twin()
    payload = twin_payload(first)

    assert cached_design_health(payload, False).summary == "No design-health findings."
    assert cached_design_health(payload, False).summary == "No design-health findings."
    assert calls == [first.metadata.name]

    changed = first.model_copy(
        update={"metadata": first.metadata.model_copy(update={"name": "Other"})}
    )
    cached_design_health(twin_payload(changed), False)
    assert calls == [first.metadata.name, "Other"]


def test_capacity_payloads_are_canonical_and_empty_for_missing_runs() -> None:
    series = make_series([100.0, 101.0, 102.0])
    same = make_series([100.0, 101.0, 102.0])
    forecast = constant_run(10.0)

    assert capacity_series_payload((series,)) == capacity_series_payload((same,))
    assert capacity_series_payload((series,)) != capacity_series_payload(
        (series, make_series([1.0, 2.0, 3.0], series_id="s2"))
    )
    assert capacity_source_payload(None) == ""
    assert capacity_source_payload(forecast) == forecast.model_dump_json()


def test_cached_forecast_run_is_reused_until_an_input_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = cache.forecast_series

    def spy(series, **kwargs):
        calls.append(series.series_id)
        return original(series, **kwargs)

    monkeypatch.setattr(cache, "forecast_series", spy)
    cached_forecast_run.clear()
    payload = capacity_series_payload((make_series([10.0] * 8, series_id="users"),))

    first = cached_forecast_run(payload, 2, 3, 4, GapPolicy.reject.value)
    second = cached_forecast_run(payload, 2, 3, 4, GapPolicy.reject.value)

    assert first == second
    assert calls == ["users"]

    cached_forecast_run(payload, 3, 3, 4, GapPolicy.reject.value)
    assert calls == ["users", "users"]


def test_cached_capacity_run_is_reused_until_an_input_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []
    original = cache.evaluate_capacity
    twin = line_capacity_twin()
    forecast = constant_run(30.0)
    changed = constant_run(40.0)
    mapping = DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0)
    assumptions = SimulationAssumptions()
    cost = CostModel()

    def spy(twin_arg, forecast_arg, *args, **kwargs):
        calls.append(forecast_arg.results[0].evaluation.metrics.mae)
        return original(twin_arg, forecast_arg, *args, **kwargs)

    monkeypatch.setattr(cache, "evaluate_capacity", spy)
    cached_capacity_run.clear()

    args = (
        twin_payload(twin),
        forecast.model_dump_json(),
        mapping.model_dump_json(),
        assumptions.model_dump_json(),
        cost.model_dump_json(),
        24,
        30.0,
    )
    first = cached_capacity_run(*args)
    second = cached_capacity_run(*args)
    cached_capacity_run(
        twin_payload(twin),
        changed.model_dump_json(),
        mapping.model_dump_json(),
        assumptions.model_dump_json(),
        cost.model_dump_json(),
        24,
        30.0,
    )

    assert first == second
    assert len(calls) == 2


def test_cached_report_includes_the_selected_capacity_source() -> None:
    cached_report.clear()
    twin = line_capacity_twin()
    forecast = constant_run(30.0)
    mapping = DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0)
    run = evaluate_capacity(twin, forecast, mapping)
    generated_at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

    with_capacity = cached_report(
        twin_payload(twin),
        "",
        "",
        generated_at.isoformat(),
        capacity_payload=capacity_source_payload(run),
    )
    without_capacity = cached_report(
        twin_payload(twin),
        "",
        "",
        generated_at.isoformat(),
    )

    assert with_capacity.section("capacity").status.value == "available"
    assert without_capacity.section("capacity").status.value == "not_run"
    assert any(
        record.key == "capacity.projected_steps"
        for record in with_capacity.values
    )
