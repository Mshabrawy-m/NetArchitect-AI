"""Typed tool registry wrapping the deterministic engineering engines.

Every tool has an input model, an output model, and a pure implementation.
The registry validates both sides and rejects unknown or disallowed tools with
typed errors. No tool runs a shell, ``eval``, ``exec``, or arbitrary code.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from core.exceptions import (
    AgentValidationError,
    LimitsExceededError,
    NetArchitectError,
    ToolError,
    ToolInputError,
    ToolNotAllowedError,
    ToolNotFoundError,
    ToolOutputError,
)
from core.schemas.addressing import AddressingPlan, Subnet
from core.schemas.network import Topology
from core.schemas.requirements import NetworkRequirements
from core.schemas.routing import TrafficDemand
from core.schemas.scenario import Scenario
from core.schemas.validation import Finding, ValidationReport
from digital_twin import DigitalTwin, validate_twin
from network.addressing import (
    AddressAssignment,
    VlsmRequirement,
    VlsmResult,
    allocate_vlsm,
    detect_overlaps,
    validate_addressing,
)
from network.analysis import (
    AnalysisReport,
    SpofReport,
    analyze_topology,
    spof_report,
)
from network.routing import RoutePath, RoutingTable, routing_table, shortest_path
from network.topology import (
    ConnectivityReport,
    analyze_connectivity,
    generate_hierarchical_campus,
    generate_hybrid,
    generate_mesh,
    generate_ring,
    generate_spine_leaf,
    generate_star,
    generate_tree,
)
from network.vlan import VlanPlanResult, VlanRequest, plan_vlans
from optimization import Algorithm, OptimizationRun, OptimizationSettings
from optimization import run_optimization as run_optimization_engine
from security import FlowRequest, SecurityAnalysis, SecurityModel, analyze_design
from simulation import NetworkState, ScenarioRun, SimulationAssumptions
from simulation import evaluate as evaluate_network_state
from simulation import run_scenario as run_scenario_engine

from .planning import (
    DemandPlan,
    IpPlanResult,
    TopologyPolicyError,
    build_demands,
    build_ip_plan,
    build_topology,
    build_working_twin,
    validate_generator_params,
)


class RequirementsValidateInput(BaseModel):
    requirements: NetworkRequirements


class RequirementsValidation(BaseModel):
    requirements: NetworkRequirements
    site_count: int = Field(ge=0)
    department_count: int = Field(ge=0)
    total_user_count: int = Field(ge=0)


class TopologyGenerateInput(BaseModel):
    family: Literal[
        "star",
        "ring",
        "mesh",
        "tree",
        "campus",
        "spine_leaf",
        "hybrid",
    ] = "star"
    name: str = "Generated topology"
    site: str = "site-1"
    params: dict[str, Any] = Field(default_factory=dict)


class TopologyFromRequirementsInput(BaseModel):
    requirements: NetworkRequirements


class IpPlanFromRequirementsInput(BaseModel):
    requirements: NetworkRequirements
    base_network: str | None = None
    attempt: int = Field(default=1, ge=1)


class TopologyConnectivityInput(BaseModel):
    topology: Topology


class VlsmAllocateInput(BaseModel):
    parent: str
    requirements: list[VlsmRequirement]
    reserved_addresses: int | None = None


class VlanPlanInput(BaseModel):
    requests: list[VlanRequest]
    start_vlan_id: int = 10


class AddressingValidateInput(BaseModel):
    subnets: list[Subnet] = Field(default_factory=list)
    assignments: list[AddressAssignment] = Field(default_factory=list)


class AddressingOverlapsInput(BaseModel):
    subnets: list[Subnet] = Field(default_factory=list)


class OverlapReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class RoutingPathInput(BaseModel):
    topology: Topology
    source: str
    destination: str
    failed_devices: list[str] = Field(default_factory=list)
    failed_links: list[str] = Field(default_factory=list)


class RoutingTableInput(BaseModel):
    topology: Topology
    source: str
    failed_devices: list[str] = Field(default_factory=list)
    failed_links: list[str] = Field(default_factory=list)


class AnalysisInput(BaseModel):
    topology: Topology
    failed_devices: list[str] = Field(default_factory=list)
    failed_links: list[str] = Field(default_factory=list)


class SpofInput(BaseModel):
    topology: Topology


class TwinValidateInput(BaseModel):
    twin: DigitalTwin


class TwinLoadStateInput(BaseModel):
    twin: DigitalTwin
    assumptions: SimulationAssumptions | None = None


class SimulationRunInput(BaseModel):
    twin: DigitalTwin
    scenario: Scenario
    assumptions: SimulationAssumptions | None = None


class OptimizationRunInput(BaseModel):
    twin: DigitalTwin
    settings: OptimizationSettings
    algorithm: Algorithm = Algorithm.greedy


class DemandPlanInput(BaseModel):
    requirements: NetworkRequirements
    topology: Topology


class WorkingTwinInput(BaseModel):
    topology: Topology
    addressing: AddressingPlan | None = None
    vlan_plan: VlanPlanResult | None = None
    demands: list[TrafficDemand] = Field(default_factory=list)
    name: str | None = None


class SecurityAnalysisInput(BaseModel):
    twin: DigitalTwin
    model: SecurityModel | None = None
    flows: tuple[FlowRequest, ...] = Field(default_factory=tuple)


ToolImplementation = Callable[[Any], Any]

_GENERATORS = {
    "star": generate_star,
    "ring": generate_ring,
    "mesh": generate_mesh,
    "tree": generate_tree,
    "campus": generate_hierarchical_campus,
    "spine_leaf": generate_spine_leaf,
    "hybrid": generate_hybrid,
}


@dataclass(frozen=True)
class Tool:
    """One registered tool contract."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    implementation: ToolImplementation


