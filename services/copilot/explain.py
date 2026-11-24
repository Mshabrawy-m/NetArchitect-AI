"""C3: deterministic explanations with optional, audited AI prose.

Every explanation starts from a typed request built by deterministic Python from
an already-computed engineering object. The deterministic paragraph is always
present and carries the computed values. An optional language model may add one
short advisory paragraph, which is audited for invented numbers, out-of-scope
content, and any attempt to state a verdict, level, rank, or decision.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from config.limits import (
    MAX_COPILOT_EXPLANATION_CHARS,
    MAX_LLM_REPAIR_RETRIES,
)
from core.exceptions import (
    LLMError,
    LLMMissingKeyError,
    OversizedInputError,
    ensure_llm_status,
)
from core.inputs import reject_unsafe_text
from core.schemas.validation import Finding
from digital_twin import DigitalTwin
from network.l2.models import L2Design
from network.l2.switching import L2Analysis
from network.qos.admission import ADMISSION_NOTE, QosAdmissionPlan
from network.qos.models import TRAFFIC_CLASS_PRIORITY, QosDesign
from network.routing.ha import HaAnalysis, HaGroup
from network.routing.ospf import OspfAnalysis, OspfDesign
from network.wan.models import WanDesign
from network.wan.planning import LATENCY_NOTE, MONTHLY_COST_NOTE, WanAnalysis
from network.wireless.models import WirelessDesign
from network.wireless.planning import (
    CAPACITY_FORMULA,
    COVERAGE_FORMULA,
    NO_RF_NOTE,
    UPLINK_FORMULA,
    WirelessAnalysis,
)
from optimization import (
    CandidateEvaluation,
    CandidateRecord,
    OptimizationSettings,
    candidate_changes,
)
from security import BlastRadius, SecurityFinding, SegmentationScore
from services.llm import EXPLAIN_RESULT, LLMProvider, PromptSpec
from simulation import DemandEvaluation, ScenarioRun, SimulationAssumptions

from .cache import CacheKey, CopilotCache, build_key
from .llm_bridge import request_structured
from .models import (
    AIExplanationDraft,
    ExplanationResult,
    ExplanationTarget,
    audit_prose,
)
from .trace import PromptTrace

# The shared security-agent vocabulary covers attack/scan content. These terms
# close the C3-specific gap: model prose must never state a verdict, level, or
# decision, even when those values exist in the deterministic paragraph.
_EXTRA_FORBIDDEN_TERMS: tuple[str, ...] = (
    "verdict",
    "severity",
    "risk level",
    "congestion level",
    "critical",
    "overloaded",
    "warning",
    "passed",
    "rejected",
    "approved",
    "recommend",
    "recommendation",
    "rank",
    "score",
    "best",
    "optimal",
    "ignore previous",
    "system prompt",
    "tool call",
    "api key",
)

_AI_REJECTION = (
    "The AI explanation was rejected by the deterministic prose audit; only "
    "the computed explanation is shown."
)


class ExplanationRequest(BaseModel):
    """A bounded, deterministic explanation request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: ExplanationTarget
    target_id: str = Field(min_length=1, max_length=200)
    deterministic_text: str = Field(
        min_length=1,
        max_length=MAX_COPILOT_EXPLANATION_CHARS,
    )
    facts: str = Field(
        min_length=1,
        max_length=MAX_COPILOT_EXPLANATION_CHARS,
        description="Already-computed facts the AI paragraph may refer to.",
    )


def _number(value: float) -> str:
    return f"{value:g}"


def _path(demand: DemandEvaluation) -> str:
    return " -> ".join(demand.path_device_ids) if demand.path_device_ids else "none"


