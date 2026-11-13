"""Typed models for bounded, reproducible network optimization.

Candidate representation
------------------------
A :class:`Candidate` is a deterministic, serializable set of decisions on top
of an unmodified baseline digital twin. It never stores a copy of the twin.

* ``selected_link_ids`` names links from the user-supplied candidate pool that
  are added to the candidate topology.
* ``tier_assignments`` maps a link id (baseline or selected) to a capacity tier
  name. A selected link without an assignment uses the first configured tier.
  A baseline link without an assignment keeps its existing capacity.
* ``cost_multipliers`` optionally scales the routing-cost metric of a baseline
  or selected link. A multiplier of 1 leaves the cost unchanged.

All tuples are canonicalized (sorted, duplicate-free) so two decisions with
the same meaning have the same hash and evaluate identically.

Units and cost scope
--------------------
Capacities are megabits per second. ``cost`` on a link is the routing metric
used by :mod:`network.routing`; it is not money. The infrastructure cost
objective is a *proxy* in model cost units. It charges selected links once at
their tier cost and charges only the positive tier delta for baseline capacity
upgrades; existing baseline infrastructure is treated as a sunk cost. Optional
per-device cost is charged for every device in the candidate topology.

No model in this module calls Streamlit, an LLM, or a random source.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

import config.limits
from core.schemas.network import Link
from simulation.models import MODEL_NOTE, SimulationAssumptions

COST_NOTE = (
    "Infrastructure cost is a modeled proxy from the stated tier costs and "
    "device cost; it is not a vendor quote, budget, or measured expense."
)
SEARCH_NOTE = (
    "Heuristic search over a modeled design space; no global optimum is "
    "claimed. Costs are proxies from stated assumptions."
)


class ObjectiveKind(str, Enum):
    """Objectives this engine can evaluate."""

    infrastructure_cost = "infrastructure_cost"
    max_utilization = "max_utilization"
    mean_path_cost = "mean_path_cost"
    spof_count = "spof_count"
    min_edge_disjoint_paths = "min_edge_disjoint_paths"
    link_count = "link_count"


class ObjectiveDirection(str, Enum):
    """Whether an objective value should be minimized or maximized."""

    minimize = "minimize"
    maximize = "maximize"


@dataclass(frozen=True)
class ObjectiveDefinition:
    """Static label, unit, direction, and definition of one objective."""

    label: str
    unit: str
    direction: ObjectiveDirection
    description: str


OBJECTIVE_DEFINITIONS: dict[ObjectiveKind, ObjectiveDefinition] = {
    ObjectiveKind.infrastructure_cost: ObjectiveDefinition(
        label="Infrastructure cost proxy",
        unit="modeled cost units",
        direction=ObjectiveDirection.minimize,
        description=(
            "Sum of selected-link tier costs, positive baseline-upgrade tier "
            "deltas, and the optional per-device cost for every device."
        ),
    ),
    ObjectiveKind.max_utilization: ObjectiveDefinition(
        label="Maximum link utilization",
        unit="percent",
        direction=ObjectiveDirection.minimize,
        description=(
            "Highest modeled link utilization from simulation.evaluator; "
            "utilization may exceed 100 percent and is not clamped."
        ),
    ),
    ObjectiveKind.mean_path_cost: ObjectiveDefinition(
        label="Mean served-demand path cost",
        unit="routing cost units per served demand",
        direction=ObjectiveDirection.minimize,
        description=(
            "Sum of selected path costs for served demands divided by the "
            "number of served demands; zero when no demand is served."
        ),
    ),
    ObjectiveKind.spof_count: ObjectiveDefinition(
        label="Single points of failure",
        unit="entities",
        direction=ObjectiveDirection.minimize,
        description=(
            "Count of devices and physical links whose individual removal "
            "increases the number of connected components."
        ),
    ),
    ObjectiveKind.min_edge_disjoint_paths: ObjectiveDefinition(
        label="Minimum edge-disjoint paths",
        unit="paths",
        direction=ObjectiveDirection.maximize,
        description=(
            "Minimum physical-link-disjoint path count over all demand "
            "endpoint pairs; zero when the twin has no demands."
        ),
    ),
    ObjectiveKind.link_count: ObjectiveDefinition(
        label="Link count",
        unit="links",
        direction=ObjectiveDirection.minimize,
        description="Number of physical links in the candidate topology.",
    ),
}


class Algorithm(str, Enum):
    """Optimization algorithms implemented by this package."""

    greedy = "greedy"
    genetic = "genetic"
    nsga2 = "nsga2"


class StopReason(str, Enum):
    """Why an optimization run stopped. Every run ends with one of these."""

    completed = "completed"
    no_improvement = "no_improvement"
    max_iterations = "max_iterations"
    max_evaluations = "max_evaluations"
    runtime_limit = "runtime_limit"


class CapacityTier(BaseModel):
    """One configurable link capacity tier and its cost proxy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Tier name, unique in the model.")
    capacity_mbps: float = Field(gt=0, description="Tier capacity in Mbps.")
    link_cost_proxy: float = Field(
        ge=0,
        description="Modeled cost units charged per selected link at this tier.",
    )


