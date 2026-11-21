"""C3: deterministic explanations with optional, audited AI prose.

Every explanation starts from a typed request built by deterministic Python from
an already-computed engineering object. The deterministic paragraph is always
present and carries the computed values. An optional language model may add one
short advisory paragraph, which is audited for invented numbers, out-of-scope
content, and any attempt to state a verdict, level, rank, or decision.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from config.limits import (
    MAX_COPILOT_EXPLANATION_CHARS,
    MAX_LLM_REPAIR_RETRIES,
)
from core.exceptions import LLMError, LLMMissingKeyError, OversizedInputError
from core.inputs import reject_unsafe_text
from digital_twin import DigitalTwin
from optimization import (
    CandidateEvaluation,
    CandidateRecord,
    OptimizationSettings,
    candidate_changes,
)
from security import SecurityFinding
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
    except (LLMError, OversizedInputError):
        return _result(
            typed,
            prompt=prompt,
            provider_used=True,
            ai_rejection=(
                "The AI note was unavailable or failed schema validation; only "
                "the deterministic explanation is shown."
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
    "explain",
    "finding_request",
    "optimization_request",
    "route_request",
    "simulation_request",
]
