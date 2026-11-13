"""Unit tests for scenario validation, execution, comparison, and history."""

from __future__ import annotations

import pytest

from config.limits import MAX_SCENARIO_ELEMENTS
from core.exceptions import LimitsExceededError, ScenarioValidationError
from core.schemas.scenario import ScenarioType
from simulation import (
    ScenarioHistory,
    SimulationAssumptions,
    compare_runs,
    run_scenario,
    run_to_csv,
    run_to_json,
    validate_scenario,
)

from .helpers import (
    diamond_twin,
    line_twin,
    make_demand,
    make_scenario,
    make_twin,
)


def test_single_link_failure_reroutes_and_reports_path_change() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bd"],
    )

    run = run_scenario(twin, scenario)

    assert run.baseline_state.demands[0].path_device_ids == ("a", "b", "d")
    assert run.scenario_state.demands[0].path_device_ids == ("a", "c", "d")
    assert run.scenario_state.failed_links == ("bd",)
    assert run.comparison.newly_unserved_demands == ()
    assert run.comparison.path_changes[0].name == "a-to-d"
    assert run.comparison.recovery_available is True
    assert "remain served" in run.comparison.recovery_note


def test_multiple_link_failures_and_node_failure_reroute() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    multiple = make_scenario(
        ScenarioType.multiple_link_failures,
        affected_links=["ab", "bd"],
    )
    node = make_scenario(
        ScenarioType.node_failure,
        affected_nodes=["b"],
    )

    multiple_run = run_scenario(twin, multiple)
    node_run = run_scenario(twin, node)

    assert multiple_run.scenario_state.demands[0].path_device_ids == (
        "a",
        "c",
        "d",
    )
    assert node_run.scenario_state.demands[0].path_device_ids == ("a", "c", "d")
    assert node_run.scenario_state.failed_devices == ("b",)


def test_unserved_scenario_loses_service_and_reports_recovery_false() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bc"],
    )

    run = run_scenario(twin, scenario)

    assert run.baseline_state.served_demand_count == 1
    assert run.scenario_state.served_demand_count == 0
    assert run.comparison.newly_unserved_demands == ("a-to-c",)
    assert run.comparison.recovery_available is False
    assert "Service was lost" in run.comparison.recovery_note


def test_bandwidth_reduction_by_percent_and_mbps() -> None:
    twin = line_twin(demands=(make_demand("a-to-b", "a", "b", 30.0),))
    percent = make_scenario(
        ScenarioType.bandwidth_reduction,
        affected_links=["ab"],
        parameters={"percent": 50},
    )
    mbps = make_scenario(
        ScenarioType.bandwidth_reduction,
        affected_links=["ab"],
        parameters={"mbps": 40},
    )

    percent_run = run_scenario(twin, percent)
    mbps_run = run_scenario(twin, mbps)

    assert percent_run.scenario_state.links[0].capacity_mbps == pytest.approx(50.0)
    assert percent_run.scenario_state.links[0].utilization_percent == pytest.approx(
        60.0
    )
    assert mbps_run.scenario_state.links[0].capacity_mbps == pytest.approx(60.0)
    assert mbps_run.scenario_state.links[0].utilization_percent == pytest.approx(50.0)
    assert percent_run.comparison.max_utilization_delta_percent == pytest.approx(30.0)


def test_traffic_increase_by_factor_and_per_demand_factors() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 20.0),))
    factor = make_scenario(
        ScenarioType.increased_traffic_demand,
        parameters={"factor": 2.5},
    )
    targeted = line_twin(
        demands=(
            make_demand("a-to-b", "a", "b", 10.0),
            make_demand("b-to-c", "b", "c", 20.0),
        )
    )
    factors = make_scenario(
        ScenarioType.increased_traffic_demand,
        parameters={"demand_factors": {"a-to-b": 3.0}},
    )

    factor_run = run_scenario(twin, factor)
    factors_run = run_scenario(targeted, factors)

    assert factor_run.scenario_state.total_demand_mbps == pytest.approx(50.0)
    assert factor_run.scenario_state.max_utilization_percent == pytest.approx(50.0)
    assert factors_run.scenario_state.demands[0].bandwidth_mbps == pytest.approx(30.0)
    assert factors_run.scenario_state.demands[1].bandwidth_mbps == pytest.approx(20.0)


@pytest.mark.parametrize(
    "parameters",
    [
        {"cost": 10.0},
        {"cost_factor": 10.0},
        {"costs": {"ab": 10.0}},
    ],
)
def test_routing_cost_change_moves_traffic_to_the_other_branch(
    parameters: dict[str, object],
) -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    scenario = make_scenario(
        ScenarioType.routing_cost_change,
        affected_links=["ab"],
        parameters=parameters,
    )

    run = run_scenario(twin, scenario)

    assert run.scenario_state.demands[0].path_device_ids == ("a", "c", "d")


