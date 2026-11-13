"""Unit tests for presentational row helpers."""

from __future__ import annotations

import pytest

from simulation import (
    demand_rows,
    evaluate,
    format_path,
    link_rows,
    metric_rows,
    path_change_rows,
    unserved_rows,
)

from .helpers import line_twin, make_demand, make_twin


def test_link_rows_follow_topology_order_and_report_levels() -> None:
    state = evaluate(
        line_twin(
            demands=(
                make_demand("a-to-c", "a", "c", 80.0),
                make_demand("overload", "a", "b", 30.0),
            )
        )
    )

    rows = link_rows(state)

    assert [row["Link"] for row in rows] == ["ab", "bc"]
    assert rows[0]["Congestion"] == "overloaded"
    assert rows[0]["Demands"] == "a-to-c, overload"
    assert rows[1]["Congestion"] == "warning"


def test_demand_and_unserved_rows_explain_the_outcome() -> None:
    twin = line_twin(
        demands=(
            make_demand("served", "a", "b", 10.0),
            make_demand("missing", "a", "nowhere", 5.0),
        )
    )
    state = evaluate(twin)

    demands = demand_rows(state)
    unserved = unserved_rows(state)

    assert demands[0]["Served"] == "yes"
    assert demands[0]["Path"] == "a -> b"
    assert demands[1]["Served"] == "no"
    assert demands[1]["Path"].startswith("Unserved:")
    assert unserved[0]["Demand"] == "missing"
    assert "not present" in str(unserved[0]["Reason"])


def test_metric_rows_show_baseline_scenario_and_delta() -> None:
    baseline = evaluate(line_twin(demands=(make_demand("load", "a", "b", 20.0),)))
    scenario = evaluate(line_twin(demands=(make_demand("load", "a", "b", 50.0),)))

    rows = {row["Metric"]: row for row in metric_rows(baseline, scenario)}

    assert rows["Max utilization (%)"]["Baseline"] == pytest.approx(20.0)
    assert rows["Max utilization (%)"]["Scenario"] == pytest.approx(50.0)
    assert rows["Max utilization (%)"]["Delta"] == "+30.00%"


def test_path_change_rows_compare_by_demand_name() -> None:
    topology = line_twin().topology
    baseline = evaluate(
        make_twin(topology, (make_demand("load", "a", "c", 10.0),))
    )
    scenario = evaluate(
        make_twin(topology, (make_demand("load", "a", "b", 10.0),))
    )

    rows = path_change_rows(baseline, scenario, only_changed=True)

    assert len(rows) == 1
    assert rows[0]["Demand"] == "load"
    assert rows[0]["Baseline path"] == "a -> b -> c"
    assert rows[0]["Scenario path"] == "a -> b"
    assert rows[0]["Changed"] == "yes"


def test_format_path_for_unserved_demand_includes_reason() -> None:
    state = evaluate(line_twin(demands=(make_demand("x", "a", "ghost", 1.0),)))

    assert format_path(state.demands[0]).startswith("Unserved:")
