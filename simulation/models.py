"""Typed results for the abstract flow-simulation model.

Model (v1)
----------
This module models traffic as *flows between devices*, not packets. Every
number is a modeled estimate from the stated assumptions; nothing here is
packet-level or hardware-accurate emulation.

* Each :class:`~core.schemas.routing.TrafficDemand` is routed on the single
  lowest-cost path returned by :func:`network.routing.shortest_path`. The
  routing engine's deterministic lexicographic tie-break is reused. There is
  no flow splitting and no ECMP in v1.
* Link load is the sum of the bandwidth of every demand whose chosen path
  traverses the link. Parallel links have already collapsed in the routing
  graph, so load is assigned to the physical link chosen by that engine.
* A directed link records load for its one permitted direction
  (``endpoints[0]`` -> ``endpoints[1]``). An undirected link is shared by both
  directions: the report keeps the forward and reverse components separate for
  inspection, but utilization uses their sum against the one capacity.
* Utilization is ``load / capacity * 100``. It may exceed 100 percent and is
  never clamped; above the configured overload threshold the link is reported
  as ``overloaded``.
* Default congestion thresholds are warning at 70 percent, critical at
  90 percent, and overloaded above 100 percent. They are configurable through
  :class:`SimulationAssumptions`.
* An unroutable demand is returned as unserved with a reason. It is never
  dropped silently.
* Latency is estimated only when the caller supplies an explicit per-link
  delay assumption for every hop. Otherwise only path cost and hop count are
  reported. Delay values are milliseconds and are assumptions, not measured
  values.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MODEL_NOTE = (
    "Modeled estimates from stated assumptions; not packet-level or "
    "hardware-accurate."
)


class CongestionLevel(str, Enum):
    """Modeled utilization band for one link."""

    normal = "normal"  # Below the warning threshold.
    warning = "warning"  # At or above the warning threshold.
    critical = "critical"  # At or above the critical threshold.
    overloaded = "overloaded"  # Above the overload threshold.


class CongestionThresholds(BaseModel):
    """Configurable utilization thresholds, expressed as percentages."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warning_percent: float = Field(
        default=70.0,
        description="At or above this utilization the link is a warning.",
    )
    critical_percent: float = Field(
        default=90.0,
        description="At or above this utilization the link is critical.",
    )
    overload_percent: float = Field(
        default=100.0,
        description="Above this utilization the link is overloaded (strictly greater).",
    )

    @model_validator(mode="after")
    def _validate_order(self) -> CongestionThresholds:
        if not (
            0.0 < self.warning_percent < self.critical_percent < self.overload_percent
        ):
            raise ValueError(
                "Congestion thresholds must satisfy 0 < warning < critical < "
                "overload; got "
                f"{self.warning_percent}, {self.critical_percent}, "
                f"{self.overload_percent}"
            )
        return self

    def level_for(self, utilization_percent: float) -> CongestionLevel:
        """Classify one utilization value against the configured thresholds."""
        if utilization_percent > self.overload_percent:
            return CongestionLevel.overloaded
        if utilization_percent >= self.critical_percent:
            return CongestionLevel.critical
        if utilization_percent >= self.warning_percent:
            return CongestionLevel.warning
        return CongestionLevel.normal


class SimulationAssumptions(BaseModel):
    """Explicit, documented inputs to the flow model.

    ``link_delay_ms`` is optional. When a path has a delay entry for every
    traversed link, the result reports an estimated path latency in
    milliseconds. A partial map deliberately produces no latency estimate
    rather than silently treating a missing link as zero delay.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    thresholds: CongestionThresholds = Field(
        default_factory=CongestionThresholds,
        description="Utilization bands used to label links.",
    )
    link_delay_ms: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Assumed one-way delay per link id, in milliseconds. Empty means "
            "latency is not estimated."
        ),
    )

    @field_validator("link_delay_ms")
    @classmethod
    def _validate_delays(cls, value: dict[str, float]) -> dict[str, float]:
        for link_id, delay in value.items():
            if not link_id:
                raise ValueError("Link delay assumption keys must be non-empty.")
            if delay < 0:
                raise ValueError(
                    f"Link delay for {link_id!r} must be non-negative, got {delay}"
                )
        return dict(value)


class TwinReference(BaseModel):
    """Traceability reference for the twin revision a result came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Twin metadata name.")
    created_at: datetime = Field(description="Twin creation timestamp.")
    schema_version: int = Field(description="Digital-twin schema version.")
    fingerprint: str = Field(
        description="SHA-256 of the twin's canonical JSON serialization.",
    )


