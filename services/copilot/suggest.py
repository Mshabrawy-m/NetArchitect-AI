"""C2: deterministic, engine-evaluated design suggestions.

Every suggestion comes from a deterministic signal (a single point of failure,
an overloaded link, a security design issue, or the worst case of a failure
sweep). Each proposed fix is a typed object that the existing engineering
engines evaluate before it is ranked. Baseline data is never mutated, and the
language model has no role in generating, scoring, or applying a suggestion.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from config.limits import MAX_COPILOT_SUGGESTIONS
from core.schemas.network import Link
from digital_twin import DigitalTwin, apply_failure
from network.analysis import spof_report
from optimization import (
    Candidate,
    CandidateEvaluation,
    CostModel,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationSettings,
    build_candidate_twin,
    evaluate_candidate,
)
from security import (
    ProposalSet,
    SecurityAnalysis,
    accept_proposed_rules,
    analyze_design,
)
from simulation import (
    CongestionLevel,
    FailureSweepResult,
    SimulationAssumptions,
    evaluate,
    twin_fingerprint,
)

MAX_SOURCE_ENTITIES = 3


class SuggestionKind(str, Enum):
    """Deterministic source of one suggestion."""

    spof = "spof"
    overloaded_link = "overloaded_link"
    security = "security"
    failure_sweep = "failure_sweep"


class CandidateProposal(BaseModel):
    """A typed optimization candidate plus the exact pool used to evaluate it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["candidate"] = "candidate"
    candidate: Candidate
    pool: tuple[Link, ...] = Field(default_factory=tuple)
    assumptions: SimulationAssumptions = Field(default_factory=SimulationAssumptions)


class SecurityProposal(BaseModel):
    """A typed set of accepted security rule ids and their source proposals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["security"] = "security"
    rule_ids: tuple[str, ...]
    proposals: ProposalSet


Proposal = Annotated[
    CandidateProposal | SecurityProposal,
    Field(discriminator="kind"),
]


class Suggestion(BaseModel):
    """One engine-evaluated, user-confirmable design suggestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: SuggestionKind
    title: str
    rationale: str
    proposal: Proposal
    before: dict[str, float]
    after: dict[str, float]
    score: float = Field(ge=0)
    primary_metric: str
    primary_before: float
    primary_after: float
    direction: Literal["lower", "higher"]


