"""Deterministic candidate evaluation with per-run caching and counts.

``evaluate_candidate`` applies a candidate to a *new* twin, runs the existing
flow evaluator and structural analyses, and returns a typed result. It never
mutates the baseline twin. Identical candidate decisions are cached within one
run so the same design is not evaluated twice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.exceptions import OptimizationRuntimeExceeded, SimulationRuntimeExceeded
from core.schemas.network import Link
from digital_twin import DigitalTwin
from network.analysis import redundancy, spof_report
from network.routing import SparseRouter
from simulation import evaluate, twin_fingerprint
from simulation.models import NetworkState

from .constraints import evaluate_constraints
from .models import (
    Candidate,
    CandidateEvaluation,
    CandidateMetrics,
    ObjectiveKind,
    OptimizationSettings,
    candidate_hash,
)
from .objectives import (
    infrastructure_cost_proxy,
    objective_value,
    weighted_score,
)
from .space import baseline_link_index, build_candidate_twin, pool_index


def _context_key(baseline_twin: DigitalTwin, config: OptimizationSettings) -> str:
    """Identify the immutable inputs shared by a run's precomputed lookups."""
    return f"{twin_fingerprint(baseline_twin)}|{config.model_dump_json()}"


@dataclass
class EvaluationCache:
    """Per-run candidate cache, precomputed lookups, and evaluation counters."""

    results: dict[str, CandidateEvaluation] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    router_cache: dict[tuple[object, ...], SparseRouter] = field(default_factory=dict)
    pool: dict[str, Link] | None = None
    baseline_links: dict[str, Link] | None = None
    context_key: str | None = None

    @classmethod
    def for_run(
        cls,
        baseline_twin: DigitalTwin,
        config: OptimizationSettings,
    ) -> EvaluationCache:
        """Create a cache with the baseline link and pool indexes precomputed."""
        return cls(
            pool=pool_index(config),
            baseline_links=baseline_link_index(baseline_twin),
            context_key=_context_key(baseline_twin, config),
        )

    def prepare(
        self,
        baseline_twin: DigitalTwin,
        config: OptimizationSettings,
    ) -> None:
        """Populate or validate the per-run indexes before an evaluation."""
        key = _context_key(baseline_twin, config)
        if self.context_key is None:
            self.context_key = key
            self.pool = pool_index(config)
            self.baseline_links = baseline_link_index(baseline_twin)
        elif self.context_key != key:
            raise ValueError(
                "An evaluation cache must not be reused across different "
                "baselines or settings"
            )

    @property
    def unique_candidates(self) -> int:
        """Return the number of distinct candidates evaluated."""
        return len(self.results)

    def get(self, key: str) -> CandidateEvaluation | None:
        """Return a cached evaluation without changing counters."""
        return self.results.get(key)

    def put(self, key: str, evaluation: CandidateEvaluation) -> None:
        """Store an evaluation and count it as one full evaluation."""
        self.results[key] = evaluation
        self.misses += 1


def resolve_deadline(
    settings: OptimizationSettings,
    deadline: float | None,
) -> float:
    """Resolve an absolute monotonic search deadline."""
    if deadline is not None:
        return deadline
    return time.perf_counter() + settings.max_runtime_seconds


def deadline_expired(deadline: float) -> bool:
    """Return whether the search deadline has passed."""
    return time.perf_counter() > deadline


def _check_deadline(deadline: float) -> None:
    if deadline_expired(deadline):
        raise OptimizationRuntimeExceeded(
            "The optimization search exceeded its wall-clock limit. Reduce "
            "the candidate pool, population, or iterations and try again."
        )


def _redundancy_metrics(
    twin: DigitalTwin,
    state: NetworkState,
) -> int:
    """Return the minimum physical-link-disjoint path count over demands."""
    if not twin.demands:
        return 0
    counts = [
        redundancy(
            twin.topology,
            demand.source,
            demand.destination,
            failed_devices=state.failed_devices,
            failed_links=state.failed_links,
        ).edge_disjoint_paths
        for demand in twin.demands
    ]
    return min(counts) if counts else 0


