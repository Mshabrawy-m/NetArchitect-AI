"""Unit tests for the abstract flow evaluator."""

from __future__ import annotations

import pytest

from config.limits import MAX_SIMULATION_RUNTIME_SECONDS
from core.exceptions import LimitsExceededError, SimulationRuntimeExceeded
from digital_twin import DeviceState, LinkState, OperationalState
from simulation import (
    CongestionLevel,
    CongestionThresholds,
    SimulationAssumptions,
    evaluate,
)
from simulation import evaluator as evaluator_module

from .helpers import (
    diamond_twin,
    line_twin,
    make_demand,
    make_link,
    make_topology,
    make_twin,
)


def test_line_load_is_reported_per_link_in_warning_band() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 80.0),))

    state = evaluate(twin)

    assert [link.link_id for link in state.links] == ["ab", "bc"]
    assert [link.utilization_percent for link in state.links] == pytest.approx(
        [80.0, 80.0]
    )
    assert all(link.level is CongestionLevel.warning for link in state.links)
    assert state.max_utilization_percent == pytest.approx(80.0)
    assert state.congested_link_count == 2
    assert state.overloaded_link_count == 0
    assert state.demands[0].path_device_ids == ("a", "b", "c")
    assert state.demands[0].link_ids == ("ab", "bc")
    assert state.served_demand_count == 1
    assert state.served_demand_ratio == pytest.approx(1.0)


def test_utilization_above_100_percent_is_never_clamped() -> None:
    twin = line_twin(demands=(make_demand("overload", "a", "b", 150.0),))

    state = evaluate(twin)

    link = state.links[0]
    assert link.load_mbps == pytest.approx(150.0)
    assert link.utilization_percent == pytest.approx(150.0)
    assert link.level is CongestionLevel.overloaded
    assert state.max_utilization_percent == pytest.approx(150.0)
    assert state.overloaded_link_count == 1


def test_undirected_link_shares_capacity_across_both_directions() -> None:
    twin = line_twin(
        demands=(
            make_demand("forward", "a", "b", 60.0),
            make_demand("reverse", "b", "a", 50.0),
        )
    )

    state = evaluate(twin)

    link = state.links[0]
    assert link.forward_load_mbps == pytest.approx(60.0)
    assert link.reverse_load_mbps == pytest.approx(50.0)
    assert link.load_mbps == pytest.approx(110.0)
    assert link.utilization_percent == pytest.approx(110.0)
    assert link.forward_demand_names == ("forward",)
    assert link.reverse_demand_names == ("reverse",)
    assert link.level is CongestionLevel.overloaded


def test_directed_link_records_only_its_permitted_direction() -> None:
    topology = make_topology(
        ["a", "b"],
        [make_link("ab", "a", "b", directed=True)],
    )
    twin = make_twin(
        topology,
        (
            make_demand("forward", "a", "b", 40.0),
            make_demand("reverse", "b", "a", 10.0),
        ),
    )

    state = evaluate(twin)

    link = state.links[0]
    assert link.forward_load_mbps == pytest.approx(40.0)
    assert link.reverse_load_mbps == pytest.approx(0.0)
    assert link.load_mbps == pytest.approx(40.0)
    assert state.unserved_demands[0].name == "reverse"
    assert "No directed path" in state.unserved_demands[0].reason


def test_failed_bridge_reports_unserved_demand_and_disconnected_device() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))
    failed = twin.model_copy(
        update={
            "link_states": (
                LinkState(link_id="bc", state=OperationalState.down),
            )
        }
    )

    state = evaluate(failed)

    assert state.failed_links == ("bc",)
    assert [link.link_id for link in state.links] == ["ab"]
    assert state.unserved_demands[0].name == "a-to-c"
    assert "No directed path" in state.unserved_demands[0].reason
    assert state.weak_components == (("a", "b"), ("c",))
    assert state.disconnected_devices == ("c",)
    assert state.served_demand_count == 0
    assert state.served_demand_ratio == pytest.approx(0.0)


