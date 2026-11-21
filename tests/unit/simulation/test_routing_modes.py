"""Additive routing-mode tests with legacy byte-for-byte compatibility."""

from __future__ import annotations

from pathlib import Path

from config.limits import MAX_ECMP_PATHS
from core.schemas.scenario import ScenarioType
from digital_twin.serialization import to_json
from simulation.evaluator import evaluate, twin_fingerprint
from simulation.export import run_to_json_bytes
from simulation.models import RoutingMode, SimulationAssumptions
from simulation.scenarios import run_scenario

from .helpers import (
    diamond_twin,
    line_twin,
    make_demand,
    make_link,
    make_scenario,
    make_topology,
    make_twin,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _equal_cost_diamond(bandwidth: float = 20.0):
    topology = make_topology(
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("ac", "a", "c", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
        ],
    )
    return make_twin(topology, (make_demand("a-to-d", "a", "d", bandwidth),))


def test_equal_cost_diamond_splits_fifty_fifty() -> None:
    state = evaluate(
        _equal_cost_diamond(),
        SimulationAssumptions(routing_mode=RoutingMode.ecmp),
    )
    evaluation = state.demands[0]
    loads = {link.link_id: link.load_mbps for link in state.links}

    assert evaluation.served is True
    assert [split.path_device_ids for split in evaluation.splits] == [
        ("a", "b", "d"),
        ("a", "c", "d"),
    ]
    assert [split.bandwidth_mbps for split in evaluation.splits] == [10.0, 10.0]
    assert loads == {
        "ab": 10.0,
        "bd": 10.0,
        "ac": 10.0,
        "cd": 10.0,
    }
    assert state.max_utilization_percent == 10.0
    assert state.served_demand_mbps == 20.0
    assert state.warnings == ()


def test_unequal_cost_paths_do_not_split() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 12.0),))
    state = evaluate(
        twin,
        SimulationAssumptions(routing_mode=RoutingMode.ecmp),
    )
    evaluation = state.demands[0]
    loads = {link.link_id: link.load_mbps for link in state.links}

    assert len(evaluation.splits) == 1
    assert evaluation.path_device_ids == ("a", "b", "d")
    assert loads == {"ab": 12.0, "bd": 12.0, "ac": 0.0, "cd": 0.0}


def test_single_path_default_is_byte_identical_to_legacy_fixtures() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 80.0),))
    run = run_scenario(
        twin,
        make_scenario(
            ScenarioType.single_link_failure,
            affected_links=["bc"],
        ),
    )

    assert to_json(twin, indent=None) == (
        _FIXTURES / "e1_legacy_twin.json"
    ).read_text(encoding="utf-8")
    assert twin_fingerprint(twin) == (
        _FIXTURES / "e1_legacy_fingerprint.txt"
    ).read_text(encoding="utf-8")
    assert run_to_json_bytes(run) == (_FIXTURES / "e1_legacy_run.json").read_bytes()
    assert b"routing_mode" not in run_to_json_bytes(run)
    assert b'"splits"' not in run_to_json_bytes(run)


def test_default_assumptions_omit_new_fields_but_non_default_mode_is_recorded() -> None:
    default_dump = SimulationAssumptions().model_dump(mode="json")
    explicit_dump = SimulationAssumptions(
        routing_mode=RoutingMode.ecmp
    ).model_dump(mode="json")

    assert "routing_mode" not in default_dump
    assert explicit_dump["routing_mode"] == "ecmp"
    default_state = evaluate(
        line_twin(demands=(make_demand("a-to-c", "a", "c", 1.0),))
    )
    assert "splits" not in default_state.demands[0].model_dump(mode="json")


def test_ecmp_path_cap_warns_instead_of_silently_truncating() -> None:
    middle = [f"m{index:02d}" for index in range(MAX_ECMP_PATHS + 2)]
    links = [make_link(f"a-{node}", "a", node, cost=0.5) for node in middle]
    links.extend(make_link(f"{node}-d", node, "d", cost=0.5) for node in middle)
    twin = make_twin(
        make_topology(["a", "d", *middle], links),
        (make_demand("many", "a", "d", 16.0),),
    )

    state = evaluate(
        twin,
        SimulationAssumptions(routing_mode=RoutingMode.ecmp),
    )

    assert len(state.demands[0].splits) == MAX_ECMP_PATHS
    assert any("ECMP used the lexicographically first" in note for note in state.warnings)
    assert state.served_demand_mbps == 16.0