def route_request(
    demand: DemandEvaluation,
    *,
    assumptions: SimulationAssumptions,
) -> ExplanationRequest:
    """Build a route explanation from one deterministic demand evaluation."""
    detail = [
        (
            f"Demand {demand.name} from {demand.source} to {demand.destination} "
            f"requested {_number(demand.bandwidth_mbps)} Mbps."
        ),
        f"Routing mode: {assumptions.routing_mode.value}.",
    ]
    if demand.served:
        detail.append(
            f"The modeled path is {_path(demand)} over links "
            f"{', '.join(demand.link_ids) or 'none'} with "
            f"{demand.hop_count} hops and total cost "
            f"{_number(demand.total_cost)}."
        )
        if demand.latency_ms is not None:
            detail.append(f"Estimated latency is {_number(demand.latency_ms)} ms.")
    else:
        detail.append(f"No path was admitted. Computed reason: {demand.reason}")
        if demand.bottleneck_link_id:
            detail.append(
                f"The bottleneck link was {demand.bottleneck_link_id} with "
                f"{_number(demand.bottleneck_available_mbps or 0.0)} Mbps "
                "residual capacity."
            )
    if demand.splits:
        shares = ", ".join(
            f"{split.share_percent:g}% on {_path(split.path_device_ids)}"
            for split in demand.splits
        )
        detail.append(f"The split shares were: {shares}.")

    facts = (
        f"Demand {demand.name}, source {demand.source}, destination "
        f"{demand.destination}, requested {_number(demand.bandwidth_mbps)} Mbps, "
        f"path {_path(demand)}, links {', '.join(demand.link_ids) or 'none'}, "
        f"hops {demand.hop_count}, total cost {_number(demand.total_cost)}"
    )
    if demand.latency_ms is not None:
        facts += f", latency {_number(demand.latency_ms)} ms"
    if demand.bottleneck_link_id:
        facts += (
            f", bottleneck {demand.bottleneck_link_id}, residual "
            f"{_number(demand.bottleneck_available_mbps or 0.0)} Mbps"
        )
    return ExplanationRequest(
        target=ExplanationTarget.route,
        target_id=demand.name,
        deterministic_text=" ".join(detail),
        facts=facts,
    )


def finding_request(finding: SecurityFinding) -> ExplanationRequest:
    """Build a finding explanation from one deterministic security finding."""
    entities = ", ".join(finding.affected_entities) or "none"
    evidence = "; ".join(finding.evidence) or "none"
    deterministic = (
        f"Finding {finding.code} concerns {entities}. "
        f"{finding.explanation} Evidence: {evidence}. "
        f"Deterministic remediation: {finding.remediation}"
    )
    facts = (
        f"Finding {finding.code}, affected entities {entities}, "
        f"evidence {evidence}, explanation {finding.explanation}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.finding,
        target_id=finding.code,
        deterministic_text=deterministic,
        facts=facts,
    )


def blast_radius_request(radius: BlastRadius) -> ExplanationRequest:
    """Build a bounded blast-radius explanation from one S1 result."""
    direct = ", ".join(radius.directly_reachable) or "none"
    closure = ", ".join(radius.closure_zones) or "none"
    deterministic = (
        f"Modeled policy reachability from {radius.origin_zone} "
        f"({radius.origin_zone_type.value}) directly includes {direct}. Within "
        f"the bounded {radius.hop_count}-hop closure, reachable zones are "
        f"{closure}. Highest designer-set criticality reached is "
        f"{radius.max_criticality_reached}; exposure flag is "
        f"{str(radius.exposure).lower()}. This is a policy-reachability model, "
        "not an attack path or exploit chain."
    )
    facts = (
        f"Origin {radius.origin_zone}, direct zones {direct}, closure zones "
        f"{closure}, hops {radius.hop_count}, highest criticality "
        f"{radius.max_criticality_reached}, exposure "
        f"{str(radius.exposure).lower()}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.blast_radius,
        target_id=radius.origin_zone,
        deterministic_text=deterministic,
        facts=facts,
    )


