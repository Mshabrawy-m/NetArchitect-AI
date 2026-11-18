"""Capacity Planning page with Data, Forecast, Capacity, and Downloads tabs.

The page only uses user-supplied CSV rows, a deterministic labeled SYNTHETIC
generator, the current digital twin, and the existing forecasting/capacity
engines. Every projected value is a modeled result, never a measurement or a
guarantee.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from capacity import (
    CapacityRun,
    DemandMapping,
)
from config.limits import (
    MAX_CAPACITY_EVALUATIONS,
    MAX_CAPACITY_HORIZON_STEPS,
    MAX_CAPACITY_RUNTIME_SECONDS,
    MAX_FORECAST_SERIES,
)
from core.exceptions import CapacityError, ForecastError, InputError
from forecasting import (
    GapPolicy,
    SeriesUnit,
    SyntheticSpec,
    TimeSeries,
    allowed_horizon,
    forecast_csv,
    forecast_json,
    generate_synthetic,
    parse_csv,
    series_csv,
)
from optimization import CostModel
from simulation import SimulationAssumptions
from ui import state
from ui.cache import (
    cached_capacity_run,
    cached_forecast_run,
    capacity_series_payload,
    twin_payload,
)
from ui.components import csv_bytes, empty_state, model_estimate_note, page_header

MODEL_NOTE = (
    "Modeled projections from supplied or synthetic data; not measurements or "
    "guarantees."
)
NONE_LABEL = "(not mapped)"

CSV_KEY = "capacity_csv_text"
GAP_KEY = "capacity_gap_policy"
PARSE_KEY = "capacity_parse_csv"
SYN_ID_KEY = "capacity_synthetic_series_id"
SYN_UNIT_KEY = "capacity_synthetic_unit"
SYN_BASE_KEY = "capacity_synthetic_base"
SYN_GROWTH_KEY = "capacity_synthetic_growth"
SYN_SEASONALITY_KEY = "capacity_synthetic_seasonality"
SYN_PERIOD_KEY = "capacity_synthetic_period"
SYN_NOISE_KEY = "capacity_synthetic_noise"
SYN_POINTS_KEY = "capacity_synthetic_points"
SYN_SEED_KEY = "capacity_synthetic_seed"
SYN_GENERATE_KEY = "capacity_synthetic_generate"
HORIZON_KEY = "capacity_horizon"
WINDOW_KEY = "capacity_moving_window"
SEASON_KEY = "capacity_seasonal_period"
FORECAST_KEY = "capacity_build_forecast"
PER_USER_KEY = "capacity_per_user_mbps"
MAPPING_KEY_PREFIX = "capacity_map_"
EVALUATE_KEY = "capacity_evaluate"
RUN_KEY = "capacity_selected_run"

SERIES_DOWNLOAD_KEY = "capacity_series_download"
FORECAST_CSV_DOWNLOAD_KEY = "capacity_forecast_csv_download"
FORECAST_JSON_DOWNLOAD_KEY = "capacity_forecast_json_download"
BOTTLENECK_DOWNLOAD_KEY = "capacity_bottleneck_download"
UPGRADE_DOWNLOAD_KEY = "capacity_upgrade_download"
RUN_JSON_DOWNLOAD_KEY = "capacity_run_json_download"

DEFAULT_CSV = (
    "timestamp,series_id,value,unit\n"
    "2026-01-01,subscribers,100,users\n"
    "2026-01-02,subscribers,102,users\n"
    "2026-01-03,subscribers,101,users\n"
    "2026-01-04,subscribers,104,users\n"
    "2026-01-05,subscribers,106,users\n"
    "2026-01-06,subscribers,105,users\n"
    "2026-01-07,subscribers,108,users\n"
    "2026-01-08,subscribers,110,users\n"
)


def _replace_series(series_id: str, generated: TimeSeries) -> None:
    """Replace one series by id while enforcing session bounds."""
    existing = [item for item in state.peek_capacity_series() if item.series_id != series_id]
    if len(existing) + 1 > MAX_FORECAST_SERIES:
        st.error(f"The capacity session limit is {MAX_FORECAST_SERIES} series.")
        return
    state.set_capacity_series((*existing, generated))


def _render_data_tab() -> None:
    st.subheader("Supplied data")
    st.caption(
        "Paste rows with the exact header timestamp,series_id,value,unit. Values "
        "must be non-negative, timestamps must be chronological, and a series "
        "may not mix units. Every parsing problem is reported, never silently fixed."
    )
    text = st.text_area(
        "CSV rows",
        value=state.session_get(CSV_KEY, DEFAULT_CSV),
        key=CSV_KEY,
        height=180,
    )
    gap_value = st.selectbox(
        "Missing-value policy",
        [policy.value for policy in GapPolicy],
        index=0,
        key=GAP_KEY,
        help="Leading and trailing gaps are never filled; every fill is reported.",
    )
    if st.button("Parse supplied CSV", key=PARSE_KEY):
        try:
            result = parse_csv(text, gap_policy=GapPolicy(gap_value))
        except InputError as error:
            st.error(str(error), title="CSV input rejected")
            return
        for finding in result.findings:
            if finding.severity.value == "error":
                st.error(f"{finding.code.value}: {finding.message}")
            elif finding.severity.value == "warning":
                st.warning(f"{finding.code.value}: {finding.message}")
        if result.valid and result.series:
            state.set_capacity_series(result.series)
            st.success(
                f"Accepted {len(result.series)} series and "
                f"{sum(len(item.observations) for item in result.series)} observations."
            )
        elif not result.findings:
            st.error("No usable rows were found.")

    st.divider()
    st.subheader("Synthetic illustration data")
    st.caption(
        "The generator creates clearly labeled SYNTHETIC inputs from the stated "
        "formula and seed. It does not read a network or a measurement archive."
    )
    columns = st.columns(3)
    with columns[0]:
        series_id = st.text_input(
            "Series id", value=state.session_get(SYN_ID_KEY, "subscribers"), key=SYN_ID_KEY
        )
        unit_value = st.selectbox(
            "Unit",
            [item.value for item in SeriesUnit],
            index=0,
            key=SYN_UNIT_KEY,
        )
        base = st.number_input(
            "Base value",
            min_value=0.0,
            value=float(state.session_get(SYN_BASE_KEY, 100.0)),
            key=SYN_BASE_KEY,
        )
    with columns[1]:
        growth = st.number_input(
            "Growth rate per step",
            value=float(state.session_get(SYN_GROWTH_KEY, 0.02)),
            key=SYN_GROWTH_KEY,
        )
        seasonality = st.number_input(
            "Seasonality amplitude",
            min_value=0.0,
            value=float(state.session_get(SYN_SEASONALITY_KEY, 5.0)),
            key=SYN_SEASONALITY_KEY,
        )
        period = st.number_input(
            "Seasonal period",
            min_value=2,
            max_value=365,
            value=int(state.session_get(SYN_PERIOD_KEY, 7)),
            key=SYN_PERIOD_KEY,
        )
    with columns[2]:
        noise = st.number_input(
            "Noise sigma",
            min_value=0.0,
            value=float(state.session_get(SYN_NOISE_KEY, 1.0)),
            key=SYN_NOISE_KEY,
        )
        points = st.number_input(
            "Observations",
            min_value=8,
            max_value=2_000,
            value=int(state.session_get(SYN_POINTS_KEY, 12)),
            key=SYN_POINTS_KEY,
        )
        seed = st.number_input(
            "Seed",
            min_value=0,
            value=int(state.session_get(SYN_SEED_KEY, 42)),
            key=SYN_SEED_KEY,
        )
    if st.button("Generate SYNTHETIC series", key=SYN_GENERATE_KEY):
        try:
            spec = SyntheticSpec(
                series_id=series_id,
                unit=SeriesUnit(unit_value),
                base=base,
                growth_rate=growth,
                seasonality=seasonality,
                period=int(period),
                noise=noise,
                points=int(points),
                seed=int(seed),
            )
        except ValueError as error:
            st.error(str(error))
        else:
            generated = generate_synthetic(spec)
            _replace_series(generated.series_id, generated)
            st.success("Generated one SYNTHETIC series from the stated assumptions.")

    series = state.peek_capacity_series()
    st.subheader("Current input series")
    if not series:
        empty_state("No series has been accepted. Parse CSV rows or generate SYNTHETIC data.")
        return
    frame = pd.DataFrame(
        [
            {
                "series_id": item.series_id,
                "data_label": item.label,
                "unit": item.unit.value,
                "observations": len(item.observations),
                "first": item.observations[0].timestamp.isoformat()
                if item.observations
                else "",
                "last": item.observations[-1].timestamp.isoformat()
                if item.observations
                else "",
                "filled": item.fill_report.filled_points,
                "unfilled": item.fill_report.unfilled_points,
            }
            for item in series
        ],
        columns=[
            "series_id",
            "data_label",
            "unit",
            "observations",
            "first",
            "last",
            "filled",
            "unfilled",
        ],
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    st.caption(
        "SYNTHETIC rows are illustration inputs, not measurements. Filled points "
        "are listed explicitly and are never applied to leading or trailing gaps."
    )


def _render_forecast_tab() -> None:
    series = state.peek_capacity_series()
    if not series:
        empty_state("Add input series on the Data tab before building forecasts.")
        return

    allowed = min(allowed_horizon(item) for item in series)
    ceiling = min(allowed, MAX_CAPACITY_HORIZON_STEPS)
    horizon = st.number_input(
        "Forecast horizon (steps)",
        min_value=1,
        max_value=max(1, ceiling),
        value=min(2, max(1, ceiling)),
        key=HORIZON_KEY,
        help=(
            "The horizon cannot exceed half the shortest history or the capacity "
            "analysis ceiling. Oversized requests are refused by the engine."
        ),
    )
    moving_window = st.number_input(
        "Moving-average window",
        min_value=1,
        max_value=64,
        value=3,
        key=WINDOW_KEY,
    )
    seasonal_period = st.number_input(
        "Seasonal period",
        min_value=2,
        max_value=64,
        value=4,
        key=SEASON_KEY,
    )
    st.caption(
        f"Shortest history allows {allowed} projected steps; the capacity tab "
        f"evaluates at most {MAX_CAPACITY_HORIZON_STEPS} of them."
    )
    if st.button("Build forecasts", key=FORECAST_KEY):
        gap_policy = series[0].fill_report.policy.value
        try:
            run = cached_forecast_run(
                capacity_series_payload(series),
                int(horizon),
                int(moving_window),
                int(seasonal_period),
                gap_policy,
            )
        except ForecastError as error:
            st.error(str(error))
        else:
            state.set_capacity_forecast(run)
            st.success(f"Forecast {len(run.results)} series for {run.horizon} steps.")

    run = state.peek_capacity_forecast()
    if run is None:
        empty_state("No forecast has been built in this session.")
        return
    frame = pd.DataFrame(
        [
            {
                "series_id": result.series_id,
                "data_label": result.data_label,
                "unit": result.unit.value,
                "model": result.model.value,
                "mae": result.evaluation.metrics.mae,
                "naive_mae": result.naive_evaluation.metrics.mae,
                "beats_naive": result.beats_naive,
                "steps": len(result.forecast_points),
                "selection_note": result.selection_note,
            }
            for result in run.results
        ],
        columns=[
            "series_id",
            "data_label",
            "unit",
            "model",
            "mae",
            "naive_mae",
            "beats_naive",
            "steps",
            "selection_note",
        ],
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    point_frame = pd.DataFrame(
        [
            {
                "series_id": result.series_id,
                "data_label": result.data_label,
                "step": point.step,
                "timestamp": point.timestamp.isoformat(),
                "projected": point.value,
                "lower_approx": point.lower,
                "upper_approx": point.upper,
            }
            for result in run.results
            for point in result.forecast_points
        ],
        columns=[
            "series_id",
            "data_label",
            "step",
            "timestamp",
            "projected",
            "lower_approx",
            "upper_approx",
        ],
    )
    st.subheader("Modeled projection points")
    st.dataframe(point_frame, hide_index=True, width="stretch")
    st.caption(run.interval_note)


def _capacity_frame(run: CapacityRun) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "step": state.step,
                "timestamp": state.timestamp.isoformat(),
                "link_id": load.link_id,
                "capacity_mbps": load.capacity_mbps,
                "modeled_load_mbps": load.load_mbps,
                "utilization_percent": load.utilization_percent,
                "level": load.level.value,
            }
            for state in run.steps
            for load in state.state.links
        ],
        columns=[
            "step",
            "timestamp",
            "link_id",
            "capacity_mbps",
            "modeled_load_mbps",
            "utilization_percent",
            "level",
        ],
    )


def _render_results(run: CapacityRun) -> None:
    assumptions = run.bounds
    columns = st.columns(5)
    columns[0].metric("Baseline max utilization", f"{max((load.utilization_percent for load in run.baseline.links), default=0.0):.1f}%")
    columns[1].metric("Projected steps", len(run.steps))
    columns[2].metric("Crossings", len(run.crossings))
    columns[3].metric("Upgrades", len(run.recommendations))
    columns[4].metric("Cost proxy", f"{run.total_cost_delta:,.1f}")
    st.caption(
        f"Stop reason: {assumptions.stop_reason.value}. Evaluations used: "
        f"{assumptions.used_evaluations}/{assumptions.max_evaluations}. "
        f"Source twin fingerprint: {run.twin_fingerprint}."
    )
    st.caption(
        f"Data label: {', '.join(sorted({item.data_label for item in run.projection.demands})) or 'none'}. "
        f"Forecast model: {', '.join(sorted({item.model.value for item in run.projection.demands})) or 'none'}."
    )

    if run.projection.findings:
        st.subheader("Mapping findings")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "code": finding.code.value,
                        "series_id": finding.series_id,
                        "demand": finding.demand_name,
                        "message": finding.message,
                    }
                    for finding in run.projection.findings
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Projected link utilization")
    frame = _capacity_frame(run)
    if frame.empty:
        empty_state("No projected step produced a surviving link load.")
    else:
        st.dataframe(frame, hide_index=True, width="stretch")

    st.subheader("Ranked bottlenecks")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "link_id": item.link_id,
                    "peak_utilization_percent": item.peak_utilization_percent,
                    "peak_step": item.peak_step,
                    "headroom_mbps": item.headroom_mbps,
                    "bands_crossed": ", ".join(
                        sorted({crossing.level.value for crossing in item.crossings})
                    ),
                }
                for item in run.bottlenecks
            ],
            columns=[
                "link_id",
                "peak_utilization_percent",
                "peak_step",
                "headroom_mbps",
                "bands_crossed",
            ],
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Tier upgrade recommendations")
    if run.recommendations:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "link_id": item.link_id,
                        "current_mbps": item.current_capacity_mbps,
                        "target_tier": item.target_tier_name,
                        "target_mbps": item.target_capacity_mbps,
                        "projected_utilization_percent": item.projected_utilization_percent,
                        "cost_delta": item.cost_delta,
                        "cost_unit": item.cost_unit,
                    }
                    for item in run.recommendations
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        empty_state("No configured tier upgrade was required at the horizon end.")
    if run.gaps:
        st.warning(
            "No configured tier clears the warning threshold for: "
            + ", ".join(item.link_id for item in run.gaps)
            + ". Escalate these to the Optimization Center."
        )


def _render_capacity_tab() -> None:
    forecast = state.peek_capacity_forecast()
    if forecast is None:
        empty_state("Build a forecast on the Forecast tab before evaluating capacity.")
        return
    twin = state.get_twin()
    if twin is None or not twin.demands:
        empty_state(
            "The current twin has no traffic demands. Add them on the Simulation "
            "Lab page, then return here.",
            hint="Forecasts are mapped only onto demands that already exist in the twin.",
        )
        return

    demand_names = [demand.name for demand in twin.demands]
    st.subheader("Map forecasts to existing demands")
    st.caption(
        "Each series may replace the bandwidth of one existing demand. Unmapped "
        "series, unknown demand names, and missing user assumptions are reported "
        "as findings, not invented data."
    )
    mapping: dict[str, str] = {}
    for index, result in enumerate(forecast.results):
        choice = st.selectbox(
            f"Demand for {result.series_id}",
            [NONE_LABEL, *demand_names],
            key=f"{MAPPING_KEY_PREFIX}{index}",
        )
        if choice != NONE_LABEL:
            mapping[result.series_id] = choice
    per_user = st.number_input(
        "Bandwidth per user (Mbps)",
        min_value=0.0,
        value=float(state.session_get(PER_USER_KEY, 0.0)),
        key=PER_USER_KEY,
        help=(
            "Required only when a mapped series is measured in users. It is a "
            "user-supplied modeling assumption, not a measurement."
        ),
    )
    demand_mapping = DemandMapping(
        series_to_demand=mapping,
        per_user_mbps=per_user if per_user > 0 else None,
    )
    assumptions = SimulationAssumptions()
    cost = CostModel()
    st.caption(
        f"Congestion thresholds are warning {assumptions.thresholds.warning_percent:g}%, "
        f"critical {assumptions.thresholds.critical_percent:g}%, and overload "
        f"{assumptions.thresholds.overload_percent:g}%. Upgrade costs are proxies "
        "from the configured tiers, not vendor quotes."
    )
    if st.button("Evaluate projected demand", key=EVALUATE_KEY):
        try:
            run = cached_capacity_run(
                twin_payload(twin),
                forecast.model_dump_json(),
                demand_mapping.model_dump_json(),
                assumptions.model_dump_json(),
                cost.model_dump_json(),
                MAX_CAPACITY_EVALUATIONS,
                MAX_CAPACITY_RUNTIME_SECONDS,
            )
        except (CapacityError, ValueError) as error:
            st.error(str(error))
        else:
            state.add_capacity_run(run)
            st.success("Capacity analysis completed and retained for this session.")

    runs = state.peek_capacity_runs()
    if not runs:
        empty_state("No capacity analysis has been run in this session.")
        return
    labels = [
        f"{index + 1}. {len(run.steps)} steps | {len(run.recommendations)} upgrades"
        for index, run in enumerate(runs)
    ]
    selected = st.selectbox(
        "Retained capacity run",
        labels,
        index=len(labels) - 1,
        key=RUN_KEY,
    )
    _render_results(runs[labels.index(selected)])


def _render_downloads_tab() -> None:
    series = state.peek_capacity_series()
    forecast = state.peek_capacity_forecast()
    runs = state.peek_capacity_runs()
    if not series and forecast is None and not runs:
        empty_state("No capacity data has been produced in this session yet.")
        return
    if series:
        st.download_button(
            "Download input series as CSV",
            data=series_csv(series),
            file_name="capacity-input-series.csv",
            mime="text/csv",
            key=SERIES_DOWNLOAD_KEY,
        )
    if forecast is not None:
        st.download_button(
            "Download forecast points as CSV",
            data=forecast_csv(forecast),
            file_name="capacity-forecast.csv",
            mime="text/csv",
            key=FORECAST_CSV_DOWNLOAD_KEY,
        )
        st.download_button(
            "Download forecast run as JSON",
            data=forecast_json(forecast),
            file_name="capacity-forecast.json",
            mime="application/json",
            key=FORECAST_JSON_DOWNLOAD_KEY,
        )
    if runs:
        run = runs[-1]
        bottleneck_frame = pd.DataFrame(
            [
                {
                    "link_id": item.link_id,
                    "peak_utilization_percent": item.peak_utilization_percent,
                    "headroom_mbps": item.headroom_mbps,
                    "bands_crossed": ", ".join(
                        sorted({crossing.level.value for crossing in item.crossings})
                    ),
                }
                for item in run.bottlenecks
            ]
        )
        upgrade_frame = pd.DataFrame(
            [
                {
                    "link_id": item.link_id,
                    "target_tier": item.target_tier_name,
                    "target_mbps": item.target_capacity_mbps,
                    "cost_delta": item.cost_delta,
                    "cost_unit": item.cost_unit,
                }
                for item in run.recommendations
            ]
        )
        st.download_button(
            "Download bottlenecks as CSV",
            data=csv_bytes(bottleneck_frame),
            file_name="capacity-bottlenecks.csv",
            mime="text/csv",
            key=BOTTLENECK_DOWNLOAD_KEY,
        )
        st.download_button(
            "Download upgrades as CSV",
            data=csv_bytes(upgrade_frame),
            file_name="capacity-upgrades.csv",
            mime="text/csv",
            key=UPGRADE_DOWNLOAD_KEY,
        )
        st.download_button(
            "Download capacity run as JSON",
            data=(run.model_dump_json(indent=2) + "\n").encode("utf-8"),
            file_name="capacity-run.json",
            mime="application/json",
            key=RUN_JSON_DOWNLOAD_KEY,
        )
    st.caption(
        "Downloads are generated in memory and carry the provenance label of "
        "every input series. No file is written to disk."
    )


def render() -> None:
    """Render the four-tab Capacity Planning workflow."""
    page_header(
        "Capacity Planning",
        "Forecast stated or synthetic demand, evaluate it on copies of the "
        "current twin, and review bounded tier-upgrade recommendations.",
    )
    model_estimate_note(MODEL_NOTE, title="Model scope")
    twin = state.get_twin()
    if twin is None or not twin.topology.devices:
        empty_state(
            "No digital twin with a topology is loaded. Open the Topology "
            "Editor to create, generate, or import one, then return here.",
            title="Digital twin required",
            hint="Capacity results are evaluated only against a stored twin revision.",
        )
        return

    data_tab, forecast_tab, capacity_tab, downloads_tab = st.tabs(
        ["Data", "Forecast", "Capacity", "Downloads"]
    )
    with data_tab:
        _render_data_tab()
    with forecast_tab:
        _render_forecast_tab()
    with capacity_tab:
        _render_capacity_tab()
    with downloads_tab:
        _render_downloads_tab()


__all__ = ["render"]
