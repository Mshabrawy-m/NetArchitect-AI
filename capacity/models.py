"""Typed inputs and results for bounded capacity planning.

Every number produced here is a *modeled projection from stated assumptions*,
not a measurement or a guarantee. Forecasts may come from user-supplied history
or from a clearly labeled SYNTHETIC generator; provenance is carried from the
forecast result into the projection and the final capacity run.

The baseline digital twin is never mutated. Projected scenarios are copies with
only the mapped demand bandwidths replaced, and they are evaluated with the
existing :mod:`simulation.evaluator` flow model.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forecasting.models import DataProvenance, ForecastModelKind, SeriesUnit
from simulation.models import CongestionLevel, NetworkState

CAPACITY_NOTE = (
    "Modeled projections from supplied or synthetic data; not measurements or "
    "guarantees."
)
CAPACITY_METHOD_NOTE = (
    "Demand is projected per forecast step, applied to copies of the baseline "
    "twin, and evaluated with the existing single-path flow model. Link capacity "
    "changes do not alter path selection in this model."
)


class CapacityFindingCode(str, Enum):
    """Stable codes for non-fatal capacity-planning findings."""

    unmapped_series = "unmapped_series"
    unknown_demand = "unknown_demand"
    duplicate_mapping = "duplicate_mapping"
    missing_per_user_assumption = "missing_per_user_assumption"
    unused_per_user_assumption = "unused_per_user_assumption"
    short_forecast = "short_forecast"
    horizon_clipped = "horizon_clipped"
    no_mapped_demand = "no_mapped_demand"


class CapacityFinding(BaseModel):
    """One typed finding explaining what was mapped, skipped, or clipped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: CapacityFindingCode
    message: str
    series_id: str = ""
    demand_name: str = ""


class DemandMapping(BaseModel):
    """User-stated relationship between forecast series and twin demands.

    ``series_to_demand`` maps a forecast ``series_id`` to an existing demand
    name. A series measured in ``users`` additionally requires the user to state
    ``per_user_mbps``; a series already measured in ``Mbps`` does not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_to_demand: dict[str, str] = Field(default_factory=dict)
    per_user_mbps: float | None = Field(
        default=None,
        gt=0,
        description="Stated bandwidth per user; required only for user-count series.",
    )

    @model_validator(mode="after")
    def _validate_mapping(self) -> DemandMapping:
        for series_id, demand_name in self.series_to_demand.items():
            if not series_id or not demand_name:
                raise ValueError("Mapping keys and demand names must be non-empty.")
        if len(set(self.series_to_demand.values())) != len(self.series_to_demand):
            raise ValueError("Each demand may be mapped from at most one series.")
        if self.per_user_mbps is not None and self.per_user_mbps <= 0:
            raise ValueError("per_user_mbps must be positive when supplied.")
        return self


class ProjectedDemandPoint(BaseModel):
    """One step of one demand's bandwidth projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=1)
    timestamp: datetime
    series_id: str
    unit: SeriesUnit
    projected_value: float = Field(ge=0)
    bandwidth_mbps: float = Field(ge=0)
    data_label: str


class ProjectedDemand(BaseModel):
    """All projected steps for one existing twin demand."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    series_id: str
    provenance: DataProvenance
    data_label: str
    unit: SeriesUnit
    model: ForecastModelKind
    points: tuple[ProjectedDemandPoint, ...]

    def point_for(self, step: int) -> ProjectedDemandPoint | None:
        """Return the point for ``step``, if the forecast supplied it."""
        for point in self.points:
            if point.step == step:
                return point
        return None


class DemandProjection(BaseModel):
    """Bounded, provenance-carrying projection of twin demands."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    horizon: int = Field(ge=1)
    per_user_mbps: float | None = None
    step_timestamps: tuple[datetime, ...] = Field(
        default_factory=tuple,
        description="Projection timestamps in step order, from the first forecast result.",
    )
    demands: tuple[ProjectedDemand, ...] = Field(default_factory=tuple)
    findings: tuple[CapacityFinding, ...] = Field(default_factory=tuple)
    assumptions: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def has_synthetic(self) -> bool:
        """True when any projected demand came from SYNTHETIC data."""
        return any(
            demand.provenance is DataProvenance.synthetic for demand in self.demands
        )