DEFAULT_TIERS: tuple[CapacityTier, ...] = (
    CapacityTier(name="100 Mbps", capacity_mbps=100.0, link_cost_proxy=100.0),
    CapacityTier(name="1 Gbps", capacity_mbps=1_000.0, link_cost_proxy=600.0),
    CapacityTier(name="10 Gbps", capacity_mbps=10_000.0, link_cost_proxy=4_000.0),
)


class CostModel(BaseModel):
    """Proxy cost assumptions for candidate links and capacity upgrades."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tiers: tuple[CapacityTier, ...] = Field(
        default=DEFAULT_TIERS,
        description="Capacity tiers in preference order; the first is the default.",
    )
    device_cost_proxy: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Optional modeled cost units charged once per device in the "
            "candidate topology."
        ),
    )
    unit: str = Field(
        default="modeled cost units",
        description="Label for the cost unit; this is not a real currency.",
    )
    note: str = Field(default=COST_NOTE, description="Cost-scope reminder.")

    @model_validator(mode="after")
    def _validate_tiers(self) -> CostModel:
        if not self.tiers:
            raise ValueError("A cost model needs at least one capacity tier.")
        names = [tier.name for tier in self.tiers]
        if len(set(names)) != len(names):
            raise ValueError("Capacity tier names must be unique.")
        capacities = [tier.capacity_mbps for tier in self.tiers]
        if len(set(capacities)) != len(capacities):
            raise ValueError("Capacity tier capacities must be unique.")
        for tier in self.tiers:
            if not math.isfinite(tier.capacity_mbps) or not math.isfinite(
                tier.link_cost_proxy
            ):
                raise ValueError(
                    f"Capacity tier {tier.name!r} must use finite numbers."
                )
        if not math.isfinite(self.device_cost_proxy):
            raise ValueError("Device cost must be a finite number.")
        return self

    def tier(self, name: str) -> CapacityTier:
        """Return the named tier or raise a clear error."""
        for tier in self.tiers:
            if tier.name == name:
                return tier
        raise ValueError(
            f"Unknown capacity tier {name!r}; configured tiers are "
            + ", ".join(repr(tier.name) for tier in self.tiers)
        )

    def tier_for_capacity(self, capacity_mbps: float) -> CapacityTier | None:
        """Return the tier whose capacity exactly matches, if any."""
        for tier in self.tiers:
            if tier.capacity_mbps == capacity_mbps:
                return tier
        return None


class Candidate(BaseModel):
    """A deterministic set of link additions, tiers, and cost adjustments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_link_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Ids from the candidate-link pool to add.",
    )
    tier_assignments: tuple[tuple[str, str], ...] = Field(
        default_factory=tuple,
        description="Link id -> capacity tier name.",
    )
    cost_multipliers: tuple[tuple[str, float], ...] = Field(
        default_factory=tuple,
        description="Link id -> positive multiplier on the routing cost metric.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        selected = [link_id for link_id in data.get("selected_link_ids", ()) if link_id]
        if len(selected) != len(set(selected)):
            raise ValueError("Selected link ids must be unique.")
        assignments = list(data.get("tier_assignments", ()))
        assignment_ids = [link_id for link_id, _ in assignments]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("Tier assignments must name each link at most once.")
        if any(not link_id or not tier for link_id, tier in assignments):
            raise ValueError("Tier assignments need a non-empty link id and tier.")
        multipliers = list(data.get("cost_multipliers", ()))
        multiplier_ids = [link_id for link_id, _ in multipliers]
        if len(multiplier_ids) != len(set(multiplier_ids)):
            raise ValueError("Cost multipliers must name each link at most once.")
        if any(not link_id for link_id, _ in multipliers):
            raise ValueError("Cost multipliers need a non-empty link id.")
        if any(
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not value > 0
            for _, value in multipliers
        ):
            raise ValueError("Cost multipliers must be positive finite numbers.")
        return {
            **data,
            "selected_link_ids": tuple(sorted(set(selected))),
            "tier_assignments": tuple(
                sorted((link_id, tier) for link_id, tier in assignments)
            ),
            "cost_multipliers": tuple(
                sorted((link_id, float(value)) for link_id, value in multipliers)
            ),
        }

    def tier_for(self, link_id: str) -> str | None:
        """Return the assigned tier name for ``link_id``, if any."""
        for assigned_id, tier in self.tier_assignments:
            if assigned_id == link_id:
                return tier
        return None

    def multiplier_for(self, link_id: str) -> float:
        """Return the routing-cost multiplier for ``link_id`` (1 by default)."""
        for assigned_id, value in self.cost_multipliers:
            if assigned_id == link_id:
                return value
        return 1.0


def candidate_hash(candidate: Candidate) -> str:
    """Return a stable SHA-256 hash of the canonical candidate decisions."""
    payload = json.dumps(
        candidate.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ObjectiveSpec(BaseModel):
    """One selected objective, its fixed normalization bounds, and its weight.

    Bounds are stated explicitly so normalization is reproducible and does not
    depend on the candidate population. Values outside the bounds are clamped
    to the normalized interval.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObjectiveKind = Field(description="Objective to evaluate.")
    weight: float = Field(
        default=1.0,
        ge=0,
        description="Weighted-sum weight; all selected weights must sum to 1.",
    )
    lower_bound: float = Field(
        description="Reference lower value used for min-max normalization.",
    )
    upper_bound: float = Field(
        description="Reference upper value used for min-max normalization.",
    )

    @model_validator(mode="after")
    def _validate_bounds(self) -> ObjectiveSpec:
        if not (
            math.isfinite(self.lower_bound)
            and math.isfinite(self.upper_bound)
            and math.isfinite(self.weight)
        ):
            raise ValueError("Objective bounds and weight must be finite.")
        if not self.upper_bound > self.lower_bound:
            raise ValueError(
                f"Objective {self.kind.value!r} needs upper_bound > lower_bound; "
                f"got {self.lower_bound} and {self.upper_bound}"
            )
        return self

    @property
    def definition(self) -> ObjectiveDefinition:
        """Return the static definition for this objective."""
        return OBJECTIVE_DEFINITIONS[self.kind]

    @property
    def direction(self) -> ObjectiveDirection:
        """Return the objective direction from the static definition."""
        return self.definition.direction

    @property
    def label(self) -> str:
        """Return the human-readable objective label."""
        return self.definition.label

    @property
    def unit(self) -> str:
        """Return the objective unit."""
        return self.definition.unit


class HardConstraints(BaseModel):
    """Hard constraints checked separately from objectives.

    A candidate that violates any enforced hard constraint is infeasible and is
    never reported as a recommendation. ``None`` disables a threshold.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    require_connectivity: bool = Field(
        default=True,
        description="Require at most one weak component and no isolated device.",
    )
    min_served_demand_ratio: float | None = Field(
        default=0.95,
        ge=0,
        le=1,
        description="Minimum served demands divided by total demands.",
    )
    max_utilization_percent: float | None = Field(
        default=100.0,
        gt=0,
        description="Maximum allowed modeled link utilization, in percent.",
    )
    max_budget_proxy: float | None = Field(
        default=None,
        ge=0,
        description="Maximum infrastructure cost proxy, in modeled cost units.",
    )
    max_nodes: int = Field(
        default=config.limits.MAX_NODES,
        ge=0,
        le=config.limits.MAX_NODES,
        description="Maximum device count in the candidate topology.",
    )
    max_edges: int = Field(
        default=config.limits.MAX_EDGES,
        ge=0,
        le=config.limits.MAX_EDGES,
        description="Maximum link count in the candidate topology.",
    )
    min_edge_disjoint_paths: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional minimum physical-link-disjoint path count for every "
            "demand endpoint pair."
        ),
    )


