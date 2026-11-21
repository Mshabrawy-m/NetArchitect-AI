"""Content-keyed caches for pure, expensive computations.

Every cached function is pure: its result depends only on the arguments it
receives. Streamlit's ``cache_data`` hashes those arguments, so a cache entry is
reused on reruns while the underlying twin and selected sources stay identical
and is bypassed as soon as any of them changes.

The caches are keyed by the canonical twin JSON *and* the twin fingerprint.
The fingerprint alone is already unique per twin revision; passing the JSON as
well lets the cached function rebuild the model without touching session state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import streamlit as st

from capacity import CapacityRun, DemandMapping, evaluate_capacity
from digital_twin import DigitalTwin, to_json
from forecasting import (
    ForecastRun,
    GapPolicy,
    TimeSeries,
    forecast_series,
)
from optimization import (
    CostModel,
    OptimizationRun,
    ParetoReranking,
    SensitivityReport,
)
from security import FlowRequest, SecurityAnalysis, SecurityModel, analyze_design
from services.validation import DesignHealth, build_design_health
from simulation import (
    FailureSweepResult,
    RoutingModeComparison,
    ScenarioRun,
    SimulationAssumptions,
    twin_fingerprint,
)

if TYPE_CHECKING:
    from services.copilot import DecisionLog
    from services.reporting import ReportDocument

CACHE_ENTRIES = 8


def twin_payload(twin: DigitalTwin) -> str:
    """Return the compact canonical JSON used as a cache payload."""
    return to_json(twin, indent=None)


def twin_cache_key(twin: DigitalTwin) -> str:
    """Return the stable content key for one twin revision."""
    return twin_fingerprint(twin)


def source_payload(
    source: (
        ScenarioRun
        | OptimizationRun
        | FailureSweepResult
        | RoutingModeComparison
        | SensitivityReport
        | ParetoReranking
        | None
    ),
) -> str:
    """Return canonical JSON for an optional cacheable report source.

    ``WorkflowState`` is deliberately absent: it holds a live baseline accessor
    and is not serializable, so a workflow-backed report is built directly
    instead of entering a content-keyed cache.
    """
    if source is None:
        return ""
    return source.model_dump_json()


def decisions_payload(decisions: DecisionLog | None) -> str:
    """Return canonical JSON for the bounded session decision log."""
    return decisions.to_json() if decisions is not None else ""


def capacity_series_payload(series: tuple[TimeSeries, ...]) -> str:
    """Return canonical JSON for the bounded capacity input series."""
    return json.dumps(
        [json.loads(item.model_dump_json()) for item in series],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def capacity_source_payload(source: CapacityRun | None) -> str:
    """Return canonical JSON for an optional capacity report source."""
    return source.model_dump_json() if source is not None else ""


def security_flows_payload(flows: tuple[FlowRequest, ...] | list[FlowRequest]) -> str:
    """Return canonical JSON for bounded modeled security flow checks."""
    return json.dumps(
        [json.loads(item.model_dump_json()) for item in flows],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_security_analysis(
    twin_payload: str,
    model_payload: str,
    flows_payload: str,
) -> SecurityAnalysis:
    """Build one deterministic security assessment per content-keyed input set."""
    return analyze_design(
        DigitalTwin.model_validate_json(twin_payload),
        model=SecurityModel.model_validate_json(model_payload),
        flows=tuple(
            FlowRequest.model_validate_json(json.dumps(item))
            for item in json.loads(flows_payload)
        ),
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_forecast_run(
    series_payload: str,
    horizon: int,
    moving_window: int,
    seasonal_period: int,
    gap_policy: str,
) -> ForecastRun:
    """Build one forecast run per content keyed input set."""
    items = json.loads(series_payload)
    series = tuple(TimeSeries.model_validate_json(json.dumps(item)) for item in items)
    results = tuple(
        forecast_series(
            item,
            horizon=horizon,
            moving_window=moving_window,
            seasonal_period=seasonal_period,
        )
        for item in series
    )
    return ForecastRun(
        results=results,
        horizon=horizon,
        gap_policy=GapPolicy(gap_policy),
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_capacity_run(
    twin_payload: str,
    forecast_payload: str,
    mapping_payload: str,
    assumptions_payload: str,
    cost_payload: str,
    max_evaluations: int,
    max_runtime_seconds: float,
) -> CapacityRun:
    """Evaluate one bounded capacity run per content keyed input set."""
    return evaluate_capacity(
        DigitalTwin.model_validate_json(twin_payload),
        ForecastRun.model_validate_json(forecast_payload),
        DemandMapping.model_validate_json(mapping_payload),
        assumptions=SimulationAssumptions.model_validate_json(assumptions_payload),
        cost_model=CostModel.model_validate_json(cost_payload),
        max_evaluations=max_evaluations,
        max_runtime_seconds=max_runtime_seconds,
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_design_health(
    twin_payload: str,
    include_expensive: bool,
    constraints: tuple[str, ...] = (),
) -> DesignHealth:
    """Build the design-health report once per twin revision and options."""
    return build_design_health(
        DigitalTwin.model_validate_json(twin_payload),
        include_expensive=include_expensive,
        constraints=constraints,
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_report(
    twin_payload: str,
    scenario_payload: str,
    optimization_payload: str,
    generated_at_iso: str,
    title: str = "",
    capacity_payload: str = "",
    optimization_source_fingerprint: str = "",
    sweep_payload: str = "",
    mode_comparison_payload: str = "",
    sensitivity_payload: str = "",
    reranking_payload: str = "",
    sensitivity_source_fingerprint: str = "",
    rerank_source_fingerprint: str = "",
    decisions_json: str = "",
) -> ReportDocument:
    """Build one report document once per twin revision and source selection."""
    from services.copilot import DecisionLog
    from services.reporting import ReportSources, build_report

    return build_report(
        ReportSources(
            twin=DigitalTwin.model_validate_json(twin_payload),
            scenario_run=(
                ScenarioRun.model_validate_json(scenario_payload)
                if scenario_payload
                else None
            ),
            optimization_run=(
                OptimizationRun.model_validate_json(optimization_payload)
                if optimization_payload
                else None
            ),
            capacity_run=(
                CapacityRun.model_validate_json(capacity_payload)
                if capacity_payload
                else None
            ),
            failure_sweep=(
                FailureSweepResult.model_validate_json(sweep_payload)
                if sweep_payload
                else None
            ),
            mode_comparison=(
                RoutingModeComparison.model_validate_json(mode_comparison_payload)
                if mode_comparison_payload
                else None
            ),
            sensitivity_report=(
                SensitivityReport.model_validate_json(sensitivity_payload)
                if sensitivity_payload
                else None
            ),
            reranking=(
                ParetoReranking.model_validate_json(reranking_payload)
                if reranking_payload
                else None
            ),
            decisions=(
                DecisionLog.from_json(decisions_json) if decisions_json else None
            ),
            optimization_source_fingerprint=optimization_source_fingerprint,
            sensitivity_source_fingerprint=sensitivity_source_fingerprint,
            rerank_source_fingerprint=rerank_source_fingerprint,
            generated_at=datetime.fromisoformat(generated_at_iso),
            title=title,
        )
    )


@dataclass(frozen=True)
class ExportBundle:
    """All in-memory report exports for one document and twin revision."""

    pdf: bytes
    markdown: bytes
    json: bytes
    csv: bytes
    config: bytes
    warnings: tuple[str, ...] = ()


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_exports(document_payload: str, twin_payload: str) -> ExportBundle:
    """Build every export once per filtered document and twin revision."""
    from services.export import (
        pdf_warnings,
        to_config_bundle,
        to_csv_bundle,
        to_markdown,
        to_pdf,
    )
    from services.export import (
        to_json as document_to_json,
    )
    from services.reporting import ReportDocument

    document = ReportDocument.model_validate_json(document_payload)
    return ExportBundle(
        pdf=to_pdf(document),
        markdown=to_markdown(document),
        json=document_to_json(document),
        csv=to_csv_bundle(document),
        config=to_config_bundle(DigitalTwin.model_validate_json(twin_payload)),
        warnings=pdf_warnings(document),
    )


__all__ = [
    "ExportBundle",
    "cached_capacity_run",
    "cached_design_health",
    "cached_exports",
    "cached_forecast_run",
    "cached_report",
    "cached_security_analysis",
    "capacity_series_payload",
    "capacity_source_payload",
    "security_flows_payload",
    "source_payload",
    "twin_cache_key",
    "twin_payload",
]
