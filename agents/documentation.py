"""Documentation Agent (Phase 10c).

The agent collects the *validated* results of a completed workflow into one
typed report. It never recalculates a design value: every number it prints is
copied from a deterministic task result and carries the step and tool that
produced it.

The optional language model may only add a short plain-language explanation.
That explanation is clearly separated from the deterministic report, and any
numeric token that does not match a computed value causes the text to be
rejected and replaced with the deterministic summary. No PDF is produced; the
supported exports are JSON, CSV, and Markdown.
"""

from __future__ import annotations

import csv
import io
import json
import re

from pydantic import BaseModel, Field

from config.limits import MAX_DOCUMENTATION_EXPLANATION_CHARS
from core.exceptions import LLMError
from core.schemas.requirements import NetworkRequirements
from services.llm.models import LLMMessage, MessageRole
from services.llm.provider import LLMProvider
from simulation import MODEL_NOTE

from .base import AgentContext, BaseAgent
from .critic import CriticOutput
from .network_agents import (
    IpVlanOutput,
    OptimizationOutput,
    RequirementsOutput,
    RoutingOutput,
    SimulationOutput,
    TopologyOutput,
)
from .planning import departments, redundancy_requested

DOCUMENTATION_SYSTEM_PROMPT = (
    "You explain a deterministic network-design report in plain language. "
    "Use only numbers that already appear in the report; do not invent "
    "measurements or thresholds. Do not change the stated verdict and do not "
    "claim the design is valid beyond that verdict. Keep the explanation short."
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class DocumentationInput(BaseModel):
    """Optional requirements fallback when the requirements task is absent."""

    requirements: NetworkRequirements | None = None


class DocumentValue(BaseModel):
    """One computed number together with its deterministic provenance."""

    label: str
    value: str
    step: str
    tool: str = ""


class DocumentSection(BaseModel):
    """One prose section whose numbers are listed with provenance."""

    title: str
    body: str
    step: str
    tool: str = ""
    values: list[DocumentValue] = Field(default_factory=list)


class DocumentTable(BaseModel):
    """One table copied from a single deterministic task result."""

    title: str
    columns: list[str]
    rows: list[list[str]] = Field(default_factory=list)
    step: str
    tool: str = ""
    note: str = ""


class DocumentationTraceEntry(BaseModel):
    """One execution-trace row copied from the workflow trace."""

    step: int
    agent: str
    action: str
    status: str
    attempt: int
    tool: str = ""
    duration_seconds: float


class DocumentationOutput(BaseModel):
    """The complete documentation report and its optional model note."""

    title: str
    summary: str
    verdict: str
    sections: list[DocumentSection] = Field(default_factory=list)
    tables: list[DocumentTable] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    trace: list[DocumentationTraceEntry] = Field(default_factory=list)
    deterministic_explanation: str
    ai_explanation: str = ""
    ai_rejected: bool = False
    ai_note: str = ""
    provider_used: bool = False


def _site_list(requirements: NetworkRequirements) -> list[object]:
    facts = requirements.user_provided
    if facts.organization is not None and facts.organization.sites:
        return list(facts.organization.sites)
    return list(facts.sites)


def _topology_choice(
    requirements: NetworkRequirements,
) -> tuple[str, str]:
    """Return a deterministic topology choice and its rationale."""
    facts = requirements.user_provided
    if facts.device_requirements:
        return (
            "User-supplied device and link set",
            (
                "The design uses the devices and links supplied in the structured "
                "requirements without substituting a generated topology."
            ),
        )
    if len(_site_list(requirements)) > 1:
        return (
            "Multi-site campus with a WAN ring",
            (
                "Each site is generated from the documented site policy, and the "
                "site cores are joined in a ring so the whole design is one "
                "connected graph."
            ),
        )
    department_count = len(departments(requirements))
    if department_count <= 4 and not redundancy_requested(requirements):
        return (
            "Single-site access star",
            (
                "A site with at most four departments and no resilience request is "
                "represented by a star because it has the fewest links while "
                "remaining connected."
            ),
        )
    return (
        "Single-site hierarchical campus",
        "More departments or an explicit resilience request selects the "
        "three-tier campus policy with distribution and access layers"
        + (" and redundant uplinks." if redundancy_requested(requirements) else "."),
    )


def _number(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _numeric_values(text: str) -> list[float]:
    return [float(match.group()) for match in _NUMBER.finditer(text)]


class DocumentationAgent(BaseAgent):
    """Assemble a traceable report from validated workflow results."""

    name = "documentation"
    responsibility = (
        "Collect validated results into a provenance-tagged report with "
        "assumptions, limitations, trace, and optional clearly labelled AI text."
    )
    input_model = DocumentationInput
    output_model = DocumentationOutput
    allowed_tools = frozenset()

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    def run(
        self, payload: DocumentationInput, context: AgentContext
    ) -> DocumentationOutput:
        requirements = self._requirements(payload, context)
        sections: list[DocumentSection] = []
        tables: list[DocumentTable] = []

        summary = self._summary(requirements, context)
        self._requirements_section(requirements, sections)
        self._topology_section(requirements, context, sections)
        self._ip_section(context, sections, tables)
        self._routing_section(context, sections, tables)
        self._simulation_section(context, sections, tables)
        self._optimization_section(context, sections, tables)
        self._findings_section(context, sections, tables)
        critic = context.result("critic")
        verdict = (
            critic.verdict.value
            if isinstance(critic, CriticOutput)
            else "not reviewed"
        )

        trace = [
            DocumentationTraceEntry(
                step=entry.step,
                agent=entry.agent,
                action=entry.action,
                status=entry.status,
                attempt=entry.attempt,
                tool=entry.tool,
                duration_seconds=entry.duration_seconds,
            )
            for entry in context.state.trace.entries
        ]
        tables.append(
            DocumentTable(
                title="Execution trace",
                columns=[
                    "Step",
                    "Agent",
                    "Action",
                    "Status",
                    "Attempt",
                    "Tool",
                    "Duration (s)",
                ],
                rows=[
                    [
                        str(entry.step),
                        entry.agent,
                        entry.action,
                        entry.status,
                        str(entry.attempt),
                        entry.tool or "-",
                        _number(entry.duration_seconds),
                    ]
                    for entry in trace
                ],
                step="orchestrator",
                tool="execution_trace",
                note="Every task attempt and tool call recorded by the orchestrator.",
            )
        )

        assumptions = self._assumptions(requirements, context)
        limitations = self._limitations(context)
        ai_explanation, ai_rejected, ai_note, provider_used = self._explain(
            summary,
            sections,
            tables,
            assumptions,
            limitations,
            verdict,
        )
        return DocumentationOutput(
            title="NetArchitect AI design report",
            summary=summary,
            verdict=verdict,
            sections=sections,
            tables=tables,
            assumptions=assumptions,
            limitations=limitations,
            trace=trace,
            deterministic_explanation=summary,
            ai_explanation=ai_explanation,
            ai_rejected=ai_rejected,
            ai_note=ai_note,
            provider_used=provider_used,
        )

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    @staticmethod
    def _requirements(
        payload: DocumentationInput, context: AgentContext
    ) -> NetworkRequirements:
        output = context.result("requirements")
        if isinstance(output, RequirementsOutput):
            return output.requirements
        if payload.requirements is not None:
            return payload.requirements
        raise ValueError("No requirements result is available for documentation.")

    @staticmethod
    def _summary(
        requirements: NetworkRequirements, context: AgentContext
    ) -> str:
        facts = requirements.user_provided
        sites = len(_site_list(requirements))
        department_count = len(departments(requirements))
        devices = 0
        links = 0
        topology = context.result("topology")
        if isinstance(topology, TopologyOutput):
            devices = len(topology.topology.devices)
            links = len(topology.topology.links)
        critic = context.result("critic")
        verdict = (
            critic.verdict.value
            if isinstance(critic, CriticOutput)
            else "not reviewed"
        )
        return (
            f"{sites} site(s), {department_count} department(s), "
            f"{facts.total_user_count} reported user(s); {devices} device(s) "
            f"and {links} link(s); critic verdict {verdict}."
        )

    @staticmethod
    def _requirements_section(
        requirements: NetworkRequirements, sections: list[DocumentSection]
    ) -> None:
        facts = requirements.user_provided
        sites = len(_site_list(requirements))
        department_count = len(departments(requirements))
        sections.append(
            DocumentSection(
                title="Requirements",
                body=(
                    "The deterministic workflow used the structured requirements "
                    "only. User facts and system assumptions are reported "
                    "separately below."
                ),
                step="requirements",
                tool="requirements_validate",
                values=[
                    DocumentValue(
                        label="Sites",
                        value=str(sites),
                        step="requirements",
                        tool="requirements_validate",
                    ),
                    DocumentValue(
                        label="Departments",
                        value=str(department_count),
                        step="requirements",
                        tool="requirements_validate",
                    ),
                    DocumentValue(
                        label="Reported users",
                        value=str(facts.total_user_count),
                        step="requirements",
                        tool="requirements_validate",
                    ),
                ],
            )
        )

    @staticmethod
    def _topology_section(
        requirements: NetworkRequirements,
        context: AgentContext,
        sections: list[DocumentSection],
    ) -> None:
        topology = context.result("topology")
        if not isinstance(topology, TopologyOutput):
            return
        choice, rationale = _topology_choice(requirements)
        sections.append(
            DocumentSection(
                title="Topology",
                body=f"Choice: {choice}. Rationale: {rationale}",
                step="topology",
                tool="topology_from_requirements",
                values=[
                    DocumentValue(
                        label="Devices",
                        value=str(len(topology.topology.devices)),
                        step="topology",
                        tool="topology_from_requirements",
                    ),
                    DocumentValue(
                        label="Links",
                        value=str(len(topology.topology.links)),
                        step="topology",
                        tool="topology_from_requirements",
                    ),
                    DocumentValue(
                        label="Connected components",
                        value=str(topology.connectivity.component_count),
                        step="topology",
                        tool="topology_connectivity",
                    ),
                ],
            )
        )

    @staticmethod
    def _ip_section(
        context: AgentContext,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
    ) -> None:
        ip_output = context.result("ip_vlan")
        if not isinstance(ip_output, IpVlanOutput):
            return
        plan = ip_output.plan
        vlan_count = (
            0 if plan.vlan_plan is None else len(plan.vlan_plan.assignments)
        )
        sections.append(
            DocumentSection(
                title="IP addressing and VLANs",
                body=(
                    "VLSM allocates one subnet per planning department and the "
                    "VLAN planner assigns one VLAN id per department."
                ),
                step="ip_vlan",
                tool="ip_plan_from_requirements",
                values=[
                    DocumentValue(
                        label="Base network",
                        value=plan.base_network,
                        step="ip_vlan",
                        tool="ip_plan_from_requirements",
                    ),
                    DocumentValue(
                        label="Subnets",
                        value=str(len(plan.subnets)),
                        step="ip_vlan",
                        tool="ip_plan_from_requirements",
                    ),
                    DocumentValue(
                        label="VLANs",
                        value=str(vlan_count),
                        step="ip_vlan",
                        tool="plan_vlans",
                    ),
                ],
            )
        )
        if plan.vlan_plan is not None:
            tables.append(
                DocumentTable(
                    title="Addressing and VLAN allocation",
                    columns=["Department", "Subnet", "VLAN", "Purpose"],
                    rows=[
                        [
                            assignment.department,
                            str(assignment.network),
                            str(assignment.vlan_id),
                            assignment.purpose or "-",
                        ]
                        for assignment in plan.vlan_plan.assignments
                    ],
                    step="ip_vlan",
                    tool="ip_plan_from_requirements",
                )
            )
        twin = context.current_twin
        scopes = () if twin is None else twin.dhcp_scopes
        tables.append(
            DocumentTable(
                title="DHCP scopes",
                columns=["Scope", "Network", "Gateway", "Range", "Lease (minutes)"],
                rows=[
                    [
                        scope.name,
                        str(scope.network),
                        str(scope.gateway) if scope.gateway is not None else "-",
                        (
                            f"{scope.start_address}-{scope.end_address}"
                            if scope.start_address is not None
                            and scope.end_address is not None
                            else "-"
                        ),
                        str(scope.lease_minutes),
                    ]
                    for scope in scopes
                ],
                step="ip_vlan",
                tool="working_twin_build",
                note=(
                    "No DHCP scopes are modeled by the current deterministic "
                    "policy."
                    if not scopes
                    else "DHCP scopes copied from the derived working twin."
                ),
            )
        )

    @staticmethod
    def _routing_section(
        context: AgentContext,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
    ) -> None:
        routing = context.result("routing")
        if not isinstance(routing, RoutingOutput) or routing.path is None:
            return
        path = routing.path
        sections.append(
            DocumentSection(
                title="Routing",
                body=(
                    "The routing engine returns the deterministic lowest-cost "
                    "path between the first and last device in id order."
                ),
                step="routing",
                tool="routing_path",
                values=[
                    DocumentValue(
                        label="Reachable",
                        value=str(path.reachable),
                        step="routing",
                        tool="routing_path",
                    ),
                    DocumentValue(
                        label="Total cost",
                        value=_number(path.total_cost),
                        step="routing",
                        tool="routing_path",
                    ),
                    DocumentValue(
                        label="Hops",
                        value=str(path.hop_count),
                        step="routing",
                        tool="routing_path",
                    ),
                ],
            )
        )
        tables.append(
            DocumentTable(
                title="Routing path",
                columns=["Source", "Destination", "Reachable", "Total cost", "Hops"],
                rows=[
                    [
                        routing.source or "-",
                        routing.destination or "-",
                        str(path.reachable),
                        _number(path.total_cost),
                        str(path.hop_count),
                    ]
                ],
                step="routing",
                tool="routing_path",
            )
        )

    @staticmethod
    def _findings_section(
        context: AgentContext,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
    ) -> None:
        critic = context.result("critic")
        findings: list[tuple[str, str, str, str, str]] = []
        if isinstance(critic, CriticOutput):
            for finding in critic.findings:
                findings.append(
                    (
                        finding.code,
                        finding.severity.value,
                        finding.responsible_step,
                        finding.explanation,
                        finding.remediation or "-",
                    )
                )
        if isinstance(critic, CriticOutput):
            blocking = sum(1 for finding in critic.findings if finding.blocking)
            sections.append(
                DocumentSection(
                    title="Critic review",
                    body=(
                        "The independent critic checked topology, addressing, "
                        "routing, modeled load, and redundancy. The deterministic "
                        f"verdict is {critic.verdict.value}."
                    ),
                    step="critic",
                    tool="critic_checks",
                    values=[
                        DocumentValue(
                            label="Blocking findings",
                            value=str(blocking),
                            step="critic",
                            tool="critic_checks",
                        ),
                        DocumentValue(
                            label="All findings",
                            value=str(len(critic.findings)),
                            step="critic",
                            tool="critic_checks",
                        ),
                    ],
                )
            )
        if findings:
            tables.append(
                DocumentTable(
                    title="Critic findings",
                    columns=[
                        "Code",
                        "Severity",
                        "Responsible step",
                        "Explanation",
                        "Remediation",
                    ],
                    rows=[list(row) for row in findings],
                    step="critic",
                    tool="critic_checks",
                )
            )

    @staticmethod
    def _simulation_section(
        context: AgentContext,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
    ) -> None:
        simulation = context.result("simulation")
        if not isinstance(simulation, SimulationOutput) or simulation.run is None:
            return
        comparison = simulation.run.comparison
        sections.append(
            DocumentSection(
                title="Simulation",
                body=simulation.summary,
                step="simulation",
                tool="simulation_run",
                values=[
                    DocumentValue(
                        label="Baseline served demands",
                        value=str(comparison.baseline_served_demand_count),
                        step="simulation",
                        tool="simulation_run",
                    ),
                    DocumentValue(
                        label="Scenario served demands",
                        value=str(comparison.scenario_served_demand_count),
                        step="simulation",
                        tool="simulation_run",
                    ),
                    DocumentValue(
                        label="Maximum utilization delta (percentage points)",
                        value=_number(comparison.max_utilization_delta_percent),
                        step="simulation",
                        tool="simulation_run",
                    ),
                ],
            )
        )
        baseline_state = simulation.run.baseline_state
        scenario_state = simulation.run.scenario_state
        tables.append(
            DocumentTable(
                title="Simulation comparison",
                columns=["Metric", "Baseline", "Scenario", "Delta"],
                rows=[
                    [
                        "Served demands",
                        str(comparison.baseline_served_demand_count),
                        str(comparison.scenario_served_demand_count),
                        str(
                            comparison.scenario_served_demand_count
                            - comparison.baseline_served_demand_count
                        ),
                    ],
                    [
                        "Served demand ratio",
                        _number(comparison.baseline_served_demand_ratio),
                        _number(comparison.scenario_served_demand_ratio),
                        _number(
                            comparison.scenario_served_demand_ratio
                            - comparison.baseline_served_demand_ratio
                        ),
                    ],
                    [
                        "Maximum utilization percent",
                        _number(baseline_state.max_utilization_percent),
                        _number(scenario_state.max_utilization_percent),
                        _number(comparison.max_utilization_delta_percent),
                    ],
                    [
                        "Congested links",
                        str(baseline_state.congested_link_count),
                        str(scenario_state.congested_link_count),
                        str(comparison.congested_link_delta),
                    ],
                ],
                step="simulation",
                tool="simulation_run",
                note="All values are modeled estimates from the stated assumptions.",
            )
        )

    @staticmethod
    def _optimization_section(
        context: AgentContext,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
    ) -> None:
        optimization = context.result("optimization")
        if not isinstance(optimization, OptimizationOutput) or optimization.run is None:
            return
        run = optimization.run
        best = run.best
        sections.append(
            DocumentSection(
                title="Optimization",
                body=optimization.summary,
                step="optimization",
                tool="optimization_run",
                values=[
                    DocumentValue(
                        label="Evaluations",
                        value=str(run.evaluations),
                        step="optimization",
                        tool="optimization_run",
                    ),
                    DocumentValue(
                        label="Baseline weighted score",
                        value=_number(run.baseline.weighted_score),
                        step="optimization",
                        tool="optimization_run",
                    ),
                    DocumentValue(
                        label="Best weighted score",
                        value=(
                            _number(best.evaluation.weighted_score)
                            if best is not None
                            else "n/a"
                        ),
                        step="optimization",
                        tool="optimization_run",
                    ),
                ],
            )
        )
        rows = [
            [
                "Seeded devices",
                str(run.baseline.metrics.device_count),
                str(best.evaluation.metrics.device_count) if best else "n/a",
            ],
            [
                "Selected links",
                str(run.baseline.metrics.link_count),
                str(best.evaluation.metrics.link_count) if best else "n/a",
            ],
            [
                "Served demands",
                str(run.baseline.metrics.served_demand_count),
                (
                    str(best.evaluation.metrics.served_demand_count)
                    if best
                    else "n/a"
                ),
            ],
            [
                "Maximum utilization percent",
                _number(run.baseline.metrics.max_utilization_percent),
                (
                    _number(best.evaluation.metrics.max_utilization_percent)
                    if best
                    else "n/a"
                ),
            ],
            [
                "Weighted score",
                _number(run.baseline.weighted_score),
                _number(best.evaluation.weighted_score) if best else "n/a",
            ],
        ]
        tables.append(
            DocumentTable(
                title="Optimization comparison",
                columns=["Metric", "Baseline", "Best candidate"],
                rows=rows,
                step="optimization",
                tool="optimization_run",
                note="Baseline and best-candidate modeled metrics, not measurements.",
            )
        )

    # ------------------------------------------------------------------
    # Assumptions, limitations, optional explanation
    # ------------------------------------------------------------------
    @staticmethod
    def _assumptions(
        requirements: NetworkRequirements, context: AgentContext
    ) -> list[str]:
        assumptions = [
            f"{assumption.description}"
            + (f" Rationale: {assumption.rationale}" if assumption.rationale else "")
            for assumption in requirements.assumptions
        ]
        ip_output = context.result("ip_vlan")
        if isinstance(ip_output, IpVlanOutput) and ip_output.demands.note:
            assumptions.append(ip_output.demands.note)
        return assumptions

    @staticmethod
    def _limitations(context: AgentContext) -> list[str]:
        limitations = [
            (
                "All utilization, demand, and cost figures are modeled estimates "
                "from the stated assumptions, not measurements."
            ),
            MODEL_NOTE,
            (
                "Free-text interpretation is optional; the deterministic workflow "
                "uses only structured requirements and typed engine results."
            ),
            "Exports are JSON, CSV, and Markdown only; no PDF is produced.",
        ]
        if isinstance(context.result("optimization"), OptimizationOutput):
            limitations.append(
                "Optimization uses a bounded deterministic search; the best "
                "candidate is the best found within the configured limits, not a "
                "proof of a global optimum."
            )
        return limitations

    def _explain(
        self,
        summary: str,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
        assumptions: list[str],
        limitations: list[str],
        verdict: str,
    ) -> tuple[str, bool, str, bool]:
        if self.provider is None:
            return "", False, "", False
        payload = {
            "summary": summary,
            "verdict": verdict,
            "sections": [
                {"title": section.title, "body": section.body} for section in sections
            ],
            "tables": [
                {"title": table.title, "rows": table.rows[:20]}
                for table in tables
                if table.title != "Execution trace"
            ],
            "assumptions": assumptions,
            "limitations": limitations,
        }
        messages = [
            LLMMessage(role=MessageRole.system, content=DOCUMENTATION_SYSTEM_PROMPT),
            LLMMessage(role=MessageRole.user, content=json.dumps(payload)),
        ]
        try:
            response = self.provider.complete(messages)
        except LLMError:
            return "", False, "The optional AI explanation was unavailable.", False
        except Exception:  # noqa: BLE001 - the model note must never fail a task
            return "", False, "The optional AI explanation was unavailable.", False
        text = (response.text or "").strip()
        if not text:
            return "", False, "", False
        allowed = self._computed_numbers(
            summary, sections, tables, assumptions, limitations
        )
        if any(token not in allowed for token in _numeric_values(text)):
            return (
                summary,
                True,
                (
                    "The model explanation was rejected because it contained a "
                    "number that does not match the computed results; the "
                    "deterministic summary is shown instead."
                ),
                True,
            )
        return text[:MAX_DOCUMENTATION_EXPLANATION_CHARS], False, "", True

    @staticmethod
    def _computed_numbers(
        summary: str,
        sections: list[DocumentSection],
        tables: list[DocumentTable],
        assumptions: list[str],
        limitations: list[str],
    ) -> set[float]:
        texts: list[str] = [summary, *assumptions, *limitations]
        for section in sections:
            texts.extend([section.body, *(value.value for value in section.values)])
        for table in tables:
            if table.title == "Execution trace":
                continue
            texts.extend(cell for row in table.rows for cell in row)
        return {
            round(value, 6)
            for text in texts
            for value in _numeric_values(text)
        }


def export_json(report: DocumentationOutput) -> str:
    """Return the report as deterministic, sorted JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)


def export_csv(report: DocumentationOutput) -> str:
    """Return every table cell as a CSV row with step/tool provenance."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["table", "row", "column", "value", "step", "tool"])
    for table in report.tables:
        for row_index, row in enumerate(table.rows, start=1):
            for column_index, value in enumerate(row):
                column = (
                    table.columns[column_index]
                    if column_index < len(table.columns)
                    else f"column_{column_index + 1}"
                )
                writer.writerow(
                    [
                        table.title,
                        row_index,
                        column,
                        value,
                        table.step,
                        table.tool,
                    ]
                )
    return buffer.getvalue()


def export_markdown(report: DocumentationOutput) -> str:
    """Return the report as deterministic Markdown."""
    lines: list[str] = [f"# {report.title}", "", report.summary, ""]
    for section in report.sections:
        lines.extend([f"## {section.title}", "", section.body, ""])
        if section.values:
            lines.extend(
                [
                    "| Value | Result | Source |",
                    "| --- | --- | --- |",
                    *[
                        f"| {value.label} | {value.value} | "
                        f"{value.step}/{value.tool or '-'} |"
                        for value in section.values
                    ],
                    "",
                ]
            )
    for table in report.tables:
        if table.note:
            lines.extend([f"## {table.title}", "", f"_{table.note}_", ""])
        else:
            lines.extend([f"## {table.title}", ""])
        lines.append("| " + " | ".join(table.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in table.columns) + " |")
        for row in table.rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        lines.append(f"Source: `{table.step}/{table.tool or '-'}`")
        lines.append("")
    lines.extend(["## Assumptions", ""])
    lines.extend(f"- {item}" for item in report.assumptions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    lines.append("")
    if report.ai_explanation:
        label = "AI explanation (optional, model-written"
        label += ", rejected and replaced deterministically)" if report.ai_rejected else ")"
        lines.extend([f"## {label}", "", report.ai_explanation, ""])
        if report.ai_note:
            lines.extend([f"> {report.ai_note}", ""])
    lines.extend(
        [
            "## Execution trace",
            "",
            "| Step | Agent | Action | Status | Attempt | Tool | Duration (s) |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            *[
                f"| {entry.step} | {entry.agent} | {entry.action} | "
                f"{entry.status} | {entry.attempt} | {entry.tool or '-'} | "
                f"{_number(entry.duration_seconds)} |"
                for entry in report.trace
            ],
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "DOCUMENTATION_SYSTEM_PROMPT",
    "DocumentSection",
    "DocumentTable",
    "DocumentValue",
    "DocumentationAgent",
    "DocumentationInput",
    "DocumentationOutput",
    "DocumentationTraceEntry",
    "export_csv",
    "export_json",
    "export_markdown",
]