class OptimizationSettings(BaseModel):
    """All inputs that define one bounded optimization problem."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_pool: tuple[Link, ...] = Field(
        default_factory=tuple,
        description="Links the optimizer may select from; ids must be unique.",
    )
    cost_model: CostModel = Field(
        default_factory=CostModel,
        description="Proxy infrastructure cost assumptions.",
    )
    objectives: tuple[ObjectiveSpec, ...] = Field(
        min_length=1,
        description="Selected objectives, weights, and normalization bounds.",
    )
    constraints: HardConstraints = Field(
        default_factory=HardConstraints,
        description="Hard constraints applied to every candidate.",
    )
    assumptions: SimulationAssumptions = Field(
        default_factory=SimulationAssumptions,
        description="Flow-model assumptions shared by every evaluation.",
    )
    seed: int = Field(default=0, ge=0, description="Deterministic random seed.")
    population_size: int = Field(
        default=50,
        ge=1,
        le=config.limits.MAX_POPULATION,
        description="Population size for population-based algorithms.",
    )
    max_iterations: int = Field(
        default=100,
        ge=1,
        le=config.limits.MAX_OPTIMIZATION_ITERATIONS,
        description="Maximum generations or greedy improvement steps.",
    )
    max_evaluations: int = Field(
        default=2_000,
        ge=1,
        le=config.limits.MAX_EVALUATIONS,
        description="Maximum full candidate evaluations in the search phase.",
    )
    max_runtime_seconds: float = Field(
        default=30.0,
        gt=0,
        le=config.limits.MAX_OPTIMIZATION_RUNTIME_SECONDS,
        description="Search-phase wall-clock budget, in seconds.",
    )
    cost_multiplier_options: tuple[float, ...] = Field(
        default_factory=tuple,
        description=(
            "Optional routing-cost multipliers algorithms may apply to links. "
            "An empty tuple disables cost-adjustment moves."
        ),
    )

    @model_validator(mode="after")
    def _validate_settings(self) -> OptimizationSettings:
        pool_ids = [link.id for link in self.candidate_pool]
        if len(pool_ids) != len(set(pool_ids)):
            raise ValueError("Candidate-link pool ids must be unique.")
        weights = [objective.weight for objective in self.objectives]
        if not all(math.isfinite(weight) for weight in weights):
            raise ValueError("Objective weights must be finite.")
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError(
                "Objective weights must sum to 1; got "
                f"{sum(weights):.12g}"
            )
        kinds = [objective.kind for objective in self.objectives]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Each objective may be selected only once.")
        if any(
            not math.isfinite(value) or not value > 0
            for value in self.cost_multiplier_options
        ):
            raise ValueError("Cost multiplier options must be positive and finite.")
        return self

    def objective(self, kind: ObjectiveKind) -> ObjectiveSpec | None:
        """Return the selected objective of ``kind``, if present."""
        for objective in self.objectives:
            if objective.kind is kind:
                return objective
        return None

    def limits(self) -> OptimizationLimits:
        """Return the explicit limits recorded with a run."""
        return OptimizationLimits(
            max_population=self.population_size,
            max_iterations=self.max_iterations,
            max_evaluations=self.max_evaluations,
            max_runtime_seconds=self.max_runtime_seconds,
        )


class OptimizationLimits(BaseModel):
    """Explicit limits recorded on every optimization result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_population: int = Field(ge=1)
    max_iterations: int = Field(ge=1)
    max_evaluations: int = Field(ge=1)
    max_runtime_seconds: float = Field(gt=0)


