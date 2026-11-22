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

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

import streamlit as st

from capacity import CapacityRun, DemandMapping, evaluate_capacity
from core.schemas.validation import Finding
from digital_twin import DigitalTwin, to_json
from forecasting import (
    ForecastRun,
    GapPolicy,
    TimeSeries,
    forecast_series,
)
from network.addressing.dual_stack import validate_dual_stack
from network.addressing.nat import analyze_nat_plan
from network.l2.switching import analyze_l2_design
from network.qos.review import qos_findings
from network.routing.ha import analyze_ha_groups
from network.routing.ospf import analyze_ospf_design
from network.wan.planning import analyze_wan_design
from network.wireless.planning import analyze_wireless_design
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
from simulation.evaluator import evaluate
from simulation.models import RoutingMode

if TYPE_CHECKING:
    from services.copilot import DecisionLog
    from services.reporting import ReportDocument

CACHE_ENTRIES = 8

# Fixed, bounded review sections. Each section is one cached slice, so a full
# review uses exactly four entries regardless of topology size.
L2_REVIEW_SECTIONS: tuple[str, ...] = ("l2", "wan", "wireless", "qos")
L2_REVIEW_SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "l2": ("l2_loops", "l2_blocked_links", "l2_bundles", "l2_findings"),
    "wan": (
        "wan_links",
        "wan_site_ids",
        "wan_total_monthly_cost_proxy",
        "wan_findings",
    ),
    "wireless": (
        "wireless_areas",
        "wireless_total_aps",
        "wireless_total_uplink_mbps",
        "wireless_findings",
    ),
    "qos": ("qos_caps", "qos_default_class", "qos_findings"),
}


@dataclass(frozen=True)
class L2DesignReview:
    """Small, serializable summary of one bounded L2/WAN/wireless/QoS review.

    A cached slice fills only its own section fields. The UI merges the four
    slices into one ``sections=L2_REVIEW_SECTIONS`` result, so every summary is
    built from immutable tuples and needs no live engine object.
    """

    twin_version: str
    sections: tuple[str, ...] = ()
    status: str = "complete"
    l2_loops: tuple[tuple[int, str | None, int, tuple[str, ...]], ...] = ()
    l2_blocked_links: tuple[str, ...] = ()
    l2_bundles: tuple[tuple[str, float, bool, tuple[str, ...]], ...] = ()
    l2_findings: tuple[tuple[str, str, str], ...] = ()
    wan_links: tuple[tuple[str, str, str, str, float, float, float], ...] = ()
    wan_site_ids: tuple[str, ...] = ()
    wan_total_monthly_cost_proxy: float = 0.0
    wan_findings: tuple[tuple[str, str, str], ...] = ()
    wireless_areas: tuple[tuple[str, str, int, int, int, str, float], ...] = ()
    wireless_total_aps: int = 0
    wireless_total_uplink_mbps: float = 0.0
    wireless_findings: tuple[tuple[str, str, str], ...] = ()
    qos_caps: tuple[tuple[str, str, float], ...] = ()
    qos_default_class: str = ""
    qos_findings: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class L3DesignReview:
    """Small, serializable summary of the four optional L3 design models."""

    twin_version: str
    dual_stack_findings: tuple[tuple[str, str], ...] = ()
    nat_sizings: tuple[tuple[str, str, int, int, int, int, int, int], ...] = ()
    nat_findings: tuple[tuple[str, str], ...] = ()
    ospf_routers: tuple[tuple[str, tuple[int, ...], str], ...] = ()
    ospf_link_costs: tuple[tuple[str, float, float, float, str], ...] = ()
    ospf_findings: tuple[tuple[str, str], ...] = ()
    ha_active: tuple[tuple[str, str], ...] = ()
    ha_findings: tuple[tuple[str, str], ...] = ()


def twin_payload(twin: DigitalTwin) -> str:
    """Return the compact canonical JSON used as a cache payload."""
    return to_json(twin, indent=None)


def twin_cache_key(twin: DigitalTwin) -> str:
    """Return the stable content key for one twin revision."""
    return twin_fingerprint(twin)