def segmentation_score_request(score: SegmentationScore) -> ExplanationRequest:
    """Build a hand-checkable segmentation-score explanation from one S2 result."""
    inputs = "; ".join(
        f"{item.name} subscore {_number(item.subscore)} x weight "
        f"{_number(item.weight)} = {_number(item.contribution)}"
        for item in score.inputs
    )
    deterministic = (
        f"Modeled segmentation score is {score.score}/100. Weighted inputs: "
        f"{inputs}. {score.formula}"
    )
    facts = (
        f"Score {score.score}, weighted inputs {inputs}, formula {score.formula}, "
        f"allowed {score.allowed_count}, needed {score.needed_count}, excess "
        f"{score.excess_count}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.segmentation_score,
        target_id="segmentation",
        deterministic_text=deterministic,
        facts=facts,
    )


def simulation_request(run: ScenarioRun) -> ExplanationRequest:
    """Build a scenario-result explanation from one deterministic run."""
    comparison = run.comparison
    scenario = run.scenario
    deterministic = (
        f"Scenario {scenario.name} ({scenario.type.value}) compared "
        f"{run.baseline_state.served_demand_count} of "
        f"{run.baseline_state.demand_count} served demands at baseline with "
        f"{run.scenario_state.served_demand_count} in the scenario. "
        f"Maximum utilization changed by "
        f"{_number(comparison.max_utilization_delta_percent)} percentage points; "
        f"overloaded links changed by {comparison.overloaded_link_delta}; "
        f"disconnected devices changed by {comparison.disconnected_device_delta}. "
        f"{comparison.summary}"
    )
    facts = (
        f"Baseline served {run.baseline_state.served_demand_count} of "
        f"{run.baseline_state.demand_count}, scenario served "
        f"{run.scenario_state.served_demand_count}, maximum utilization delta "
        f"{_number(comparison.max_utilization_delta_percent)} percentage points, "
        f"overloaded link delta {comparison.overloaded_link_delta}, disconnected "
        f"device delta {comparison.disconnected_device_delta}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.simulation,
        target_id=scenario.id,
        deterministic_text=deterministic,
        facts=facts,
    )


def optimization_request(
    record: CandidateRecord,
    *,
    twin: DigitalTwin,
    settings: OptimizationSettings,
    baseline: CandidateEvaluation | None = None,
) -> ExplanationRequest:
    """Build a candidate explanation from one deterministic evaluation."""
    evaluation = record.evaluation
    metrics = evaluation.metrics
    changes = (
        candidate_changes(twin, evaluation.candidate, settings)
        or ("no topology changes",)
    )
    change_text = "; ".join(changes)
    objectives = "; ".join(
        f"{item.label} {_number(item.raw_value)} {item.unit}".strip()
        for item in evaluation.objectives
    )
    deterministic = (
        f"Candidate {evaluation.candidate_hash[:12]} applies {change_text}. "
        f"Modeled served ratio {_number(metrics.served_demand_ratio)}, maximum "
        f"utilization {_number(metrics.max_utilization_percent)} percent, and "
        f"cost proxy {_number(metrics.infrastructure_cost_proxy)}. "
        f"Objective values: {objectives or 'none'}."
    )
    if baseline is not None:
        base_metrics = baseline.metrics
        deterministic += (
            " Baseline served ratio "
            f"{_number(base_metrics.served_demand_ratio)}, maximum utilization "
            f"{_number(base_metrics.max_utilization_percent)} percent, and cost "
            f"proxy {_number(base_metrics.infrastructure_cost_proxy)}."
        )
    facts = (
        f"Candidate {evaluation.candidate_hash[:12]}, changes {change_text}, served "
        f"ratio {_number(metrics.served_demand_ratio)}, maximum utilization "
        f"{_number(metrics.max_utilization_percent)} percent, cost proxy "
        f"{_number(metrics.infrastructure_cost_proxy)}, objectives {objectives}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.optimization,
        target_id=evaluation.candidate_hash[:16],
        deterministic_text=deterministic,
        facts=facts,
    )


