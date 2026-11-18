"""Standard deterministic agents for the structured-form design workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.exceptions import AgentValidationError
from core.schemas.network import Topology
from core.schemas.requirements import NetworkRequirements
from core.schemas.scenario import Scenario, ScenarioType
from core.schemas.validation import Finding, Severity, ValidationReport
from digital_twin import DigitalTwin
from network.routing import RoutePath, RoutingTable
from network.topology import ConnectivityReport
from optimization import (
    Algorithm,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationRun,
    OptimizationSettings,
)
from simulation import ScenarioRun

from .base import AgentContext, BaseAgent
from .models import summarize
from .planning import (
    DemandPlan,
    IpPlanResult,
    base_network_for,
    next_base_network,
)


class RequirementsInput(BaseModel):
    requirements: NetworkRequirements


class RequirementsOutput(BaseModel):
    requirements: NetworkRequirements
    site_count: int = Field(ge=0)
    department_count: int = Field(ge=0)
    total_user_count: int = Field(ge=0)
    summary: str


class TopologyInput(BaseModel):
    requirements: NetworkRequirements


class TopologyOutput(BaseModel):
    topology: Topology
    connectivity: ConnectivityReport
    twin: DigitalTwin


class IpVlanInput(BaseModel):
    requirements: NetworkRequirements
    base_network: str | None = None
    attempt: int = Field(default=1, ge=1)


class IpVlanOutput(BaseModel):
    plan: IpPlanResult
    demands: DemandPlan
    twin: DigitalTwin


class RoutingInput(BaseModel):
    pass


class RoutingOutput(BaseModel):
    source: str | None = None
    destination: str | None = None
    table: RoutingTable | None = None
    path: RoutePath | None = None
    reason: str = ""


class ValidationInput(BaseModel):
    pass


class ValidationOutput(BaseModel):
    addressing: ValidationReport
    twin: ValidationReport | None = None
    is_valid: bool
    issue_codes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class SimulationInput(BaseModel):
    pass


class SimulationOutput(BaseModel):
    run: ScenarioRun | None = None
    skipped_reason: str = ""
    summary: str = ""


class OptimizationInput(BaseModel):
    pass


class OptimizationOutput(BaseModel):
    run: OptimizationRun | None = None
    skipped_reason: str = ""
    summary: str = ""


class RevalidationInput(BaseModel):
    pass


class RevalidationOutput(BaseModel):
    report: ValidationReport
    is_valid: bool
    issue_codes: list[str] = Field(default_factory=list)


class ReportInput(BaseModel):
    title: str = "Structured design plan"


class ReportSection(BaseModel):
    title: str
    body: str
    status: str = "info"


class WorkflowReport(BaseModel):
    headline: str
    sections: list[ReportSection] = Field(default_factory=list)


class RequirementsAgent(BaseAgent):
    name = "requirements"
    responsibility = "Validate structured requirements without inventing facts."
    input_model = RequirementsInput
    output_model = RequirementsOutput
    allowed_tools = frozenset({"requirements_validate"})

    def run(self, payload: RequirementsInput, context: AgentContext) -> RequirementsOutput:
        validated = context.call_tool(
            "requirements_validate",
            {"requirements": payload.requirements},
        )
        summary = (
            f"{validated.site_count} site(s), {validated.department_count} "
            f"department(s), {validated.total_user_count} reported user(s)."
        )
        return RequirementsOutput(
            requirements=validated.requirements,
            site_count=validated.site_count,
            department_count=validated.department_count,
            total_user_count=validated.total_user_count,
            summary=summary,
        )


class TopologyAgent(BaseAgent):
    name = "topology"
    responsibility = "Build a deterministic topology and check connectivity."
    input_model = TopologyInput
    output_model = TopologyOutput
    allowed_tools = frozenset(
        {"topology_from_requirements", "topology_connectivity", "working_twin_build"}
    )

    def run(self, payload: TopologyInput, context: AgentContext) -> TopologyOutput:
        topology = context.call_tool(
            "topology_from_requirements",
            {"requirements": payload.requirements},
        )
        connectivity = context.call_tool(
            "topology_connectivity",
            {"topology": topology},
        )
        twin = context.call_tool(
            "working_twin_build",
            {"topology": topology, "name": topology.name},
        )
        return TopologyOutput(
            topology=topology,
            connectivity=connectivity,
            twin=twin,
        )


class IpVlanAgent(BaseAgent):
    name = "ip_vlan"
    responsibility = "Allocate VLSM subnets and assign a VLAN per department."
    input_model = IpVlanInput
    output_model = IpVlanOutput
    allowed_tools = frozenset(
        {"ip_plan_from_requirements", "demand_plan", "working_twin_build"}
    )

    def run(self, payload: IpVlanInput, context: AgentContext) -> IpVlanOutput:
        topology_output = context.result("topology")
        if not isinstance(topology_output, TopologyOutput):
            raise AgentValidationError(
                "The topology task must complete before IP planning."
            )
        plan = context.call_tool(
            "ip_plan_from_requirements",
            {
                "requirements": payload.requirements,
                "base_network": payload.base_network,
                "attempt": payload.attempt,
            },
        )
        demands = context.call_tool(
            "demand_plan",
            {
                "requirements": payload.requirements,
                "topology": topology_output.topology,
            },
        )
        twin = context.call_tool(
            "working_twin_build",
            {
                "topology": topology_output.topology,
                "addressing": plan.addressing,
                "vlan_plan": plan.vlan_plan,
                "demands": demands.demands,
                "name": topology_output.topology.name,
            },
        )
        return IpVlanOutput(plan=plan, demands=demands, twin=twin)

    def replan(self, payload: IpVlanInput, issue: str) -> IpVlanInput:
        """Move the plan to the next sibling block without redoing upstream work."""
        base = payload.base_network or base_network_for(payload.requirements)
        return IpVlanInput(
            requirements=payload.requirements,
            base_network=next_base_network(base, 1),
            attempt=payload.attempt + 1,
        )


class RoutingAgent(BaseAgent):
    name = "routing"
    responsibility = "Compute deterministic paths and a routing table."
    input_model = RoutingInput
    output_model = RoutingOutput
    allowed_tools = frozenset({"routing_path", "routing_table"})

    def run(self, payload: RoutingInput, context: AgentContext) -> RoutingOutput:
        twin = context.current_twin
        if twin is None or not twin.topology.devices:
            return RoutingOutput(reason="No topology is available for routing.")
        devices = sorted(device.id for device in twin.topology.devices)
        source, destination = devices[0], devices[-1]
        try:
            table = context.call_tool(
                "routing_table",
                {"topology": twin.topology, "source": source},
            )
            path = context.call_tool(
                "routing_path",
                {
                    "topology": twin.topology,
                    "source": source,
                    "destination": destination,
                },
            )
        except Exception as error:  # noqa: BLE001 - reported as a task failure
            return RoutingOutput(
                source=source,
                destination=destination,
                reason=f"Routing failed: {error}",
            )
        return RoutingOutput(
            source=source,
            destination=destination,
            table=table,
            path=path,
            reason="" if path.reachable else path.reason,
        )


class ValidationAgent(BaseAgent):
    name = "validation"
    responsibility = "Validate addressing and the complete working twin."
    input_model = ValidationInput
    output_model = ValidationOutput
    allowed_tools = frozenset({"addressing_validate", "twin_validate"})

    def run(self, payload: ValidationInput, context: AgentContext) -> ValidationOutput:
        ip_output = context.result("ip_vlan")
        subnets = (
            ip_output.plan.subnets
            if isinstance(ip_output, IpVlanOutput)
            else []
        )
        addressing = context.call_tool(
            "addressing_validate",
            {"subnets": subnets},
        )
        twin = context.current_twin
        twin_report = (
            context.call_tool("twin_validate", {"twin": twin})
            if twin is not None
            else None
        )
        findings: list[Finding] = list(addressing.findings)
        if twin_report is not None:
            findings.extend(twin_report.findings)
        blocking = [
            finding
            for finding in findings
            if finding.severity in {Severity.error, Severity.critical}
        ]
        return ValidationOutput(
            addressing=addressing,
            twin=twin_report,
            is_valid=not blocking,
            issue_codes=sorted({finding.code for finding in blocking}),
            issues=[finding.explanation for finding in blocking],
        )


class SimulationAgent(BaseAgent):
    name = "simulation"
    responsibility = "Run one bounded link-failure what-if scenario."
    input_model = SimulationInput
    output_model = SimulationOutput
    allowed_tools = frozenset({"simulation_run"})

    def run(self, payload: SimulationInput, context: AgentContext) -> SimulationOutput:
        twin = context.current_twin
        if twin is None or not twin.topology.links:
            return SimulationOutput(
                skipped_reason="A simulation needs a topology with at least one link."
            )
        if not twin.demands:
            return SimulationOutput(
                skipped_reason="A simulation needs at least one modeled demand."
            )
        link = min(twin.topology.links, key=lambda item: item.id)
        scenario = Scenario(
            id="plan-link-failure",
            name="Plan link-failure check",
            type=ScenarioType.single_link_failure,
            description=(
                "Modeled failure of the first link so the plan records a "
                "recovery state."
            ),
            affected_links=[link.id],
        )
        run = context.call_tool(
            "simulation_run",
            {"twin": twin, "scenario": scenario},
        )
        return SimulationOutput(run=run, summary=run.comparison.summary)


class OptimizationAgent(BaseAgent):
    name = "optimization"
    responsibility = "Run a bounded deterministic optimization baseline."
    input_model = OptimizationInput
    output_model = OptimizationOutput
    allowed_tools = frozenset({"optimization_run"})

    def run(
        self, payload: OptimizationInput, context: AgentContext
    ) -> OptimizationOutput:
        twin = context.current_twin
        if twin is None or not twin.topology.links:
            return OptimizationOutput(
                skipped_reason="Optimization needs a topology with at least one link."
            )
        settings = OptimizationSettings(
            candidate_pool=(),
            objectives=(
                ObjectiveSpec(
                    kind=ObjectiveKind.link_count,
                    weight=1.0,
                    lower_bound=0.0,
                    upper_bound=float(max(1, len(twin.topology.links) + 1)),
                ),
            ),
            seed=42,
            population_size=4,
            max_iterations=2,
            max_evaluations=20,
            max_runtime_seconds=5.0,
        )
        run = context.call_tool(
            "optimization_run",
            {
                "twin": twin,
                "settings": settings,
                "algorithm": Algorithm.greedy,
            },
        )
        best = (
            "no feasible candidate"
            if run.best is None
            else f"best score {run.best.evaluation.weighted_score:.3f}"
        )
        return OptimizationOutput(
            run=run,
            summary=(
                f"{run.algorithm.value} over {run.evaluations} evaluation(s); "
                f"{best}; stop reason {run.stop_reason.value}."
            ),
        )


class RevalidationAgent(BaseAgent):
    name = "revalidation"
    responsibility = "Re-validate the final working twin."
    input_model = RevalidationInput
    output_model = RevalidationOutput
    allowed_tools = frozenset({"twin_validate"})

    def run(
        self, payload: RevalidationInput, context: AgentContext
    ) -> RevalidationOutput:
        twin = context.current_twin
        if twin is None:
            raise ValueError("No working twin is available for re-validation.")
        report = context.call_tool("twin_validate", {"twin": twin})
        blocking = [
            finding
            for finding in report.findings
            if finding.severity in {Severity.error, Severity.critical}
        ]
        return RevalidationOutput(
            report=report,
            is_valid=not blocking,
            issue_codes=sorted({finding.code for finding in blocking}),
        )


class ReportAgent(BaseAgent):
    name = "report"
    responsibility = "Summarize the deterministic plan and its results."
    input_model = ReportInput
    output_model = WorkflowReport
    allowed_tools = frozenset()

    def run(self, payload: ReportInput, context: AgentContext) -> WorkflowReport:
        sections: list[ReportSection] = []
        requirements = context.result("requirements")
        if isinstance(requirements, RequirementsOutput):
            sections.append(
                ReportSection(
                    title="Requirements",
                    body=requirements.summary,
                )
            )
        topology = context.result("topology")
        if isinstance(topology, TopologyOutput):
            sections.append(
                ReportSection(
                    title="Topology",
                    body=(
                        f"{len(topology.topology.devices)} device(s), "
                        f"{len(topology.topology.links)} link(s); "
                        f"{topology.connectivity.component_count} component(s), "
                        f"connected={topology.connectivity.is_connected}."
                    ),
                )
            )
        ip_plan = context.result("ip_vlan")
        if isinstance(ip_plan, IpVlanOutput):
            vlan_count = (
                0
                if ip_plan.plan.vlan_plan is None
                else len(ip_plan.plan.vlan_plan.assignments)
            )
            sections.append(
                ReportSection(
                    title="IP and VLANs",
                    body=(
                        f"{len(ip_plan.plan.subnets)} subnet(s), "
                        f"{vlan_count} VLAN(s), base "
                        f"{ip_plan.plan.base_network}."
                    ),
                )
            )
        routing = context.result("routing")
        if isinstance(routing, RoutingOutput) and routing.path is not None:
            sections.append(
                ReportSection(
                    title="Routing",
                    body=(
                        f"{routing.source} -> {routing.destination}: "
                        f"reachable={routing.path.reachable}, "
                        f"cost={routing.path.total_cost:.3f}, "
                        f"hops={routing.path.hop_count}."
                    ),
                )
            )
        validation = context.result("validation")
        if isinstance(validation, ValidationOutput):
            sections.append(
                ReportSection(
                    title="Validation",
                    body=(
                        f"valid={validation.is_valid}; "
                        f"issues={len(validation.issues)}."
                    ),
                    status="ok" if validation.is_valid else "error",
                )
            )
        simulation = context.result("simulation")
        if isinstance(simulation, SimulationOutput):
            sections.append(
                ReportSection(
                    title="Simulation",
                    body=simulation.summary or simulation.skipped_reason,
                    status="ok" if simulation.run is not None else "info",
                )
            )
        optimization = context.result("optimization")
        if isinstance(optimization, OptimizationOutput):
            sections.append(
                ReportSection(
                    title="Optimization",
                    body=optimization.summary or optimization.skipped_reason,
                    status="ok" if optimization.run is not None else "info",
                )
            )
        revalidation = context.result("revalidation")
        if isinstance(revalidation, RevalidationOutput):
            sections.append(
                ReportSection(
                    title="Re-validation",
                    body=(
                        f"valid={revalidation.is_valid}; "
                        f"issues={len(revalidation.report.findings)}."
                    ),
                    status="ok" if revalidation.is_valid else "error",
                )
            )
        security = context.result("security")
        if security is not None and hasattr(security, "analysis"):
            sections.append(
                ReportSection(
                    title="Design-time security",
                    body=(
                        f"posture={security.posture.value}; "
                        f"risk={security.risk_score} ({security.risk_level.value}); "
                        f"gate={security.gate.value}; "
                        f"findings={len(security.analysis.findings)}."
                    ),
                    status=(
                        "ok"
                        if security.gate.value != "REJECTED"
                        else "error"
                    ),
                )
            )
        critic = context.result("critic")
        if critic is not None and hasattr(critic, "verdict"):
            blocking = [finding for finding in critic.findings if finding.blocking]
            warnings = [
                finding
                for finding in critic.findings
                if getattr(finding.severity, "value", finding.severity)
                == "warning"
            ]
            details = "; ".join(
                f"{finding.code} ({finding.responsible_step})"
                for finding in critic.findings[:3]
            )
            sections.append(
                ReportSection(
                    title="Critic review",
                    body=(
                        f"verdict={critic.verdict.value}; "
                        f"blocking={len(blocking)}, warnings={len(warnings)}"
                        + (f"; {details}" if details else ".")
                    ),
                    status="ok" if critic.verdict.value != "REJECTED" else "error",
                )
            )
        documentation = context.result("documentation")
        if documentation is not None and hasattr(documentation, "sections"):
            ai_label = (
                "rejected and replaced deterministically"
                if documentation.ai_rejected
                else ("present" if documentation.ai_explanation else "absent")
            )
            sections.append(
                ReportSection(
                    title="Documentation",
                    body=(
                        f"{len(documentation.sections)} section(s), "
                        f"{len(documentation.tables)} table(s); "
                        f"AI explanation {ai_label}."
                    ),
                    status="info",
                )
            )
        headline = (
            "Structured design plan completed with no blocking validation issues."
            if all(section.status != "error" for section in sections)
            else "Structured design plan completed with blocking validation issues."
        )
        return WorkflowReport(headline=headline, sections=sections)


def default_agents() -> dict[str, BaseAgent]:
    """Return one instance of every standard agent, keyed by name."""
    from .critic import CriticAgent
    from .documentation import DocumentationAgent
    from .security_agent import SecurityAgent

    agents: list[BaseAgent] = [
        RequirementsAgent(),
        TopologyAgent(),
        IpVlanAgent(),
        RoutingAgent(),
        ValidationAgent(),
        SimulationAgent(),
        OptimizationAgent(),
        RevalidationAgent(),
        SecurityAgent(),
        CriticAgent(),
        DocumentationAgent(),
        ReportAgent(),
    ]
    return {agent.name: agent for agent in agents}


def task_summary(value: object) -> str:
    """Return a compact summary helper for report/trace consumers."""
    return summarize(value)


__all__ = [
    "IpVlanAgent",
    "IpVlanInput",
    "IpVlanOutput",
    "OptimizationAgent",
    "OptimizationInput",
    "OptimizationOutput",
    "ReportAgent",
    "ReportInput",
    "ReportSection",
    "RequirementsAgent",
    "RequirementsInput",
    "RequirementsOutput",
    "RevalidationAgent",
    "RevalidationInput",
    "RevalidationOutput",
    "RoutingAgent",
    "RoutingInput",
    "RoutingOutput",
    "SimulationAgent",
    "SimulationInput",
    "SimulationOutput",
    "TopologyAgent",
    "TopologyInput",
    "TopologyOutput",
    "ValidationAgent",
    "ValidationInput",
    "ValidationOutput",
    "WorkflowReport",
    "default_agents",
    "task_summary",
]