def l2_review_key(twin: DigitalTwin) -> str:
    """Return one session/cache identity for a twin revision.

    The key combines the fingerprint with a digest of the canonical twin JSON,
    so either a fingerprint revision or any additive design field invalidates a
    stored review result.
    """
    payload = twin_payload(twin)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{twin_cache_key(twin)}:{digest}"


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
def cached_l3_design_review(
    twin_payload: str,
    fingerprint: str = "",
) -> L3DesignReview:
    """Review optional L3 design fields once per twin revision.

    The cache is bounded and keyed by the canonical twin JSON plus its
    fingerprint. It returns only derived design-rule summaries; no packet or
    device behavior is represented.
    """
    twin = DigitalTwin.model_validate_json(twin_payload)

    def findings(items: Sequence[Finding]) -> tuple[tuple[str, str], ...]:
        return tuple((item.code, item.explanation) for item in items)

    dual_stack = ()
    if twin.ipv6_plan is not None:
        dual_stack = validate_dual_stack(
            twin.ipv6_plan.block,
            twin.ipv6_plan,
            addressing=twin.addressing,
        )

    nat_analysis = analyze_nat_plan(twin.nat_plan) if twin.nat_plan else None
    ospf_analysis = (
        analyze_ospf_design(twin.ospf_design, twin.topology)
        if twin.ospf_design is not None
        else None
    )
    ha_analysis = (
        analyze_ha_groups(
            twin.ha_groups,
            twin.topology,
            vlan_plan=twin.vlan_plan,
        )
        if twin.ha_groups
        else None
    )

    return L3DesignReview(
        twin_version=fingerprint,
        dual_stack_findings=findings(dual_stack),
        nat_sizings=tuple(
            (
                item.rule_id,
                item.nat_type,
                item.inside_hosts,
                item.pool_addresses,
                item.required_addresses,
                item.required_sessions,
                item.session_capacity,
                item.usable_ports_per_address,
            )
            for item in (nat_analysis.sizings if nat_analysis else ())
        ),
        nat_findings=findings(nat_analysis.findings if nat_analysis else ()),
        ospf_routers=tuple(
            (item.device_id, item.area_ids, item.role.value)
            for item in (ospf_analysis.routers if ospf_analysis else ())
        ),
        ospf_link_costs=tuple(
            (
                item.link_id,
                item.capacity_mbps,
                item.base_cost,
                item.effective_cost,
                item.formula,
            )
            for item in (ospf_analysis.link_costs if ospf_analysis else ())
        ),
        ospf_findings=findings(ospf_analysis.findings if ospf_analysis else ()),
        ha_active=tuple(
            (group.id, ha_analysis.active_members.get(group.id, "none"))
            for group in twin.ha_groups
        )
        if ha_analysis
        else (),
        ha_findings=findings(ha_analysis.findings if ha_analysis else ()),
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def _cached_l2_design_review_slice(
    twin_payload: str,
    fingerprint: str = "",
    sections: tuple[str, ...] = L2_REVIEW_SECTIONS,
) -> L2DesignReview:
    """Review one bounded slice of the W1-W4 design models per twin revision.

    The cache is bounded and keyed by canonical twin JSON, fingerprint, and
    section selection. Each call rebuilds its slice from the payload without
    touching session state, so a changed twin can never reuse a stale result.
    """
    requested = tuple(dict.fromkeys(sections)) if sections else L2_REVIEW_SECTIONS
    unknown = set(requested).difference(L2_REVIEW_SECTIONS)
    if unknown:
        raise ValueError(f"Unknown L2 review sections: {sorted(unknown)}")
    twin = DigitalTwin.model_validate_json(twin_payload)

    def summary(items: Sequence[Finding]) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (item.severity.value, item.code, item.explanation) for item in items
        )

    l2_loops: tuple[tuple[int, str | None, int, tuple[str, ...]], ...] = ()
    l2_blocked_links: tuple[str, ...] = ()
    l2_bundles: tuple[tuple[str, float, bool, tuple[str, ...]], ...] = ()
    l2_findings: tuple[tuple[str, str, str], ...] = ()
    if "l2" in requested:
        l2 = analyze_l2_design(twin)
        l2_loops = tuple(
            (
                loop.vlan_id,
                loop.root_bridge,
                loop.cycle_count,
                loop.blocked_link_ids,
            )
            for loop in l2.loops
        )
        l2_blocked_links = l2.blocked_link_ids
        l2_bundles = tuple(
            (
                bundle.bundle_id,
                bundle.capacity_mbps,
                bundle.down,
                bundle.member_link_ids,
            )
            for bundle in l2.bundles
        )
        l2_findings = summary(l2.findings)

    wan_links: tuple[tuple[str, str, str, str, float, float, float], ...] = ()
    wan_site_ids: tuple[str, ...] = ()
    wan_total = 0.0
    wan_findings: tuple[tuple[str, str, str], ...] = ()
    if "wan" in requested:
        wan = analyze_wan_design(twin, design=twin.wan_design, include_expensive=False)
        wan_links = tuple(
            (
                link.link_id,
                link.source_site,
                link.target_site,
                link.wan_type.value if link.wan_type is not None else "",
                link.capacity_mbps,
                link.monthly_cost_proxy,
                link.latency_ms,
            )
            for link in wan.links
        )
        wan_site_ids = wan.site_ids
        wan_total = wan.total_monthly_cost_proxy
        wan_findings = summary(wan.findings)

    wireless_areas: tuple[tuple[str, str, int, int, int, str, float], ...] = ()
    wireless_total_aps = 0
    wireless_total_uplink = 0.0
    wireless_findings: tuple[tuple[str, str, str], ...] = ()
    if "wireless" in requested:
        wireless = analyze_wireless_design(twin.wireless_design)
        wireless_areas = tuple(
            (
                plan.area_id,
                plan.area_name,
                plan.effective_clients,
                plan.capacity_ap_count,
                plan.recommended_ap_count,
                plan.binding_constraint,
                plan.uplink_required_mbps,
            )
            for plan in wireless.plans
        )
        wireless_total_aps = wireless.total_recommended_aps
        wireless_total_uplink = wireless.total_uplink_required_mbps
        wireless_findings = summary(wireless.findings)

    qos_caps: tuple[tuple[str, str, float], ...] = ()
    qos_default_class = ""
    qos_findings_summary: tuple[tuple[str, str, str], ...] = ()
    if "qos" in requested:
        if twin.qos_design is not None:
            qos_default_class = twin.qos_design.default_class.value
            qos_caps = tuple(
                (cap.link_id, cap.traffic_class.value, cap.share_cap)
                for cap in twin.qos_design.class_share_caps
            )
        state = evaluate(
            twin,
            SimulationAssumptions(
                routing_mode=RoutingMode.capacity_aware,
                enable_strict_priority_qos=True,
            ),
        )
        qos_findings_summary = summary(
            qos_findings(twin, state, design=twin.qos_design)
        )

    return L2DesignReview(
        twin_version=fingerprint,
        sections=requested,
        l2_loops=l2_loops,
        l2_blocked_links=l2_blocked_links,
        l2_bundles=l2_bundles,
        l2_findings=l2_findings,
        wan_links=wan_links,
        wan_site_ids=wan_site_ids,
        wan_total_monthly_cost_proxy=wan_total,
        wan_findings=wan_findings,
        wireless_areas=wireless_areas,
        wireless_total_aps=wireless_total_aps,
        wireless_total_uplink_mbps=wireless_total_uplink,
        wireless_findings=wireless_findings,
        qos_caps=qos_caps,
        qos_default_class=qos_default_class,
        qos_findings=qos_findings_summary,
    )