def ospf_design_request(
    design: OspfDesign,
    analysis: OspfAnalysis,
) -> ExplanationRequest:
    """Build a deterministic OSPF-area explanation from derived design data."""
    roles = Counter(router.role.value for router in analysis.routers)
    counts = ", ".join(
        f"{role} {roles[role]}"
        for role in ("internal", "abr", "asbr")
        if roles[role]
    ) or "none"
    costs = ", ".join(
        f"{item.link_id} {_number(item.effective_cost)}"
        for item in analysis.link_costs
    ) or "none"
    deterministic = (
        "Modeled OSPF area design has "
        f"{len(design.areas)} area(s), {len(analysis.routers)} router(s): {counts}. "
        f"Derived effective link costs are {costs} using {analysis.link_costs[0].formula if analysis.link_costs else 'no links'}. "
        f"The model recorded {len(analysis.findings)} finding(s) and "
        f"{len(analysis.summaries)} inert summary suggestion(s). "
        "No OSPF packets, adjacencies, or route installation are simulated."
    )
    facts = (
        f"Areas {len(design.areas)}, routers {len(analysis.routers)}, roles {counts}, "
        f"costs {costs}, findings {len(analysis.findings)}, summaries "
        f"{len(analysis.summaries)}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.ospf_design,
        target_id="ospf",
        deterministic_text=deterministic,
        facts=facts,
    )


def ha_group_request(group: HaGroup, analysis: HaAnalysis) -> ExplanationRequest:
    """Build a deterministic gateway-group explanation from a design review."""
    active = analysis.active_members.get(group.id, "none")
    priorities = ", ".join(
        f"{member.device_id} {member.priority}" for member in group.members
    ) or "none"
    related = [
        finding.code
        for finding in analysis.findings
        if group.id in finding.affected_entities
    ]
    deterministic = (
        f"Gateway group {group.id} has {len(group.members)} modeled member(s) "
        f"with priorities {priorities}. The nominal active member is {active}. "
        f"Ties are broken by the lexicographically lowest device id; preempt is "
        f"metadata only. The review recorded {len(related)} group finding(s)"
        + (f": {', '.join(related)}." if related else ".")
        + " No VRRP or HSRP advertisement or packet behavior is simulated."
    )
    facts = (
        f"Group {group.id}, members {len(group.members)}, priorities {priorities}, "
        f"active {active}, findings {len(related)}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.ha_group,
        target_id=group.id,
        deterministic_text=deterministic,
        facts=facts,
    )


def l2_design_request(design: L2Design, analysis: L2Analysis) -> ExplanationRequest:
    """Build a hand-checkable Layer-2 design explanation.

    The rationale is rule based: cycle rank is edges minus vertices plus
    components, the modeled root is the smallest ``(priority, device id)``, and
    bundle capacity is the sum of the surviving modeled member links. No live
    switching protocol, STP election, or LACP negotiation is simulated.
    """
    loops = "; ".join(
        f"VLAN {loop.vlan_id} rank {loop.cycle_count}, root "
        f"{loop.root_bridge or 'none'}, blocked "
        f"{', '.join(loop.blocked_link_ids) or 'none'}"
        for loop in analysis.loops
    ) or "no VLAN loop reviews"
    bundles = "; ".join(
        f"{bundle.bundle_id} {_number(bundle.capacity_mbps)} Mbps from "
        f"{len(bundle.member_link_ids)} modeled member link(s)"
        for bundle in analysis.bundles
    ) or "none"
    deterministic = (
        f"Modeled Layer-2 design covers {len(analysis.loops)} VLAN review(s), "
        f"{len(analysis.blocked_link_ids)} blocked link(s), and "
        f"{len(analysis.bundles)} EtherChannel bundle(s). Loop detail: {loops}. "
        f"Bundle detail: {bundles}. Gateways are modeled for "
        f"{len(design.gateway_by_vlan)} VLAN(s), root priorities for "
        f"{len(design.root_priorities)} switch(es), and the sprawl heuristic "
        f"threshold is {design.vlan_spread_threshold} switch(es). The review "
        f"recorded {len(analysis.findings)} finding(s). This is a design model "
        "only: no live protocol state is simulated."
    )
    facts = (
        f"VLAN reviews {len(analysis.loops)}, blocked links "
        f"{', '.join(analysis.blocked_link_ids) or 'none'}, bundles {bundles}, "
        f"findings {len(analysis.findings)}, gateway VLANs "
        f"{len(design.gateway_by_vlan)}, root-priority switches "
        f"{len(design.root_priorities)}, sprawl threshold "
        f"{design.vlan_spread_threshold}, loop detail {loops}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.l2_design,
        target_id="l2",
        deterministic_text=deterministic,
        facts=facts,
    )