def test_failed_device_removes_incident_links_and_isolates_peers() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))
    failed = twin.model_copy(
        update={
            "device_states": (
                DeviceState(device_id="b", state=OperationalState.down),
            )
        }
    )

    state = evaluate(failed)

    assert state.failed_devices == ("b",)
    assert state.links == ()
    assert state.isolated_devices == ("a", "c")
    assert state.disconnected_devices == ("c",)
    assert state.unserved_demands[0].reason.startswith("No directed path")


def test_latency_is_estimated_only_when_every_hop_has_an_assumption() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))

    complete = evaluate(
        twin,
        SimulationAssumptions(link_delay_ms={"ab": 1.5, "bc": 2.5}),
    )
    partial = evaluate(twin, SimulationAssumptions(link_delay_ms={"ab": 1.5}))
    absent = evaluate(twin)

    assert complete.demands[0].latency_ms == pytest.approx(4.0)
    assert partial.demands[0].latency_ms is None
    assert "bc" in partial.demands[0].latency_note
    assert absent.demands[0].latency_ms is None
    assert "not estimated" in absent.demands[0].latency_note


def test_custom_thresholds_change_the_reported_band() -> None:
    twin = line_twin(demands=(make_demand("load", "a", "b", 25.0),))
    assumptions = SimulationAssumptions(
        thresholds=CongestionThresholds(
            warning_percent=10.0,
            critical_percent=20.0,
            overload_percent=30.0,
        )
    )

    state = evaluate(twin, assumptions)

    assert state.links[0].level is CongestionLevel.critical
    assert state.thresholds.critical_percent == pytest.approx(20.0)


def test_evaluation_is_deterministic_and_does_not_mutate_the_twin() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 30.0),))
    before = twin.model_copy(deep=True)

    first = evaluate(twin)
    second = evaluate(twin)

    assert first == second
    assert first.twin.fingerprint == second.twin.fingerprint
    assert len(first.twin.fingerprint) == 64
    assert twin == before


def test_parallel_links_reuse_the_routing_engine_tie_break() -> None:
    topology = make_topology(
        ["a", "b"],
        [
            make_link("z-expensive", "a", "b", cost=5.0),
            make_link("a-cheap", "a", "b", cost=1.0),
        ],
    )
    twin = make_twin(topology, (make_demand("load", "a", "b", 50.0),))

    state = evaluate(twin)

    loads = {link.link_id: link for link in state.links}
    assert state.demands[0].link_ids == ("a-cheap",)
    assert loads["a-cheap"].load_mbps == pytest.approx(50.0)
    assert loads["z-expensive"].load_mbps == pytest.approx(0.0)


def test_unknown_demand_endpoint_is_unserved_with_a_reason() -> None:
    topology = make_topology(["a"], [])
    twin = make_twin(topology, (make_demand("ghost", "a", "missing", 10.0),))

    state = evaluate(twin)

    assert state.demands[0].served is False
    assert "not present" in state.demands[0].reason
    assert state.unserved_demands[0].name == "ghost"


def test_stale_state_is_reported_as_a_warning() -> None:
    twin = line_twin()
    stale = twin.model_copy(
        update={
            "link_states": (
                LinkState(link_id="removed-link", state=OperationalState.down),
            )
        }
    )

    state = evaluate(stale)

    assert state.failed_links == ()
    assert state.warnings
    assert "removed-link" in state.warnings[0]


def test_runtime_guard_raises_a_typed_error(monkeypatch) -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 10.0),))
    ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    monkeypatch.setattr(
        evaluator_module.time,
        "perf_counter",
        lambda: next(ticks, 99.0),
    )

    with pytest.raises(SimulationRuntimeExceeded, match="runtime limit"):
        evaluate(twin, max_runtime_seconds=0.001)


def test_runtime_budget_above_the_global_limit_is_rejected() -> None:
    with pytest.raises(LimitsExceededError):
        evaluate(
            line_twin(),
            max_runtime_seconds=MAX_SIMULATION_RUNTIME_SECONDS + 1,
        )


def test_invalid_threshold_order_is_rejected() -> None:
    with pytest.raises(ValueError):
        CongestionThresholds(
            warning_percent=90.0,
            critical_percent=70.0,
            overload_percent=100.0,
        )