def cached_l2_design_review(
    twin_payload: str,
    fingerprint: str = "",
    sections: tuple[str, ...] = L2_REVIEW_SECTIONS,
) -> L2DesignReview:
    """Merge independently cached W1-W4 slices for one twin revision.

    Each section is cached separately, so a reordered or smaller subset reuses
    the same bounded entries instead of creating a new whole-combination entry.
    The returned review preserves the requested order while every field still
    comes from a fingerprint-keyed slice.
    """
    requested = tuple(dict.fromkeys(sections)) if sections else L2_REVIEW_SECTIONS
    unknown = set(requested).difference(L2_REVIEW_SECTIONS)
    if unknown:
        raise ValueError(f"Unknown L2 review sections: {sorted(unknown)}")

    result = L2DesignReview(
        twin_version=fingerprint,
        sections=requested,
        status="complete",
    )
    updates: dict[str, object] = {}
    for section in requested:
        piece = _cached_l2_design_review_slice(twin_payload, fingerprint, (section,))
        for field in L2_REVIEW_SECTION_FIELDS.get(section, ()):
            updates[field] = getattr(piece, field)
    return replace(result, **updates)


def _clear_cached_l2_design_review() -> None:
    """Drop all bounded L2 review slices (test and cache-reset helper)."""
    _cached_l2_design_review_slice.clear()


cached_l2_design_review.clear = _clear_cached_l2_design_review  # type: ignore[attr-defined]


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_security_analysis(
    twin_payload: str,
    model_payload: str,
    flows_payload: str,
    fingerprint: str = "",
) -> SecurityAnalysis:
    """Build one assessment per bounded, fingerprint-keyed content set.

    The canonical payloads rebuild the model without touching session state.
    The fingerprint is part of the cache key so a twin revision cannot reuse a
    result from a different session revision even if its JSON ever differs.
    """
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
    "L2_REVIEW_SECTIONS",
    "ExportBundle",
    "L2DesignReview",
    "L3DesignReview",
    "cached_capacity_run",
    "cached_design_health",
    "cached_exports",
    "cached_forecast_run",
    "cached_l2_design_review",
    "cached_l3_design_review",
    "cached_report",
    "cached_security_analysis",
    "capacity_series_payload",
    "capacity_source_payload",
    "l2_review_key",
    "security_flows_payload",
    "source_payload",
    "twin_cache_key",
    "twin_payload",
]