def wan_design_request(
    design: WanDesign | None,
    analysis: WanAnalysis,
) -> ExplanationRequest:
    """Build a hand-checkable WAN design explanation.

    The rationale is rule based: the monthly proxy is the sum of active
    inter-site link proxies, site reachability uses a bounded breadth-first walk
    over those links, and single-link groups are counted per site. No circuit is
    measured, no live protocol is run, and stated cost and latency assumptions
    are the only numbers used.
    """
    site_types = len(design.site_types) if design is not None else 0
    hq_targets = len(design.hq_site_ids) if design is not None else 0
    links = "; ".join(
        f"{info.link_id} monthly proxy {_number(info.monthly_cost_proxy)}, "
        f"latency {_number(info.latency_ms)} ms"
        for info in analysis.links
    ) or "none"
    deterministic = (
        f"Modeled WAN design covers {len(analysis.site_ids)} site(s) with "
        f"{len(analysis.links)} active inter-site WAN link(s) and a total monthly "
        f"cost proxy of {_number(analysis.total_monthly_cost_proxy)}. "
        f"{site_types} site type(s) and {hq_targets} explicit HQ target(s) come "
        f"from the modeled design; {analysis.evaluated_demand_count} demand(s) "
        f"were evaluated in the optional capacity-aware check. The review "
        f"recorded {len(analysis.findings)} finding(s). {MONTHLY_COST_NOTE} "
        f"{LATENCY_NOTE} This is a design model only: no circuit is measured "
        "and no live protocol is run."
    )
    facts = (
        f"Sites {len(analysis.site_ids)}, active links "
        f"{', '.join(info.link_id for info in analysis.links) or 'none'}, link "
        f"detail {links}, total monthly proxy "
        f"{_number(analysis.total_monthly_cost_proxy)}, modeled site types "
        f"{site_types}, explicit HQ targets {hq_targets}, evaluated demands "
        f"{analysis.evaluated_demand_count}, findings {len(analysis.findings)}, "
        f"{MONTHLY_COST_NOTE} {LATENCY_NOTE}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.wan_design,
        target_id="wan",
        deterministic_text=deterministic,
        facts=facts,
    )