def test_network_expansion_adds_entities_without_touching_baseline() -> None:
    twin = line_twin()
    before = twin.model_copy(deep=True)
    scenario = make_scenario(
        ScenarioType.network_expansion,
        parameters={
            "expansion": {
                "devices": [
                    {
                        "id": "d",
                        "type": "switch",
                        "site": "site-1",
                        "role": "access",
                    }
                ],
                "links": [
                    {
                        "id": "cd",
                        "endpoints": ["c", "d"],
                        "capacity_mbps": 100.0,
                        "cost": 1.0,
                    }
                ],
                "demands": [
                    {
                        "name": "a-to-d",
                        "source": "a",
                        "destination": "d",
                        "bandwidth_mbps": 10.0,
                    }
                ],
            }
        },
    )

    run = run_scenario(twin, scenario)

    assert run.scenario_state.device_count == 4
    assert run.scenario_state.link_count == 3
    assert run.scenario_state.served_demand_count == 1
    assert run.scenario_state.demands[0].path_device_ids == ("a", "b", "c", "d")
    assert twin == before
    assert run.baseline_twin.fingerprint != run.scenario_twin.fingerprint
    assert run.comparison.recovered_demands == ("a-to-d",)


def test_new_department_uses_the_same_validated_expansion_contract() -> None:
    twin = line_twin()
    scenario = make_scenario(
        ScenarioType.new_department,
        parameters={
            "expansion": {
                "devices": [
                    {
                        "id": "dept",
                        "type": "switch",
                        "site": "site-2",
                        "role": "access",
                    }
                ],
                "links": [
                    {
                        "id": "c-dept",
                        "endpoints": ["c", "dept"],
                        "capacity_mbps": 100.0,
                        "cost": 1.0,
                    }
                ],
            }
        },
    )

    run = run_scenario(twin, scenario)

    assert run.scenario_state.device_count == 4
    assert run.scenario_state.link_count == 3


def test_redundancy_recovery_test_reports_recovery_available() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    scenario = make_scenario(
        ScenarioType.redundancy_recovery_test,
        affected_links=["bd"],
    )

    run = run_scenario(twin, scenario)

    assert run.comparison.recovery_available is True
    assert run.comparison.newly_unserved_demands == ()


def test_traceability_records_inputs_assumptions_and_fingerprints() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 80.0),))
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bc"],
    )

    run = run_scenario(twin, scenario)

    assert run.scenario.id == "scenario-1"
    assert run.scenario.affected_links == ["bc"]
    assert run.baseline_twin.schema_version == twin.metadata.schema_version
    assert run.scenario_twin.schema_version == twin.metadata.schema_version
    assert len(run.baseline_twin.fingerprint) == 64
    assert run.assumptions.thresholds == run.thresholds
    assert run.model_note.startswith("Modeled estimates")
    assert run.baseline_state.twin == run.baseline_twin
    assert run.scenario_state.twin == run.scenario_twin


def test_results_are_reproducible_and_do_not_mutate_the_baseline() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    before = twin.model_copy(deep=True)
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bd"],
    )

    first = run_scenario(twin, scenario)
    second = run_scenario(twin, scenario)

    assert first == second
    assert run_to_json(first) == run_to_json(second)
    assert twin == before


def test_json_and_csv_exports_are_deterministic() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 20.0),))
    scenario = make_scenario(
        ScenarioType.increased_traffic_demand,
        parameters={"factor": 2.0},
    )
    run = run_scenario(twin, scenario)

    payload = run_to_json(run)
    csv_text = run_to_csv(run)

    assert '"baseline_state"' in payload
    assert '"scenario_twin"' in payload
    assert '"comparison"' in payload
    assert payload == run_to_json(run)
    assert csv_text.splitlines()[0] == "Metric,Baseline,Scenario,Delta"
    assert "Max utilization (%)" in csv_text
    assert csv_text == run_to_csv(run)


def test_compare_runs_uses_the_scenario_states() -> None:
    first_twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))
    second_twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 30.0),))

    first = run_scenario(
        first_twin,
        make_scenario(
            ScenarioType.increased_traffic_demand,
            scenario_id="first",
            parameters={"factor": 1.0},
        ),
    )
    second = run_scenario(
        second_twin,
        make_scenario(
            ScenarioType.increased_traffic_demand,
            scenario_id="second",
            parameters={"factor": 1.0},
        ),
    )
    comparison = compare_runs(first, second)

    assert comparison.max_utilization_delta_percent == pytest.approx(20.0)
    assert comparison.scenario_served_demand_count == 1


