"""What-if scenario domain models.

Models describing a planned network change or failure scenario and the
result of evaluating connectivity and cost under that scenario.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ScenarioType(str, Enum):
    """Categories of what-if scenario the platform can evaluate."""

    single_link_failure = "single_link_failure"  # One link goes down.
    multiple_link_failures = "multiple_link_failures"  # Several links go down at once.
    node_failure = "node_failure"  # A device fails.
    bandwidth_reduction = "bandwidth_reduction"  # A link's capacity is reduced.
    increased_traffic_demand = "increased_traffic_demand"  # Demand rises on a flow.
    new_department = "new_department"  # A new department is added to a site.
    network_expansion = "network_expansion"  # New sites/devices are added.
    routing_cost_change = "routing_cost_change"  # Link/path costs change.
    redundancy_recovery_test = "redundancy_recovery_test"  # Test failover/redundancy.


class Scenario(BaseModel):
    """A what-if scenario to evaluate against a topology."""

    id: str = Field(description="Unique identifier for the scenario.")
    name: str = Field(description="Human-readable scenario name.")
    type: ScenarioType = Field(description="Category of the scenario.")
    description: str = Field(
        default="",
        description="Free-form description of the scenario.",
    )
    affected_links: list[str] = Field(
        default_factory=list,
        description="Ids of links affected by the scenario.",
    )
    affected_nodes: list[str] = Field(
        default_factory=list,
        description="Ids of devices affected by the scenario.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Scenario-specific tuning parameters.",
    )


class ScenarioResult(BaseModel):
    """The outcome of evaluating a :class:`Scenario`.

    All numeric fields are non-negative. Dict fields carry free-form scenario
    output that downstream UI/engineering code interprets.
    """

    scenario_id: str = Field(description="Id of the scenario this result is for.")
    success: bool = Field(description="Whether the scenario evaluation succeeded.")
    reachable_nodes: list[str] = Field(
        default_factory=list,
        description="Device ids still reachable after applying the scenario.",
    )
    disconnected_nodes: list[str] = Field(
        default_factory=list,
        description="Device ids that became unreachable.",
    )
    selected_paths: dict[str, Any] = Field(
        default_factory=dict,
        description="Paths chosen between demands, keyed by demand name.",
    )
    estimated_path_cost: float = Field(
        default=0.0,
        description="Total estimated cost of the selected paths (non-negative).",
        ge=0,
    )
    modeled_utilization: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-link utilization modeled under the scenario.",
    )
    congestion_indicators: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-link congestion flags/thresholds.",
    )
    recovery_available: bool = Field(
        default=False,
        description="Whether a recovery path exists for the failure.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings produced during evaluation.",
    )
    summary: str = Field(
        default="",
        description="Human-readable summary of the result.",
    )