def wireless_design_request(
    design: WirelessDesign | None,
    analysis: WirelessAnalysis,
) -> ExplanationRequest:
    """Build a hand-checkable wireless AP explanation.

    The rationale is hand computable from stated assumptions: capacity APs are
    ``ceil(clients * client_mbps / (ap_capacity * utilization_target))``,
    coverage APs are ``ceil(area / (pi * radius^2 * overlap))``, and the
    recommendation is the larger. Clients are never enumerated and no RF
    propagation or signal modeling is performed.
    """
    stated_areas = len(design.areas) if design is not None else 0
    capacity_bound = sum(
        plan.binding_constraint == "capacity" for plan in analysis.plans
    )
    coverage_bound = sum(
        plan.binding_constraint == "coverage" for plan in analysis.plans
    )
    plans = "; ".join(
        f"{plan.area_id} {plan.recommended_ap_count} AP(s) "
        f"({plan.binding_constraint})"
        for plan in analysis.plans
    ) or "none"
    deterministic = (
        f"Modeled wireless plan covers {len(analysis.plans)} abstract area(s) "
        f"from {stated_areas} stated design area(s) with "
        f"{analysis.total_recommended_aps} recommended AP(s) and a total uplink "
        f"requirement of {_number(analysis.total_uplink_required_mbps)} Mbps. "
        f"{capacity_bound} area(s) are capacity-bound and {coverage_bound} are "
        f"coverage-bound under the stated assumptions. Area detail: {plans}. "
        f"The review recorded {len(analysis.findings)} finding(s). {NO_RF_NOTE} "
        "This is a design model only: clients are stated assumptions, never "
        "enumerated."
    )
    facts = (
        f"Abstract areas {len(analysis.plans)}, stated areas {stated_areas}, "
        f"recommended APs {analysis.total_recommended_aps}, uplink Mbps "
        f"{_number(analysis.total_uplink_required_mbps)}, capacity-bound "
        f"{capacity_bound}, coverage-bound {coverage_bound}, area detail "
        f"{plans}, findings {len(analysis.findings)}, formulas {CAPACITY_FORMULA}; "
        f"{COVERAGE_FORMULA}; {UPLINK_FORMULA}, {NO_RF_NOTE}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.wireless_design,
        target_id="wireless",
        deterministic_text=deterministic,
        facts=facts,
    )


def qos_design_request(
    design: QosDesign | None,
    plan: QosAdmissionPlan,
    findings: tuple[Finding, ...] = (),
) -> ExplanationRequest:
    """Build a hand-checkable QoS admission explanation.

    The rationale is the documented strict-priority order and per-link share
    caps from the already-computed plan. Ties use descending bandwidth then
    stable identifiers. This is an admission model only: no queue simulation,
    drop, scheduler, or device hardware behavior is modeled.
    """
    class_order = ", ".join(
        traffic_class.value
        for traffic_class in sorted(
            TRAFFIC_CLASS_PRIORITY,
            key=lambda item: TRAFFIC_CLASS_PRIORITY[item],
        )
    )
    default_class = design.default_class.value if design is not None else "none"
    caps = "; ".join(
        f"{link_id}: "
        + ",".join(
            f"{traffic_class.value}={_number(share)}"
            for traffic_class, share in sorted(
                by_class.items(), key=lambda item: item[0].value
            )
        )
        for link_id, by_class in sorted(plan.class_caps.items())
    ) or "none"
    codes = ", ".join(finding.code for finding in findings)
    deterministic = (
        f"Modeled QoS admission plan orders {len(plan.demand_indices)} modeled "
        f"demand(s) by the documented class order {class_order}; the default "
        f"class is {default_class}. {len(plan.class_caps)} link(s) carry modeled "
        f"class share caps: {caps}. The review recorded "
        f"{len(findings)} finding(s)"
        + (f": {codes}." if codes else ".")
        + f" {ADMISSION_NOTE} This is a design model only: no queue simulation, "
        "drop, scheduler, or device hardware behavior is modeled."
    )
    facts = (
        f"Demand indices "
        f"{', '.join(str(index) for index in plan.demand_indices) or 'none'}, "
        f"class order {class_order}, default class {default_class}, caps {caps}, "
        f"findings {codes or 'none'}, {ADMISSION_NOTE}"
    )
    return ExplanationRequest(
        target=ExplanationTarget.qos_design,
        target_id="qos",
        deterministic_text=deterministic,
        facts=facts,
    )


def audit_ai_explanation(text: str, *, facts: str) -> str:
    """Return a rejection reason for unsafe AI explanation prose."""
    reason = audit_prose(text, allowed_numbers=facts)
    if reason:
        return reason
    lowered = text.lower()
    if any(term in lowered for term in _EXTRA_FORBIDDEN_TERMS):
        return "The AI text stated a verdict, level, decision, or out-of-scope instruction."
    return ""