def test_scenario_history_is_bounded_and_supports_removal() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bc"],
    )
    run = run_scenario(twin, scenario)
    history = ScenarioHistory(max_runs=2)

    history.add(run)
    history.add(run)

    assert len(history) == 2
    with pytest.raises(LimitsExceededError):
        history.add(run)
    assert history.remove(0) == run
    assert len(history) == 1
    history.clear()
    assert history.runs == ()


def test_assumptions_are_shared_by_both_evaluations() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        affected_links=["bd"],
    )
    assumptions = SimulationAssumptions(link_delay_ms={"ab": 1.0, "bd": 1.0})

    run = run_scenario(twin, scenario, assumptions)

    assert run.baseline_state.demands[0].latency_ms == pytest.approx(2.0)
    assert run.scenario_state.demands[0].latency_ms is None


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        (
            make_scenario(
                ScenarioType.single_link_failure,
                affected_links=["ab", "bc"],
            ),
            "exactly one",
        ),
        (
            make_scenario(
                ScenarioType.multiple_link_failures,
                affected_links=["ab"],
            ),
            "at least two",
        ),
        (
            make_scenario(
                ScenarioType.node_failure,
                affected_nodes=["a", "b"],
            ),
            "exactly one",
        ),
        (
            make_scenario(
                ScenarioType.single_link_failure,
                affected_links=["ghost"],
            ),
            "Unknown affected link",
        ),
        (
            make_scenario(
                ScenarioType.single_link_failure,
                affected_links=["ab", "ab"],
            ),
            "Duplicate affected link",
        ),
        (
            make_scenario(
                ScenarioType.bandwidth_reduction,
                affected_links=["ab"],
                parameters={"percent": 100},
            ),
            "below 100",
        ),
        (
            make_scenario(
                ScenarioType.bandwidth_reduction,
                affected_links=["ab"],
                parameters={"percent": 10, "mbps": 5},
            ),
            "exactly one",
        ),
        (
            make_scenario(
                ScenarioType.increased_traffic_demand,
                parameters={"factor": 2.0, "demand_factors": {"a-to-c": 2.0}},
            ),
            "exactly one",
        ),
        (
            make_scenario(
                ScenarioType.increased_traffic_demand,
                parameters={"demand_factors": {"ghost": 2.0}},
            ),
            "Unknown demand",
        ),
        (
            make_scenario(ScenarioType.network_expansion),
            "expansion",
        ),
        (
            make_scenario(
                ScenarioType.routing_cost_change,
                affected_links=["ab"],
                parameters={"costs": {"ghost": 2.0}},
            ),
            "Unknown link",
        ),
    ],
)
def test_invalid_scenarios_raise_actionable_typed_errors(
    scenario,
    message: str,
) -> None:
    with pytest.raises(ScenarioValidationError, match=message):
        run_scenario(line_twin(), scenario)


def test_scenario_element_limit_is_enforced() -> None:
    scenario = make_scenario(
        ScenarioType.multiple_link_failures,
        affected_links=[f"link-{index}" for index in range(MAX_SCENARIO_ELEMENTS + 1)],
    )

    with pytest.raises(ScenarioValidationError, match="limit is 50"):
        validate_scenario(line_twin(), scenario)


def test_empty_scenario_id_and_name_are_rejected() -> None:
    scenario = make_scenario(
        ScenarioType.single_link_failure,
        scenario_id=" ",
        name=" ",
        affected_links=["ab"],
    )

    with pytest.raises(ScenarioValidationError) as error:
        validate_scenario(line_twin(), scenario)

    assert "id must not be empty" in str(error.value)
    assert "name must not be empty" in str(error.value)


def test_validate_scenario_accepts_a_valid_scenario() -> None:
    validate_scenario(
        line_twin(),
        make_scenario(
            ScenarioType.single_link_failure,
            affected_links=["ab"],
        ),
    )


def test_traffic_increase_without_demands_is_rejected() -> None:
    with pytest.raises(ScenarioValidationError, match="no traffic demands"):
        run_scenario(
            line_twin(),
            make_scenario(
                ScenarioType.increased_traffic_demand,
                parameters={"factor": 2},
            ),
        )


def test_demand_updates_preserve_existing_demands() -> None:
    twin = make_twin(
        line_twin(
            demands=(
                make_demand("keep", "a", "b", 10.0),
                make_demand("grow", "b", "c", 10.0),
            )
        ).topology,
        (
            make_demand("keep", "a", "b", 10.0),
            make_demand("grow", "b", "c", 10.0),
        ),
    )

    run = run_scenario(
        twin,
        make_scenario(
            ScenarioType.increased_traffic_demand,
            parameters={"demand_factors": {"grow": 4.0}},
        ),
    )

    assert run.scenario_state.demands[0].bandwidth_mbps == pytest.approx(10.0)
    assert run.scenario_state.demands[1].bandwidth_mbps == pytest.approx(40.0)
