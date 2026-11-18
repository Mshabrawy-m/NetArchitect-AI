"""Demand mapping and provenance tests."""

from __future__ import annotations

import pytest

from capacity import DemandMapping, project_demands
from forecasting import DataProvenance, SeriesUnit
from tests.unit.capacity.helpers import constant_run, line_capacity_twin
from tests.unit.forecasting.helpers import make_series


def _codes(projection: object) -> set[str]:
    return {finding.code.value for finding in projection.findings}  # type: ignore[attr-defined]


def test_user_series_requires_supplied_per_user_assumption() -> None:
    twin = line_capacity_twin()
    run = constant_run(8.0)
    mapping = DemandMapping(series_to_demand={"s1": "call"})

    without = project_demands(twin, run, mapping)
    assert "missing_per_user_assumption" in _codes(without)
    assert without.demands == ()

    with_assumption = project_demands(
        twin,
        run,
        DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=2.5),
    )
    assert with_assumption.demands[0].points[0].bandwidth_mbps == pytest.approx(20.0)
    assert "Mbps per user" in with_assumption.assumptions[3]


def test_mbps_series_does_not_need_per_user_assumption() -> None:
    twin = line_capacity_twin()
    run = constant_run(12.0, unit=SeriesUnit.mbps)
    projection = project_demands(twin, run, DemandMapping(series_to_demand={"s1": "call"}))

    assert projection.demands[0].points[0].bandwidth_mbps == pytest.approx(12.0)
    assert projection.per_user_mbps is None


def test_unmapped_series_unknown_demand_and_duplicate_mapping() -> None:
    twin = line_capacity_twin()
    run = constant_run(5.0)
    projection = project_demands(
        twin,
        run,
        DemandMapping(series_to_demand={"s1": "missing-demand"}),
    )
    assert "unknown_demand" in _codes(projection)

    extra = make_series([5.0] * 10, series_id="s2")
    from forecasting import ForecastRun, GapPolicy, forecast_series

    run_with_extra = ForecastRun(
        results=(
            run.results[0],
            forecast_series(extra, horizon=2),
        ),
        horizon=2,
        gap_policy=GapPolicy.reject,
    )
    codes = _codes(project_demands(twin, run_with_extra, DemandMapping()))
    assert codes == {"unmapped_series", "no_mapped_demand"}

    with pytest.raises(ValueError, match="at most one series"):
        DemandMapping(
            series_to_demand={"s1": "call", "s2": "call"},
            per_user_mbps=1.0,
        )


def test_synthetic_provenance_is_reported_in_projection() -> None:
    twin = line_capacity_twin()
    run = constant_run(9.0, provenance=DataProvenance.synthetic)
    projection = project_demands(
        twin,
        run,
        DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0),
    )
    assert projection.has_synthetic
    assert projection.demands[0].data_label == "SYNTHETIC"