def _key(
    *,
    provider: LLMProvider,
    prompt: PromptSpec,
    request: ExplanationRequest,
) -> CacheKey:
    return build_key(
        model=str(getattr(provider, "model", "") or "unknown"),
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        schema_name="AIExplanationDraft",
        payload=request.model_dump(mode="json"),
    )


def _result(
    request: ExplanationRequest,
    *,
    prompt: PromptSpec,
    ai_text: str = "",
    ai_rejection: str = "",
    cache_hit: bool = False,
    provider_used: bool = False,
) -> ExplanationResult:
    return ExplanationResult(
        target=request.target,
        target_id=request.target_id,
        deterministic_text=request.deterministic_text,
        ai_text=ai_text,
        ai_rejection=ai_rejection,
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        cache_hit=cache_hit,
        provider_used=provider_used,
    )


def explain(
    request: ExplanationRequest | dict[str, object],
    *,
    provider: LLMProvider | None = None,
    cache: CopilotCache | None = None,
    trace: PromptTrace | None = None,
    prompt: PromptSpec = EXPLAIN_RESULT,
    max_repair_retries: int = MAX_LLM_REPAIR_RETRIES,
) -> ExplanationResult:
    """Return a deterministic explanation and optionally an audited AI note."""
    typed = ExplanationRequest.model_validate(request)
    reject_unsafe_text(
        typed.deterministic_text,
        field="Deterministic explanation",
        max_chars=MAX_COPILOT_EXPLANATION_CHARS,
    )
    reject_unsafe_text(
        typed.facts,
        field="Explanation facts",
        max_chars=MAX_COPILOT_EXPLANATION_CHARS,
    )
    if provider is None:
        return _result(typed, prompt=prompt)

    key = _key(provider=provider, prompt=prompt, request=typed)
    cached = cache.get(key, AIExplanationDraft) if cache is not None else None
    if cached is not None:
        if trace is not None:
            trace.add(
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                schema_name="AIExplanationDraft",
                model=key.model,
                cache_hit=True,
            )
        rejection = audit_ai_explanation(cached.text, facts=typed.facts)
        return _result(
            typed,
            prompt=prompt,
            ai_text="" if rejection else cached.text,
            ai_rejection=rejection,
            cache_hit=True,
        )

    user_content = (
        "Explain these already-computed facts in at most two short sentences. "
        "Do not repeat or change any verdict, level, score, or decision.\n"
        f"TARGET: {typed.target.value}\n"
        f"FACTS: {typed.facts}"
    )
    try:
        draft_value = request_structured(
            provider,
            AIExplanationDraft,
            system_prompt=prompt.text,
            user_content=user_content,
            max_repair_retries=max_repair_retries,
        )
    except LLMMissingKeyError:
        return _result(typed, prompt=prompt, provider_used=False)
    except (LLMError, OversizedInputError) as error:
        return _result(
            typed,
            prompt=prompt,
            provider_used=True,
            ai_rejection=ensure_llm_status(
                "The AI note was unavailable or failed schema validation; only "
                "the deterministic explanation is shown.",
                error,
            ),
        )

    draft = AIExplanationDraft.model_validate(draft_value)
    if cache is not None:
        cache.put(key, draft)
    if trace is not None:
        trace.add(
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            schema_name="AIExplanationDraft",
            model=key.model,
            cache_hit=False,
        )
    rejection = audit_ai_explanation(draft.text, facts=typed.facts)
    return _result(
        typed,
        prompt=prompt,
        ai_text="" if rejection else draft.text,
        ai_rejection=rejection,
        provider_used=True,
    )


__all__ = [
    "ExplanationRequest",
    "audit_ai_explanation",
    "blast_radius_request",
    "explain",
    "finding_request",
    "l2_design_request",
    "optimization_request",
    "qos_design_request",
    "route_request",
    "segmentation_score_request",
    "simulation_request",
    "wan_design_request",
    "wireless_design_request",
]