def _metrics(
    baseline_twin: DigitalTwin,
    twin: DigitalTwin,
    candidate: Candidate,
    settings: OptimizationSettings,
    state: NetworkState,
    *,
    needs_spof: bool,
    needs_redundancy: bool,
    pool: dict[str, Link] | None = None,
    baseline_links: dict[str, Link] | None = None,
) -> CandidateMetrics:
    spof_count = (
        len(
            spof_report(
                twin.topology,
                failed_devices=state.failed_devices,
                failed_links=state.failed_links,
            ).entries
        )
        if needs_spof
        else None
    )
    min_paths = (
        _redundancy_metrics(twin, state) if needs_redundancy else None
    )
    mean_path_cost = (
        state.total_path_cost / state.served_demand_count
        if state.served_demand_count
        else 0.0
    )
    return CandidateMetrics(
        device_count=state.device_count,
        link_count=state.link_count,
        demand_count=state.demand_count,
        served_demand_count=state.served_demand_count,
        served_demand_ratio=state.served_demand_ratio,
        max_utilization_percent=state.max_utilization_percent,
        mean_path_cost=mean_path_cost,
        total_path_cost=state.total_path_cost,
        congested_link_count=state.congested_link_count,
        overloaded_link_count=state.overloaded_link_count,
        weak_component_count=len(state.weak_components),
        disconnected_device_count=len(state.disconnected_devices),
        infrastructure_cost_proxy=infrastructure_cost_proxy(
            baseline_twin,
            candidate,
            settings,
            pool=pool,
            baseline_links=baseline_links,
        ),
        spof_count=spof_count,
        min_edge_disjoint_paths=min_paths,
    )


def _raw_value(kind: ObjectiveKind, metrics: CandidateMetrics) -> float:
    """Map an objective kind to its raw modeled value."""
    if kind is ObjectiveKind.infrastructure_cost:
        return metrics.infrastructure_cost_proxy
    if kind is ObjectiveKind.max_utilization:
        return metrics.max_utilization_percent
    if kind is ObjectiveKind.mean_path_cost:
        return metrics.mean_path_cost
    if kind is ObjectiveKind.spof_count:
        return float(metrics.spof_count or 0)
    if kind is ObjectiveKind.min_edge_disjoint_paths:
        return float(metrics.min_edge_disjoint_paths or 0)
    if kind is ObjectiveKind.link_count:
        return float(metrics.link_count)
    raise ValueError(f"Unsupported objective kind: {kind!r}")  # pragma: no cover


def evaluate_candidate(
    baseline_twin: DigitalTwin,
    candidate: Candidate,
    config: OptimizationSettings,
    *,
    cache: EvaluationCache | None = None,
    deadline: float | None = None,
) -> CandidateEvaluation:
    """Evaluate one candidate against ``baseline_twin``.

    ``cache`` should be shared by every call in one run. It is keyed by the
    candidate hash, so callers must not reuse a cache across different
    baselines or settings. Cached hits are counted separately from full
    evaluations.
    """
    cache = cache if cache is not None else EvaluationCache()
    cache.prepare(baseline_twin, config)
    check_deadline = deadline if deadline is not None else resolve_deadline(
        config, None
    )
    _check_deadline(check_deadline)

    key = candidate_hash(candidate)
    cached = cache.get(key)
    if cached is not None:
        cache.hits += 1
        return cached.model_copy(update={"cache_hit": True})

    twin = build_candidate_twin(
        baseline_twin,
        candidate,
        config,
        pool=cache.pool,
        baseline_links=cache.baseline_links,
    )
    try:
        state = evaluate(
            twin,
            config.assumptions,
            _deadline=check_deadline,
            _router_cache=cache.router_cache,
        )
    except SimulationRuntimeExceeded as error:
        raise OptimizationRuntimeExceeded(str(error)) from error

    _check_deadline(check_deadline)
    needs_spof = config.objective(ObjectiveKind.spof_count) is not None
    needs_redundancy = (
        config.objective(ObjectiveKind.min_edge_disjoint_paths) is not None
        or config.constraints.min_edge_disjoint_paths is not None
    )
    metrics = _metrics(
        baseline_twin,
        twin,
        candidate,
        config,
        state,
        needs_spof=needs_spof,
        needs_redundancy=needs_redundancy,
        pool=cache.pool,
        baseline_links=cache.baseline_links,
    )
    values = tuple(
        objective_value(spec, _raw_value(spec.kind, metrics))
        for spec in config.objectives
    )
    constraints = evaluate_constraints(state, metrics, config.constraints)
    violated = tuple(
        result.name
        for result in constraints
        if result.enforced and not result.passed
    )
    evaluation = CandidateEvaluation(
        candidate=candidate,
        candidate_hash=key,
        metrics=metrics,
        objectives=values,
        weighted_score=weighted_score(values),
        constraints=constraints,
        feasible=not violated,
        violated_constraints=violated,
    )
    cache.put(key, evaluation)
    return evaluation


__all__ = [
    "EvaluationCache",
    "deadline_expired",
    "evaluate_candidate",
    "resolve_deadline",
]