class CandidateMetrics(BaseModel):
    """Modeled metrics recorded for one candidate evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    demand_count: int = Field(ge=0)
    served_demand_count: int = Field(ge=0)
    served_demand_ratio: float = Field(ge=0, le=1)
    max_utilization_percent: float = Field(ge=0)
    mean_path_cost: float = Field(ge=0)
    total_path_cost: float = Field(ge=0)
    congested_link_count: int = Field(ge=0)
    overloaded_link_count: int = Field(ge=0)
    weak_component_count: int = Field(ge=0)
    disconnected_device_count: int = Field(ge=0)
    infrastructure_cost_proxy: float = Field(ge=0)
    spof_count: int | None = Field(
        default=None,
        ge=0,
        description="Populated only when the objective or a constraint needs it.",
    )
    min_edge_disjoint_paths: int | None = Field(
        default=None,
        ge=0,
        description="Populated only when the objective or a constraint needs it.",
    )


class ObjectiveValue(BaseModel):
    """One raw and normalized objective value for a candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObjectiveKind
    label: str
    unit: str
    direction: ObjectiveDirection
    raw_value: float
    normalized_value: float = Field(ge=0, le=1)
    weight: float = Field(ge=0)
    contribution: float = Field(ge=0)


class ConstraintResult(BaseModel):
    """One hard-constraint check, including skipped constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    enforced: bool
    passed: bool
    actual: float | None = None
    threshold: float | None = None
    unit: str = ""
    detail: str = ""


class CandidateEvaluation(BaseModel):
    """The complete deterministic evaluation of one candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: Candidate
    candidate_hash: str = Field(min_length=64, max_length=64)
    metrics: CandidateMetrics
    objectives: tuple[ObjectiveValue, ...] = Field(default_factory=tuple)
    weighted_score: float = Field(
        ge=0,
        description="Weighted sum of normalized objectives; lower is better.",
    )
    constraints: tuple[ConstraintResult, ...] = Field(default_factory=tuple)
    feasible: bool
    violated_constraints: tuple[str, ...] = Field(default_factory=tuple)
    cache_hit: bool = Field(
        default=False,
        description="True when the result came from the per-run cache.",
    )