def _generate_topology(payload: TopologyGenerateInput) -> Topology:
    generator = _GENERATORS[payload.family]
    signature = inspect.signature(generator)
    accepted = {
        name
        for name in signature.parameters
        if name not in {"name", "site"}
        and signature.parameters[name].kind
        in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    unknown = sorted(set(payload.params) - accepted)
    if unknown:
        raise ToolInputError(
            f"Unknown {payload.family} parameter(s): {', '.join(unknown)}"
        )
    checked = validate_generator_params(payload.family, payload.params)
    try:
        return generator(name=payload.name, site=payload.site, **checked)
    except Exception as error:
        fields = tuple(f"params.{name}" for name in sorted(checked))
        raise TopologyPolicyError(
            f"The {payload.family} parameters cannot produce a valid topology.",
            fields=fields,
        ) from error


def _validate_requirements(
    payload: RequirementsValidateInput,
) -> RequirementsValidation:
    facts = payload.requirements.user_provided
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    department_count = len(
        {
            department.id
            for site in sites
            for department in site.departments
        }
        | {department.id for department in facts.departments}
    )
    return RequirementsValidation(
        requirements=payload.requirements,
        site_count=len(sites),
        department_count=department_count,
        total_user_count=facts.total_user_count,
    )


def _vlsm(payload: VlsmAllocateInput):
    return allocate_vlsm(
        payload.parent,
        payload.requirements,
        reserved_addresses=payload.reserved_addresses,
    )


def _routing_path(payload: RoutingPathInput) -> RoutePath:
    return shortest_path(
        payload.topology,
        payload.source,
        payload.destination,
        failed_devices=payload.failed_devices,
        failed_links=payload.failed_links,
    )


def _routing_table(payload: RoutingTableInput) -> RoutingTable:
    return routing_table(
        payload.topology,
        payload.source,
        failed_devices=payload.failed_devices,
        failed_links=payload.failed_links,
    )


def _analysis(payload: AnalysisInput) -> AnalysisReport:
    return analyze_topology(
        payload.topology,
        failed_devices=payload.failed_devices,
        failed_links=payload.failed_links,
    )


def _spof(payload: SpofInput) -> SpofReport:
    return spof_report(payload.topology)


def _simulation(payload: SimulationRunInput) -> ScenarioRun:
    return run_scenario_engine(
        payload.twin,
        payload.scenario,
        payload.assumptions,
    )


def _twin_load_state(payload: TwinLoadStateInput) -> NetworkState:
    return evaluate_network_state(payload.twin, payload.assumptions)


def _optimization(payload: OptimizationRunInput) -> OptimizationRun:
    return run_optimization_engine(
        payload.twin,
        payload.settings,
        payload.algorithm,
    )


def _security_analysis(payload: SecurityAnalysisInput) -> SecurityAnalysis:
    return analyze_design(payload.twin, model=payload.model, flows=payload.flows)


def _topology_from_requirements(
    payload: TopologyFromRequirementsInput,
) -> Topology:
    """Run the deterministic policy with user-facing, typed failures only."""
    facts = payload.requirements.user_provided
    site_field = (
        "user_provided.organization.sites"
        if facts.organization is not None and facts.organization.sites
        else "user_provided.sites"
    )
    all_fields = (
        site_field,
        "user_provided.departments",
        "user_provided.total_user_count",
        "design_goals",
        "user_provided.constraints",
        "user_provided.device_requirements",
        "user_provided.link_requirements",
    )
    try:
        return build_topology(payload.requirements)
    except TopologyPolicyError:
        raise
    except LimitsExceededError as error:
        fields = (
            ("user_provided.device_requirements", "user_provided.link_requirements")
            if facts.device_requirements or facts.link_requirements
            else (site_field, "user_provided.departments")
        )
        raise TopologyPolicyError(
            "The supplied requirements exceed the topology device or link limits.",
            fields=fields,
        ) from error
    except ValidationError as error:
        fields = tuple(
            ".".join(str(part) for part in item["loc"])
            for item in error.errors()[:5]
        ) or all_fields
        raise TopologyPolicyError(
            "Some supplied requirement values are invalid.",
            fields=fields,
        ) from error
    except Exception as error:
        raise TopologyPolicyError(
            "The supplied requirements cannot be turned into a valid topology.",
            fields=all_fields,
        ) from error


def default_tools() -> tuple[Tool, ...]:
    """Return every built-in tool contract."""
    return (
        Tool(
            name="requirements_validate",
            description="Validate and summarize structured network requirements.",
            input_model=RequirementsValidateInput,
            output_model=RequirementsValidation,
            implementation=_validate_requirements,
        ),
        Tool(
            name="topology_generate",
            description="Generate a deterministic topology family.",
            input_model=TopologyGenerateInput,
            output_model=Topology,
            implementation=_generate_topology,
        ),
        Tool(
            name="topology_from_requirements",
            description="Build the structured-form topology policy for requirements.",
            input_model=TopologyFromRequirementsInput,
            output_model=Topology,
            implementation=_topology_from_requirements,
        ),
        Tool(
            name="topology_connectivity",
            description="Analyze topology connectivity.",
            input_model=TopologyConnectivityInput,
            output_model=ConnectivityReport,
            implementation=lambda payload: analyze_connectivity(payload.topology),
        ),
        Tool(
            name="vlsm_allocate",
            description="Allocate VLSM subnets inside a parent network.",
            input_model=VlsmAllocateInput,
            output_model=VlsmResult,
            implementation=_vlsm,
        ),
        Tool(
            name="vlan_plan",
            description="Assign VLAN ids and subnets to departments.",
            input_model=VlanPlanInput,
            output_model=VlanPlanResult,
            implementation=lambda payload: plan_vlans(
                payload.requests, start_vlan_id=payload.start_vlan_id
            ),
        ),
        Tool(
            name="addressing_validate",
            description="Validate subnets for overlap and duplicate addresses.",
            input_model=AddressingValidateInput,
            output_model=ValidationReport,
            implementation=lambda payload: validate_addressing(
                payload.subnets, payload.assignments
            ),
        ),
        Tool(
            name="addressing_overlaps",
            description="Detect overlapping subnet pairs.",
            input_model=AddressingOverlapsInput,
            output_model=OverlapReport,
            implementation=lambda payload: OverlapReport(
                findings=detect_overlaps(payload.subnets)
            ),
        ),
        Tool(
            name="ip_plan_from_requirements",
            description="Build the deterministic IP/VLAN plan for requirements.",
            input_model=IpPlanFromRequirementsInput,
            output_model=IpPlanResult,
            implementation=lambda payload: build_ip_plan(
                payload.requirements,
                base_network=payload.base_network,
                attempt=payload.attempt,
            ),
        ),
        Tool(
            name="routing_path",
            description="Return the lowest-cost path between two devices.",
            input_model=RoutingPathInput,
            output_model=RoutePath,
            implementation=_routing_path,
        ),
        Tool(
            name="routing_table",
            description="Build a deterministic routing table for one source.",
            input_model=RoutingTableInput,
            output_model=RoutingTable,
            implementation=_routing_table,
        ),
        Tool(
            name="topology_analysis",
            description="Run structural analysis on a topology.",
            input_model=AnalysisInput,
            output_model=AnalysisReport,
            implementation=_analysis,
        ),
        Tool(
            name="spof_analysis",
            description="Return single points of failure for a topology.",
            input_model=SpofInput,
            output_model=SpofReport,
            implementation=_spof,
        ),
        Tool(
            name="twin_validate",
            description="Validate a complete digital twin.",
            input_model=TwinValidateInput,
            output_model=ValidationReport,
            implementation=lambda payload: validate_twin(payload.twin),
        ),
        Tool(
            name="twin_load_state",
            description=(
                "Evaluate modeled link load, utilization, and unserved demands "
                "on a digital twin."
            ),
            input_model=TwinLoadStateInput,
            output_model=NetworkState,
            implementation=_twin_load_state,
        ),
        Tool(
            name="simulation_run",
            description="Run one bounded what-if scenario on a twin.",
            input_model=SimulationRunInput,
            output_model=ScenarioRun,
            implementation=_simulation,
        ),
        Tool(
            name="optimization_run",
            description="Run one bounded optimization algorithm on a twin.",
            input_model=OptimizationRunInput,
            output_model=OptimizationRun,
            implementation=_optimization,
        ),
        Tool(
            name="demand_plan",
            description="Derive modeled traffic demands from requirements.",
            input_model=DemandPlanInput,
            output_model=DemandPlan,
            implementation=lambda payload: build_demands(
                payload.requirements, payload.topology
            ),
        ),
        Tool(
            name="working_twin_build",
            description="Build a derived working twin from plan parts.",
            input_model=WorkingTwinInput,
            output_model=DigitalTwin,
            implementation=lambda payload: build_working_twin(
                topology=payload.topology,
                addressing=payload.addressing,
                vlan_plan=payload.vlan_plan,
                demands=payload.demands,
                name=payload.name,
            ),
        ),
        Tool(
            name="security_analysis",
            description=(
                "Analyze modeled zones, policy, flows, and design findings "
                "without contacting any device."
            ),
            input_model=SecurityAnalysisInput,
            output_model=SecurityAnalysis,
            implementation=_security_analysis,
        ),
    )


class ToolRegistry:
    """Name-addressable registry with typed input/output validation."""

    def __init__(self, tools: tuple[Tool, ...] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools if tools is not None else default_tools():
            self.register(tool)

    def register(self, tool: Tool) -> None:
        """Register ``tool``, rejecting a duplicate name."""
        if tool.name in self._tools:
            raise AgentValidationError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool

    def names(self) -> tuple[str, ...]:
        """Return registered tool names in deterministic order."""
        return tuple(sorted(self._tools))

    def get(self, name: str) -> Tool:
        """Return a tool by name or raise :class:`ToolNotFoundError`."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"Unknown tool: {name!r}")
        return tool

    def resolve(self, name: str, allowed: set[str] | frozenset[str]) -> Tool:
        """Return a tool that is both registered and in ``allowed``."""
        tool = self.get(name)
        if tool.name not in allowed:
            raise ToolNotAllowedError(
                f"Tool {name!r} is not in this agent's allowlist."
            )
        return tool

    def validate_input(self, tool: Tool, payload: object) -> BaseModel:
        """Validate a raw payload against ``tool.input_model``."""
        try:
            return tool.input_model.model_validate(payload)
        except ValidationError as error:
            raise ToolInputError(
                f"Invalid input for tool {tool.name!r}: "
                + "; ".join(
                    f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: "
                    f"{item['msg']}"
                    for item in error.errors()[:5]
                )
            ) from error

    def execute(self, tool: Tool, validated: BaseModel) -> BaseModel:
        """Run a tool with validated input and validate its output."""
        try:
            result = tool.implementation(validated)
        except NetArchitectError:
            raise
        except Exception as error:
            raise ToolError(
                f"Tool {tool.name!r} failed: {error}"
            ) from error
        try:
            return tool.output_model.model_validate(result)
        except ValidationError as error:
            raise ToolOutputError(
                f"Invalid output from tool {tool.name!r}: "
                + "; ".join(
                    f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: "
                    f"{item['msg']}"
                    for item in error.errors()[:5]
                )
            ) from error

    def invoke(
        self,
        name: str,
        payload: object,
        *,
        agent: str,
        allowed: set[str] | frozenset[str],
    ) -> BaseModel:
        """Validate input, run a tool, and validate its output."""
        tool = self.resolve(name, allowed)
        validated = self.validate_input(tool, payload)
        return self.execute(tool, validated)


def registry_with_defaults() -> ToolRegistry:
    """Return a registry containing every built-in tool."""
    return ToolRegistry()


__all__ = [
    "AddressingOverlapsInput",
    "AddressingValidateInput",
    "AnalysisInput",
    "DemandPlanInput",
    "IpPlanFromRequirementsInput",
    "OptimizationRunInput",
    "OverlapReport",
    "RequirementsValidateInput",
    "RequirementsValidation",
    "RoutingPathInput",
    "RoutingTableInput",
    "SecurityAnalysisInput",
    "SimulationRunInput",
    "SpofInput",
    "Tool",
    "ToolRegistry",
    "TopologyConnectivityInput",
    "TopologyFromRequirementsInput",
    "TopologyGenerateInput",
    "TwinLoadStateInput",
    "TwinValidateInput",
    "VlanPlanInput",
    "VlsmAllocateInput",
    "WorkingTwinInput",
    "default_tools",
    "registry_with_defaults",
]