class DemandEvaluation(BaseModel):
    """The modeled path and outcome for one traffic demand."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Demand name.")
    source: str = Field(description="Source device id.")
    destination: str = Field(description="Destination device id.")
    bandwidth_mbps: float = Field(ge=0, description="Requested bandwidth, in Mbps.")
    served: bool = Field(description="Whether a path was found.")
    reason: str = Field(default="", description="Why the demand is unserved, if any.")
    path_device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Device ids along the chosen path, including both endpoints.",
    )
    link_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Physical link ids traversed by the chosen path.",
    )
    total_cost: float = Field(
        default=0.0,
        ge=0,
        description="Sum of Link.cost along the chosen path (unitless).",
    )
    hop_count: int = Field(default=0, ge=0, description="Number of links traversed.")
    latency_ms: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Estimated one-way latency in milliseconds, only when every hop has "
            "a delay assumption; otherwise None."
        ),
    )
    latency_note: str = Field(
        default="",
        description="Why latency was or was not estimated.",
    )


class UnservedDemand(BaseModel):
    """One demand for which no path exists under the modeled state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Demand name.")
    source: str = Field(description="Source device id.")
    destination: str = Field(description="Destination device id.")
    bandwidth_mbps: float = Field(ge=0, description="Requested bandwidth, in Mbps.")
    reason: str = Field(description="Why the demand could not be served.")


class LinkLoad(BaseModel):
    """Modeled load and utilization for one physical link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str = Field(description="Physical link id.")
    endpoints: tuple[str, str] = Field(description="The link's endpoint pair.")
    directed: bool = Field(description="Whether the link is directed.")
    capacity_mbps: float = Field(gt=0, description="Link capacity, in Mbps.")
    forward_load_mbps: float = Field(
        ge=0,
        description=(
            "Load in the endpoints[0] -> endpoints[1] direction. For an "
            "undirected link this is one share of the shared capacity."
        ),
    )
    reverse_load_mbps: float = Field(
        ge=0,
        description=(
            "Load in the endpoints[1] -> endpoints[0] direction. Always 0 for a "
            "directed link."
        ),
    )
    load_mbps: float = Field(
        ge=0,
        description=(
            "Total modeled load. Directed links use their one direction; "
            "undirected links sum both directions because capacity is shared."
        ),
    )
    utilization_percent: float = Field(
        ge=0,
        description="load_mbps / capacity_mbps * 100; may exceed 100.",
    )
    level: CongestionLevel = Field(description="Configured utilization band.")
    forward_demand_names: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Demands contributing to the forward direction.",
    )
    reverse_demand_names: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Demands contributing to the reverse direction.",
    )
    demand_names: tuple[str, ...] = Field(
        default_factory=tuple,
        description="All demands contributing to this link.",
    )


class NetworkState(BaseModel):
    """The complete modeled state produced by one :func:`evaluate` call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    twin: TwinReference = Field(description="Twin revision this state came from.")
    assumptions: SimulationAssumptions = Field(description="Assumptions used.")
    thresholds: CongestionThresholds = Field(
        description="Convenience copy of the thresholds used.",
    )
    device_count: int = Field(ge=0, description="Devices in the twin topology.")
    link_count: int = Field(ge=0, description="Links in the twin topology.")
    demand_count: int = Field(ge=0, description="Demands in the twin.")
    demands: tuple[DemandEvaluation, ...] = Field(
        default_factory=tuple,
        description="One evaluation per demand, in twin order.",
    )
    links: tuple[LinkLoad, ...] = Field(
        default_factory=tuple,
        description=(
            "One load record per surviving physical link, in topology order. "
            "Failed links and links attached to failed devices are excluded."
        ),
    )
    unserved_demands: tuple[UnservedDemand, ...] = Field(
        default_factory=tuple,
        description="Demands with no modeled path and the reason why.",
    )
    failed_devices: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Known devices modeled as down for this evaluation.",
    )
    failed_links: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Known links modeled as down for this evaluation.",
    )
    weak_components: tuple[tuple[str, ...], ...] = Field(
        default_factory=tuple,
        description="Weakly connected components after failures.",
    )
    isolated_devices: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Surviving devices with no incident links.",
    )
    disconnected_devices: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Surviving devices outside the largest weak component. Ties for "
            "largest are resolved by the lexicographically first device id."
        ),
    )
    max_utilization_percent: float = Field(
        default=0.0,
        ge=0,
        description="Highest modeled link utilization; 0 when there are no links.",
    )
    congested_link_count: int = Field(
        default=0,
        ge=0,
        description="Links at or above the warning threshold.",
    )
    overloaded_link_count: int = Field(
        default=0,
        ge=0,
        description="Links above the overload threshold.",
    )
    served_demand_count: int = Field(default=0, ge=0)
    served_demand_ratio: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Served demands divided by total demands; 0 when there are none.",
    )
    total_demand_mbps: float = Field(default=0.0, ge=0)
    served_demand_mbps: float = Field(default=0.0, ge=0)
    total_path_cost: float = Field(
        default=0.0,
        ge=0,
        description="Sum of the selected path costs for served demands.",
    )
    warnings: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Non-fatal modeling warnings, such as stale twin state.",
    )
    model_note: str = Field(default=MODEL_NOTE, description="Model scope reminder.")