class CandidateRecord(BaseModel):
    """A candidate evaluation plus Pareto rank and crowding metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation: CandidateEvaluation
    rank: int | None = Field(default=None, ge=0)
    crowding_distance: float | None = Field(default=None, ge=0)


class OptimizationRun(BaseModel):
    """One reproducible optimization run with full traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Algorithm
    seed: int = Field(ge=0)
    settings: OptimizationSettings
    limits: OptimizationLimits
    evaluations: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    stop_reason: StopReason
    baseline: CandidateEvaluation
    candidates: tuple[CandidateRecord, ...] = Field(default_factory=tuple)
    pareto_front: tuple[CandidateRecord, ...] = Field(default_factory=tuple)
    best: CandidateRecord | None = Field(
        default=None,
        description=(
            "Best feasible candidate under the configured weighted score, or "
            "None when no evaluated candidate is feasible."
        ),
    )
    model_note: str = Field(default=MODEL_NOTE)
    cost_note: str = Field(default=COST_NOTE)
    search_note: str = Field(default=SEARCH_NOTE)


__all__ = [
    "COST_NOTE",
    "DEFAULT_TIERS",
    "OBJECTIVE_DEFINITIONS",
    "SEARCH_NOTE",
    "Algorithm",
    "Candidate",
    "CandidateEvaluation",
    "CandidateMetrics",
    "CandidateRecord",
    "CapacityTier",
    "ConstraintResult",
    "CostModel",
    "HardConstraints",
    "ObjectiveDefinition",
    "ObjectiveDirection",
    "ObjectiveKind",
    "ObjectiveSpec",
    "ObjectiveValue",
    "OptimizationLimits",
    "OptimizationRun",
    "OptimizationSettings",
    "StopReason",
    "candidate_hash",
]
