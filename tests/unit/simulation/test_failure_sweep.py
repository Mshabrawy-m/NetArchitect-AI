"""Bounded N-1/N-2 failure sweep tests with deterministic provenance."""

from __future__ import annotations

import pytest

from config.limits import MAX_N2_PAIRS
from core.exceptions import LimitsExceededError, ScenarioValidationError
from core.schemas.scenario import ScenarioType
from digital_twin import SharedRiskGroup
from simulation import failure_sweep as sweep_module
from simulation.failure_sweep import (
    FailureSweepDepth,
    FailureSweepStopReason,
    failure_sweep_to_csv,
    failure_sweep_to_json,
    plan_failure_sweep,
    run_failure_sweep,
)
from simulation.models import SimulationAssumptions
from simulation.scenarios import run_scenario

from .helpers import (
    line_twin,
    make_demand,
    make_link,
    make_scenario,
    make_topology,
    make_twin,
)


def _demand_twin():
    return line_twin(
        demands=(
            make_demand("one", "a", "c", 10.0),
            make_demand("two", "a", "c", 20.0),
        )
    )


def test_n1_plan_covers_every_link_and_device() -> None:
    twin = _demand_twin()

    plan = plan_failure_sweep(twin, FailureSweepDepth.n1)

    assert plan.depth is FailureSweepDepth.n1
    assert plan.total_cases == 5
    assert [case.target_link_ids for case in plan.cases[:2]] == [
        ("ab",),
        ("bc",),
    ]
    assert [case.target_device_ids for case in plan.cases[2:]] == [
        ("a",),
        ("b",),
        ("c",),
    ]


def test_n1_case_state_matches_direct_single_failure_scenario() -> None:
    twin = _demand_twin()
    result = run_failure_sweep(twin, SimulationAssumptions(), limit=5)
    link_case = next(
        case for case in result.cases if case.plan.target_link_ids == ("ab",)
    )
    direct = run_scenario(
        twin,
        make_scenario(ScenarioType.single_link_failure, affected_links=["ab"]),
        SimulationAssumptions(),
    )

    assert link_case.state.model_dump(mode="json") == direct.scenario_state.model_dump(
        mode="json"
    )
    assert result.stop_reason is FailureSweepStopReason.completed


def test_shared_risk_group_expands_targets_without_extra_cases() -> None:
    group = SharedRiskGroup(id="same-site", link_ids=("ab", "bc"))
    twin = _demand_twin().model_copy(update={"shared_risk_groups": (group,)})

    plan = plan_failure_sweep(twin, FailureSweepDepth.n1)
    link_case = next(
        case for case in plan.cases if case.target_link_ids == ("ab",)
    )
    result = run_failure_sweep(twin, SimulationAssumptions(), limit=1)

    assert plan.total_cases == 5
    assert link_case.failed_link_ids == ("ab", "bc")
    assert link_case.shared_risk_group_ids == ("same-site",)
    assert result.cases[0].plan.shared_risk_group_ids == ("same-site",)


def test_n2_chosen_subset_is_capped_and_reports_full_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sweep_module, "MAX_N2_PAIRS", 2)
    twin = _demand_twin()

    result = run_failure_sweep(
        twin,
        SimulationAssumptions(),
        depth=FailureSweepDepth.n2,
        selected_link_ids=("ab", "bc"),
        selected_device_ids=("a", "c"),
        max_pairs=2,
    )

    assert result.total_cases == 6
    assert result.evaluated_cases == 2
    assert result.stop_reason is FailureSweepStopReason.case_limit
    assert any("only the first 2" in warning for warning in result.warnings)


def test_n2_cap_cannot_be_raised_above_the_global_limit() -> None:
    with pytest.raises(LimitsExceededError):
        plan_failure_sweep(
            _demand_twin(),
            FailureSweepDepth.n2,
            selected_link_ids=("ab", "bc"),
            max_pairs=MAX_N2_PAIRS + 1,
        )


def test_unknown_n2_targets_and_depth_are_typed_errors() -> None:
    twin = _demand_twin()
    with pytest.raises(ScenarioValidationError):
        plan_failure_sweep(
            twin,
            FailureSweepDepth.n2,
            selected_link_ids=("missing", "ab"),
        )
    with pytest.raises(ScenarioValidationError):
        plan_failure_sweep(twin, "n3")


def test_slice_reports_full_total_and_continues_from_start() -> None:
    twin = _demand_twin()

    first = run_failure_sweep(twin, SimulationAssumptions(), limit=2)
    second = run_failure_sweep(twin, SimulationAssumptions(), start=2, limit=2)

    assert (first.total_cases, first.shown_cases) == (5, 2)
    assert first.stop_reason is FailureSweepStopReason.case_limit
    assert (second.total_cases, second.start, second.shown_cases) == (5, 2, 2)
    assert {case.plan.case_id for case in first.cases}.isdisjoint(
        {case.plan.case_id for case in second.cases}
    )


def test_cancel_stops_before_the_next_case_and_keeps_partial_results() -> None:
    twin = _demand_twin()
    calls = 0

    def should_cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    result = run_failure_sweep(
        twin,
        SimulationAssumptions(),
        limit=5,
        should_cancel=should_cancel,
    )

    assert result.stop_reason is FailureSweepStopReason.cancelled
    assert result.evaluated_cases == 1
    assert result.shown_cases == 1


def test_runtime_budget_reports_runtime_limit() -> None:
    result = run_failure_sweep(
        _demand_twin(),
        SimulationAssumptions(),
        max_runtime_seconds=1e-9,
    )

    assert result.stop_reason is FailureSweepStopReason.runtime_limit
    assert result.cases == ()


def test_n2_without_a_subset_has_no_failures() -> None:
    result = run_failure_sweep(
        _demand_twin(),
        SimulationAssumptions(),
        depth=FailureSweepDepth.n2,
    )

    assert result.stop_reason is FailureSweepStopReason.no_failures
    assert result.total_cases == 0
    assert result.cases == ()
    assert any("at least two entities" in warning for warning in result.warnings)


def test_impact_rank_prefers_the_case_with_more_unserved_demands() -> None:
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bc", "b", "c", cost=1.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
        ],
    )
    twin = make_twin(
        topology,
        (
            make_demand("backbone-one", "a", "c", 10.0),
            make_demand("backbone-two", "a", "c", 10.0),
            make_demand("stub-one", "c", "d", 10.0),
            make_demand("stub-two", "c", "d", 10.0),
            make_demand("other-stub", "b", "d", 10.0),
        ),
    )

    result = run_failure_sweep(twin, SimulationAssumptions())

    assert [case.rank for case in result.cases] == list(range(1, 9))
    assert result.cases[0].plan.target_device_ids == ("c",)
    assert result.cases[0].impact.newly_unserved_count == 4


def test_exports_are_byte_deterministic() -> None:
    twin = _demand_twin()
    first = run_failure_sweep(twin, SimulationAssumptions(), limit=3)
    second = run_failure_sweep(twin, SimulationAssumptions(), limit=3)

    assert failure_sweep_to_json(first) == failure_sweep_to_json(second)
    assert failure_sweep_to_csv(first) == failure_sweep_to_csv(second)
    assert failure_sweep_to_csv(first).startswith("Rank,Case,Targeted links,")
