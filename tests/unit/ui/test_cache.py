"""Tests for content-keyed UI caches."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capacity import DemandMapping, evaluate_capacity
from digital_twin import DigitalTwin
from forecasting import GapPolicy
from optimization import (
    Algorithm,
    CostModel,
    ObjectiveKind,
    ObjectiveSpec,
    ParetoReranking,
    SensitivityReport,
    SensitivityScenario,
    analyze_sensitivity,
    rerank_pareto_front,
    run_optimization,
)
from security import FlowRequest, Protocol
from simulation import (
    DEFAULT_COMPARISON_MODES,
    FailureSweepResult,
    RoutingModeComparison,
    SimulationAssumptions,
    compare_routing_modes,
    run_failure_sweep,
)
from tests.unit.capacity.helpers import constant_run, line_capacity_twin
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.forecasting.helpers import make_series
from tests.unit.optimization.helpers import settings, tiny_twin
from tests.unit.security.design_helpers import hardened_design
from ui import cache
from ui.cache import (
    cached_capacity_run,
    cached_design_health,
    cached_forecast_run,
    cached_report,
    cached_security_analysis,
    capacity_series_payload,
    capacity_source_payload,
    security_flows_payload,
    source_payload,
    twin_cache_key,
    twin_payload,
)


@pytest.fixture(scope="module")
def e5_sources() -> tuple[
    DigitalTwin,
    FailureSweepResult,
    RoutingModeComparison,
    SensitivityReport,
    ParetoReranking,
]:
    """One small twin and four bounded E5 results derived from it."""
    twin = tiny_twin(capacity_mbps=40.0)
    objectives = (
        ObjectiveSpec(
            kind=ObjectiveKind.infrastructure_cost,
            weight=0.5,
            lower_bound=0.0,
            upper_bound=500.0,
        ),
        ObjectiveSpec(
            kind=ObjectiveKind.max_utilization,
            weight=0.5,
            lower_bound=0.0,
            upper_bound=200.0,
        ),
    )
    config = settings(objectives=objectives, max_iterations=8, max_evaluations=250)
    run = run_optimization(twin, config, Algorithm.nsga2)
    return (
        twin,
        run_failure_sweep(twin, limit=1),
        compare_routing_modes(twin, modes=DEFAULT_COMPARISON_MODES[:1]),
        analyze_sensitivity(
            twin,
            run,
            scenarios=(
                SensitivityScenario(
                    id="demand_up",
                    label="Higher demand",
                    demand_multiplier=1.25,
                ),
            ),
            max_candidates=1,
        ),
        rerank_pareto_front(run),
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


def test_source_payload_serializes_e5_sources_as_non_empty_json(
    e5_sources: tuple[
        DigitalTwin,
        FailureSweepResult,
        RoutingModeComparison,
        SensitivityReport,
        ParetoReranking,
    ],
) -> None:
    _, sweep, comparison, sensitivity, reranking = e5_sources
    for source in (sweep, comparison, sensitivity, reranking):
        payload = source_payload(source)
        assert payload
        assert payload == source.model_dump_json()
        parsed = type(source).model_validate_json(payload)
        assert type(parsed) is type(source)
        assert parsed.model_dump(mode="json").keys() == source.model_dump(
            mode="json"
        ).keys()


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


def test_cached_report_includes_each_e5_source_only_when_supplied(
    e5_sources: tuple[
        DigitalTwin,
        FailureSweepResult,
        RoutingModeComparison,
        SensitivityReport,
        ParetoReranking,
    ],
) -> None:
    cached_report.clear()
    twin, sweep, comparison, sensitivity, reranking = e5_sources
    generated_at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    base = (twin_payload(twin), "", "", generated_at.isoformat())
    section_ids = ("failure_sweep", "mode_comparison", "sensitivity", "reranking")
    payloads = {
        "sweep_payload": source_payload(sweep),
        "mode_comparison_payload": source_payload(comparison),
        "sensitivity_payload": source_payload(sensitivity),
        "reranking_payload": source_payload(reranking),
    }
    fingerprints = {
        "sensitivity_source_fingerprint": sensitivity.source_twin_fingerprint,
        "rerank_source_fingerprint": twin_cache_key(twin),
    }

    empty = cached_report(*base)
    for section_id in section_ids:
        assert empty.section(section_id).status.value == "not_run"

    for keyword, section_id in (
        ("sweep_payload", "failure_sweep"),
        ("mode_comparison_payload", "mode_comparison"),
        ("sensitivity_payload", "sensitivity"),
        ("reranking_payload", "reranking"),
    ):
        selected = cached_report(*base, **{keyword: payloads[keyword]}, **fingerprints)
        assert selected.section(section_id).status.value == "available"
        for other_id in section_ids:
            if other_id != section_id:
                assert selected.section(other_id).status.value == "not_run"

    full = cached_report(*base, **payloads, **fingerprints)
    for section_id in section_ids:
        assert full.section(section_id).status.value == "available"
    for key in (
        "failure_sweep.total_cases",
        "mode_comparison.mode_count",
        "sensitivity.evaluated_candidates",
        "reranking.items",
    ):
        assert any(record.key == key for record in full.values)

    changed_sweep = run_failure_sweep(twin, limit=2)
    changed = cached_report(
        *base,
        **{**payloads, "sweep_payload": source_payload(changed_sweep)},
        **fingerprints,
    )
    assert next(
        record.numeric
        for record in full.values
        if record.key == "failure_sweep.evaluated_cases"
    ) == sweep.evaluated_cases
    assert next(
        record.numeric
        for record in changed.values
        if record.key == "failure_sweep.evaluated_cases"
    ) == changed_sweep.evaluated_cases
    assert changed != full


def test_security_analysis_cache_is_keyed_by_twin_model_and_flows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = cache.analyze_design
    twin, model = hardened_design()
    flow = FlowRequest(
        id="user-to-mgmt",
        source_device_id="user-sw",
        destination_device_id="mgmt-sw",
        protocol=Protocol.tcp,
        port=80,
    )
    changed_flow = flow.model_copy(update={"id": "other"})

    def spy(twin_arg, *, model=None, flows=()):
        calls.append(f"{twin_arg.metadata.name}:{len(flows)}")
        return original(twin_arg, model=model, flows=flows)

    monkeypatch.setattr(cache, "analyze_design", spy)
    cached_security_analysis.clear()

    args = (
        twin_payload(twin),
        model.model_dump_json(),
        security_flows_payload((flow,)),
    )
    first = cached_security_analysis(*args)
    second = cached_security_analysis(*args)
    changed = cached_security_analysis(
        twin_payload(twin),
        model.model_dump_json(),
        security_flows_payload((changed_flow,)),
    )

    assert first == second
    assert first.flow_checks[0].request.id == "user-to-mgmt"
    assert changed.flow_checks[0].request.id == "other"
    assert len(calls) == 2
    assert all(call.endswith(":1") for call in calls)


def test_security_analysis_cache_uses_fingerprint_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = cache.analyze_design
    twin, model = hardened_design()

    def spy(twin_arg, *, model=None, flows=()):
        calls.append(twin_arg.metadata.name)
        return original(twin_arg, model=model, flows=flows)

    monkeypatch.setattr(cache, "analyze_design", spy)
    cached_security_analysis.clear()

    args = (
        twin_payload(twin),
        model.model_dump_json(),
        security_flows_payload(()),
    )
    first = cached_security_analysis(*args, twin_cache_key(twin))
    second = cached_security_analysis(*args, twin_cache_key(twin))
    changed = cached_security_analysis(*args, f"revision-{twin_cache_key(twin)}")

    assert first == second
    assert first == changed
    assert len(calls) == 2