class StepState(BaseModel):
    """Evaluated network state at one projected step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=1)
    timestamp: datetime
    state: NetworkState


class Crossing(BaseModel):
    """First modeled step at which one link entered a congestion band."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str
    level: CongestionLevel
    step: int = Field(ge=1)
    timestamp: datetime
    utilization_percent: float = Field(ge=0)


class Bottleneck(BaseModel):
    """Ranked link-level result over the projected horizon."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str
    endpoints: tuple[str, str]
    capacity_mbps: float = Field(gt=0)
    peak_utilization_percent: float = Field(ge=0)
    peak_step: int = Field(ge=0, description="0 means the baseline evaluation.")
    horizon_end_load_mbps: float = Field(ge=0)
    headroom_mbps: float = Field(
        description="capacity minus modeled load at the horizon end; may be negative."
    )
    crossings: tuple[Crossing, ...] = Field(default_factory=tuple)


class UpgradeRecommendation(BaseModel):
    """Smallest configured tier that clears the warning threshold at horizon end."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str
    endpoints: tuple[str, str]
    current_capacity_mbps: float = Field(gt=0)
    target_tier_name: str
    target_capacity_mbps: float = Field(gt=0)
    horizon_end_load_mbps: float = Field(ge=0)
    projected_utilization_percent: float = Field(ge=0)
    warning_threshold_percent: float = Field(gt=0)
    cost_delta: float = Field(ge=0)
    cost_unit: str
    note: str = CAPACITY_NOTE


class CapacityGap(BaseModel):
    """A link for which no configured tier clears the warning threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str
    endpoints: tuple[str, str]
    horizon_end_load_mbps: float = Field(ge=0)
    required_capacity_mbps: float = Field(gt=0)
    largest_available_capacity_mbps: float = Field(gt=0)
    note: str = CAPACITY_NOTE


class CapacityStopReason(str, Enum):
    """Why a bounded capacity evaluation stopped. Every run has one."""

    completed = "completed"
    runtime_limit = "runtime_limit"
    evaluation_limit = "evaluation_limit"
    no_projection = "no_projection"
    incomplete_projection = "incomplete_projection"


class CapacityBounds(BaseModel):
    """Configured and consumed bounds for one capacity run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_evaluations: int = Field(ge=1)
    max_horizon_steps: int = Field(ge=1)
    max_runtime_seconds: float = Field(gt=0)
    used_evaluations: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    stop_reason: CapacityStopReason


class CapacityRun(BaseModel):
    """Complete, traceable result of one bounded capacity evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    twin_fingerprint: str
    projection: DemandProjection
    baseline: NetworkState
    steps: tuple[StepState, ...] = Field(default_factory=tuple)
    crossings: tuple[Crossing, ...] = Field(default_factory=tuple)
    bottlenecks: tuple[Bottleneck, ...] = Field(default_factory=tuple)
    recommendations: tuple[UpgradeRecommendation, ...] = Field(default_factory=tuple)
    gaps: tuple[CapacityGap, ...] = Field(default_factory=tuple)
    bounds: CapacityBounds
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    note: str = CAPACITY_NOTE
    method_note: str = CAPACITY_METHOD_NOTE

    @property
    def has_synthetic(self) -> bool:
        """True when any projected demand was labeled SYNTHETIC."""
        return self.projection.has_synthetic

    @property
    def total_cost_delta(self) -> float:
        """Sum of the modeled upgrade cost deltas."""
        return float(sum(recommendation.cost_delta for recommendation in self.recommendations))


__all__ = [
    "CAPACITY_METHOD_NOTE",
    "CAPACITY_NOTE",
    "Bottleneck",
    "CapacityBounds",
    "CapacityFinding",
    "CapacityFindingCode",
    "CapacityGap",
    "CapacityRun",
    "CapacityStopReason",
    "Crossing",
    "DemandMapping",
    "DemandProjection",
    "ProjectedDemand",
    "ProjectedDemandPoint",
    "StepState",
    "UpgradeRecommendation",
]
