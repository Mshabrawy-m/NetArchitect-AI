"""Unit tests for ``core.schemas.scenario``."""

import pytest
from pydantic import ValidationError

from core.schemas.scenario import Scenario, ScenarioResult, ScenarioType


def test_scenario_valid() -> None:
    scenario = Scenario(
        id="sc-1",
        name="Down link",
        type=ScenarioType.single_link_failure,
        affected_links=["l1"],
    )
    assert scenario.type is ScenarioType.single_link_failure


def test_scenario_default_fields() -> None:
    scenario = Scenario(id="sc-1", name="x", type="node_failure")
    assert scenario.affected_links == []
    assert scenario.parameters == {}


def test_scenario_invalid_type_invalid() -> None:
    with pytest.raises(ValidationError):
        Scenario(id="sc-1", name="x", type="not-a-scenario-type")


def test_scenario_json_round_trip() -> None:
    scenario = Scenario(
        id="sc-1",
        name="Down links",
        type=ScenarioType.multiple_link_failures,
        description="Two links fail",
        affected_links=["l1", "l2"],
        affected_nodes=["n1"],
        parameters={"severity": 0.8},
    )
    assert Scenario.model_validate_json(scenario.model_dump_json()) == scenario


def test_scenario_result_valid() -> None:
    result = ScenarioResult(
        scenario_id="sc-1",
        success=True,
        reachable_nodes=["r1", "r2"],
        disconnected_nodes=["r3"],
        estimated_path_cost=42.5,
        recovery_available=True,
    )
    assert result.success is True
    assert result.estimated_path_cost == 42.5


def test_scenario_result_negative_cost_invalid() -> None:
    with pytest.raises(ValidationError):
        ScenarioResult(scenario_id="sc-1", success=True, estimated_path_cost=-1.0)


def test_scenario_result_json_round_trip() -> None:
    result = ScenarioResult(
        scenario_id="sc-1",
        success=False,
        disconnected_nodes=["r3"],
        selected_paths={"d1": ["r1", "r2"]},
        warnings=["link l1 congested"],
        summary="partial",
    )
    assert ScenarioResult.model_validate_json(result.model_dump_json()) == result