class SuggestionReport(BaseModel):
    """Bounded, deterministic suggestion set for one baseline twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_fingerprint: str
    suggestions: tuple[Suggestion, ...]
    warnings: tuple[str, ...] = Field(default_factory=tuple)


def _settings(
    twin: DigitalTwin,
    assumptions: SimulationAssumptions,
    pool: tuple[Link, ...] = (),
) -> OptimizationSettings:
    """Build fixed evaluation settings; no objective is chosen from prose."""
    entity_bound = float(
        max(1, len(twin.topology.devices) + len(twin.topology.links))
    )
    return OptimizationSettings(
        candidate_pool=pool,
        cost_model=CostModel(),
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=0.5,
                lower_bound=0.0,
                upper_bound=200.0,
            ),
            ObjectiveSpec(
                kind=ObjectiveKind.spof_count,
                weight=0.5,
                lower_bound=0.0,
                upper_bound=entity_bound,
            ),
        ),
        constraints=HardConstraints(
            require_connectivity=False,
            min_served_demand_ratio=None,
            max_utilization_percent=None,
        ),
        assumptions=assumptions,
        max_evaluations=1,
    )


def _metrics(evaluation: CandidateEvaluation) -> dict[str, float]:
    """Copy deterministic candidate metrics into a plain before/after map."""
    metrics = evaluation.metrics
    return {
        "served_demand_ratio": metrics.served_demand_ratio,
        "max_utilization_percent": metrics.max_utilization_percent,
        "overloaded_links": float(metrics.overloaded_link_count),
        "congested_links": float(metrics.congested_link_count),
        "spof_count": float(metrics.spof_count or 0),
        "weak_components": float(metrics.weak_component_count),
        "cost_proxy": metrics.infrastructure_cost_proxy,
    }


def _network_after(
    twin: DigitalTwin,
    candidate: Candidate,
    pool: tuple[Link, ...],
    assumptions: SimulationAssumptions,
) -> tuple[DigitalTwin, dict[str, float]]:
    """Build the new twin and re-evaluate it with the optimization engine."""
    settings = _settings(twin, assumptions, pool)
    new_twin = build_candidate_twin(twin, candidate, settings)
    evaluation = evaluate_candidate(new_twin, Candidate(), settings)
    return new_twin, _metrics(evaluation)


def _score(
    before: float,
    after: float,
    *,
    direction: Literal["lower", "higher"],
) -> float:
    """Compute a bounded improvement score from two engine-produced values."""
    improvement = before - after if direction == "lower" else after - before
    if improvement <= 0:
        return 0.0
    denominator = max(1.0, abs(before)) if direction == "lower" else 1.0
    return round(100.0 * improvement / denominator, 4)


def _make_suggestion(
    *,
    id: str,
    kind: SuggestionKind,
    title: str,
    rationale: str,
    proposal: Proposal,
    before: dict[str, float],
    after: dict[str, float],
    primary_metric: str,
    direction: Literal["lower", "higher"],
) -> Suggestion | None:
    primary_before = before[primary_metric]
    primary_after = after[primary_metric]
    score = _score(primary_before, primary_after, direction=direction)
    if score <= 0:
        return None
    return Suggestion(
        id=id,
        kind=kind,
        title=title,
        rationale=rationale,
        proposal=proposal,
        before=before,
        after=after,
        score=score,
        primary_metric=primary_metric,
        primary_before=primary_before,
        primary_after=primary_after,
        direction=direction,
    )


def _spof_suggestions(
    twin: DigitalTwin,
    assumptions: SimulationAssumptions,
    before: dict[str, float],
) -> list[Suggestion]:
    report = spof_report(twin.topology)
    suggestions: list[Suggestion] = []
    existing_ids = {link.id for link in twin.topology.links}
    base_capacity = min(
        (link.capacity_mbps for link in twin.topology.links),
        default=100.0,
    )
    for entry in report.entries[:MAX_SOURCE_ENTITIES]:
        if entry.kind == "link":
            link = next(
                (item for item in twin.topology.links if item.id == entry.entity_id),
                None,
            )
            if link is None:
                continue
            new_id = f"copilot-rd-{entry.entity_id}"
            if new_id in existing_ids:
                continue
            pool = (
                Link(
                    id=new_id,
                    endpoints=tuple(link.endpoints),
                    capacity_mbps=link.capacity_mbps,
                    cost=link.cost + 1.0,
                    directed=link.directed,
                ),
            )
            candidate = Candidate(selected_link_ids=(new_id,))
            _, after = _network_after(twin, candidate, pool, assumptions)
            proposal = CandidateProposal(
                candidate=candidate,
                pool=pool,
                assumptions=assumptions,
            )
            suggestion = _make_suggestion(
                id=f"spof-link:{entry.entity_id}",
                kind=SuggestionKind.spof,
                title=f"Add a redundant path for link {entry.entity_id}",
                rationale=(
                    f"Removing link {entry.entity_id} increases the component "
                    "count. A second parallel link is modeled as redundancy."
                ),
                proposal=proposal,
                before=before,
                after=after,
                primary_metric="spof_count",
                direction="lower",
            )
        else:
            isolated = sorted(entry.isolated_device_ids)
            if not isolated:
                continue
            devices = sorted(device.id for device in twin.topology.devices)
            peers = [
                device_id
                for device_id in devices
                if device_id not in isolated and device_id != entry.entity_id
            ]
            if not peers:
                continue
            new_id = f"copilot-rd-node-{entry.entity_id}"
            if new_id in existing_ids:
                continue
            pool = (
                Link(
                    id=new_id,
                    endpoints=(isolated[0], peers[0]),
                    capacity_mbps=base_capacity,
                    cost=2.0,
                    directed=False,
                ),
            )
            candidate = Candidate(selected_link_ids=(new_id,))
            _, after = _network_after(twin, candidate, pool, assumptions)
            proposal = CandidateProposal(
                candidate=candidate,
                pool=pool,
                assumptions=assumptions,
            )
            suggestion = _make_suggestion(
                id=f"spof-device:{entry.entity_id}",
                kind=SuggestionKind.spof,
                title=f"Add a bypass link for device {entry.entity_id}",
                rationale=(
                    f"Removing device {entry.entity_id} isolates "
                    f"{len(isolated)} device(s). A bypass link reconnects them "
                    "in the model."
                ),
                proposal=proposal,
                before=before,
                after=after,
                primary_metric="spof_count",
                direction="lower",
            )
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _overload_suggestions(
    twin: DigitalTwin,
    assumptions: SimulationAssumptions,
    before: dict[str, float],
    baseline_state: object,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    tiers = CostModel().tiers
    overloaded = [
        link
        for link in getattr(baseline_state, "links", ())
        if link.level is CongestionLevel.overloaded
    ][:MAX_SOURCE_ENTITIES]
    for link in overloaded:
        upgrade = next(
            (tier for tier in tiers if tier.capacity_mbps > link.capacity_mbps),
            None,
        )
        if upgrade is None:
            continue
        candidate = Candidate(tier_assignments=((link.link_id, upgrade.name),))
        _, after = _network_after(twin, candidate, (), assumptions)
        suggestion = _make_suggestion(
            id=f"overload:{link.link_id}",
            kind=SuggestionKind.overloaded_link,
            title=f"Upgrade link {link.link_id} to {upgrade.name}",
            rationale=(
                f"Link {link.link_id} is modeled at "
                f"{link.utilization_percent:.1f}% utilization. The next "
                "capacity tier is applied to this link only."
            ),
            proposal=CandidateProposal(
                candidate=candidate,
                assumptions=assumptions,
            ),
            before=before,
            after=after,
            primary_metric="overloaded_links",
            direction="lower",
        )
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _security_metrics(analysis: SecurityAnalysis) -> dict[str, float]:
    return {
        "findings": float(len(analysis.findings)),
        "risk_score": float(analysis.risk.score),
        "rules": float(analysis.summary.rule_count),
    }


def _security_suggestions(
    twin: DigitalTwin,
    analysis: SecurityAnalysis,
    before_network: dict[str, float],
) -> list[Suggestion]:
    before_security = _security_metrics(analysis)
    before = {**before_network, **before_security}
    suggestions: list[Suggestion] = []
    for rule in analysis.proposals.rules[:MAX_SOURCE_ENTITIES]:
        new_twin, applied = accept_proposed_rules(
            twin,
            analysis.proposals,
            (rule.id,),
        )
        if not applied:
            continue
        after_security = _security_metrics(analyze_design(new_twin))
        after = {**before_network, **after_security}
        suggestion = _make_suggestion(
            id=f"security:{rule.id}",
            kind=SuggestionKind.security,
            title=f"Apply proposed rule {rule.id}",
            rationale=(
                f"Deterministic finding {rule.based_on_finding} produced this "
                "deny rule. Applying it changes only the modeled policy."
            ),
            proposal=SecurityProposal(
                rule_ids=(rule.id,),
                proposals=analysis.proposals,
            ),
            before=before,
            after=after,
            primary_metric="findings",
            direction="lower",
        )
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _failure_metrics(
    twin: DigitalTwin,
    failed_link_ids: tuple[str, ...],
    failed_device_ids: tuple[str, ...],
    assumptions: SimulationAssumptions,
) -> dict[str, float]:
    failed = apply_failure(
        twin,
        link_ids=failed_link_ids,
        device_ids=failed_device_ids,
    )
    state = evaluate(failed, assumptions)
    return {
        "served_demand_ratio": state.served_demand_ratio,
        "overloaded_links": float(state.overloaded_link_count),
        "max_utilization_percent": state.max_utilization_percent,
    }


def _unique_link_id(twin: DigitalTwin, prefix: str) -> str:
    """Return a deterministic, unused link id derived from ``prefix``."""
    existing = {link.id for link in twin.topology.links}
    candidate = prefix[:48]
    if candidate not in existing:
        return candidate
    index = 2
    while f"{prefix[:44]}-{index}" in existing:
        index += 1
    return f"{prefix[:44]}-{index}"


def _bypass_endpoints(
    twin: DigitalTwin,
    *,
    failed_link_ids: tuple[str, ...],
    failed_device_ids: tuple[str, ...],
) -> tuple[str, str] | None:
    """Find two surviving devices separated by the modeled failure."""
    graph = nx.Graph()
    graph.add_nodes_from(sorted(device.id for device in twin.topology.devices))
    for link in twin.topology.links:
        if link.id in failed_link_ids:
            continue
        if any(endpoint in failed_device_ids for endpoint in link.endpoints):
            continue
        graph.add_edge(*link.endpoints)
    for device_id in failed_device_ids:
        if graph.has_node(device_id):
            graph.remove_node(device_id)

    components = sorted(
        (tuple(sorted(component)) for component in nx.connected_components(graph)),
        key=lambda component: component[0] if component else "",
    )
    if len(components) < 2:
        return None
    left = next((component for component in components if component), None)
    right = next((component for component in components[1:] if component), None)
    if left is None or right is None:
        return None
    return left[0], right[0]


def _sweep_suggestions(
    twin: DigitalTwin,
    assumptions: SimulationAssumptions,
    sweep: FailureSweepResult,
) -> list[Suggestion]:
    if not sweep.cases:
        return []
    worst = max(sweep.cases, key=lambda case: (case.impact.impact_score, case.plan.case_id))
    plan = worst.plan
    failed_links = plan.failed_link_ids
    failed_devices = plan.failed_device_ids
    if not failed_links and not failed_devices:
        return []
    before = _failure_metrics(twin, failed_links, failed_devices, assumptions)

    if failed_links:
        target_link = failed_links[0]
        link = next(
            (item for item in twin.topology.links if item.id == target_link),
            None,
        )
        if link is None:
            return []
        new_id = _unique_link_id(twin, f"copilot-sweep-{target_link}-rd")
        pool: tuple[Link, ...] = (
            Link(
                id=new_id,
                endpoints=link.endpoints,
                capacity_mbps=link.capacity_mbps,
                cost=link.cost,
                directed=link.directed,
            ),
        )
        candidate = Candidate(selected_link_ids=(new_id,))
        fix_detail = f"A redundant parallel path is modeled for link {target_link}."
    else:
        endpoints = _bypass_endpoints(
            twin,
            failed_link_ids=failed_links,
            failed_device_ids=failed_devices,
        )
        if endpoints is None:
            return []
        suffix = "-".join(sorted(failed_devices))[:24] or "bypass"
        new_id = _unique_link_id(twin, f"copilot-sweep-{suffix}-bypass")
        base_capacity = max(
            (item.capacity_mbps for item in twin.topology.links),
            default=100.0,
        )
        pool = (
            Link(
                id=new_id,
                endpoints=endpoints,
                capacity_mbps=base_capacity,
                cost=2.0,
                directed=False,
            ),
        )
        candidate = Candidate(selected_link_ids=(new_id,))
        fix_detail = (
            "A bypass link reconnects the surviving components after the "
            "failed device(s)."
        )

    settings = _settings(twin, assumptions, pool)
    new_twin = build_candidate_twin(twin, candidate, settings)
    after = _failure_metrics(new_twin, failed_links, failed_devices, assumptions)
    return [
        suggestion
        for suggestion in (
            _make_suggestion(
                id=f"failure-sweep:{plan.case_id}",
                kind=SuggestionKind.failure_sweep,
                title=f"Reduce the impact of failure case {plan.case_id}",
                rationale=(
                    f"This sweep case had the highest modeled impact "
                    f"({worst.impact.impact_score:.1f}). {fix_detail} The fix "
                    "is applied to a new twin and the same failure is "
                    "re-evaluated."
                ),
                proposal=CandidateProposal(
                    candidate=candidate,
                    pool=pool,
                    assumptions=assumptions,
                ),
                before=before,
                after=after,
                primary_metric="served_demand_ratio",
                direction="higher",
            ),
        )
        if suggestion is not None
    ]


def suggest(
    twin: DigitalTwin,
    *,
    assumptions: SimulationAssumptions | None = None,
    security_analysis: SecurityAnalysis | None = None,
    sweep: FailureSweepResult | None = None,
    max_suggestions: int = MAX_COPILOT_SUGGESTIONS,
) -> SuggestionReport:
    """Return bounded, engine-evaluated suggestions for one baseline twin.

    No language model is consulted. Every fix is re-evaluated by the existing
    optimization, simulation, or security engine before its score is computed.
    """
    if max_suggestions < 1:
        raise ValueError("max_suggestions must be at least 1")
    resolved = assumptions or SimulationAssumptions()
    baseline_settings = _settings(twin, resolved)
    baseline_evaluation = evaluate_candidate(
        twin,
        Candidate(),
        baseline_settings,
    )
    before_network = _metrics(baseline_evaluation)
    baseline_state = evaluate(twin, resolved)
    analysis = security_analysis or analyze_design(twin)

    collected: list[Suggestion] = []
    collected.extend(_spof_suggestions(twin, resolved, before_network))
    collected.extend(
        _overload_suggestions(twin, resolved, before_network, baseline_state)
    )
    collected.extend(_security_suggestions(twin, analysis, before_network))
    if sweep is not None:
        collected.extend(_sweep_suggestions(twin, resolved, sweep))

    ranked = sorted(collected, key=lambda item: (-item.score, item.id))
    warnings: list[str] = []
    if len(ranked) > max_suggestions:
        warnings.append(
            f"Showing the top {max_suggestions} of {len(ranked)} evaluated "
            "suggestions."
        )
    return SuggestionReport(
        baseline_fingerprint=twin_fingerprint(twin),
        suggestions=tuple(ranked[:max_suggestions]),
        warnings=tuple(warnings),
    )


def apply_suggestion(
    twin: DigitalTwin,
    suggestion: Suggestion,
) -> DigitalTwin:
    """Apply one confirmed suggestion to a NEW twin; never mutate the baseline."""
    if isinstance(suggestion.proposal, SecurityProposal):
        new_twin, applied = accept_proposed_rules(
            twin,
            suggestion.proposal.proposals,
            suggestion.proposal.rule_ids,
        )
        if set(applied) != set(suggestion.proposal.rule_ids):
            raise ValueError("The accepted proposal ids did not all apply.")
        return new_twin
    proposal = suggestion.proposal
    settings = _settings(twin, proposal.assumptions, proposal.pool)
    return build_candidate_twin(twin, proposal.candidate, settings)


__all__ = [
    "CandidateProposal",
    "SecurityProposal",
    "Suggestion",
    "SuggestionKind",
    "SuggestionReport",
    "apply_suggestion",
    "suggest",
]
