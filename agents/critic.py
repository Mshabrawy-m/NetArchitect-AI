"""Independent Validation and Critic Agent (Phase 10b).

The critic derives its own verdict from deterministic tools. It never reads a
previous validation agent's ``is_valid`` flag and never accepts an LLM's claim
about validity: the verdict is computed in Python from the findings returned by
the topology, addressing, twin, routing, load, and SPOF tools.

An optional language model may add a short narrative note after the verdict is
fixed. That note is stored separately and cannot change the verdict, the
findings, the re-plan target, or any engineering number.
"""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel, Field

from config.limits import MAX_CRITIC_SUMMARY_CHARS
from core.exceptions import LLMError
from core.schemas.requirements import NetworkRequirements
from core.schemas.validation import Finding, Severity
from digital_twin import DigitalTwin, addressing_subnets
from security import RiskLevel, SecurityAnalysis
from services.llm.models import LLMMessage, MessageRole
from services.llm.provider import LLMProvider
from simulation import CongestionLevel

from .base import AgentContext, BaseAgent
from .network_agents import IpVlanOutput
from .planning import redundancy_requested

CRITIC_SUMMARY_PROMPT = (
    "You are given a deterministic network-design critic result. Write a short, "
    "factual summary for a network engineer. Do not change the verdict, do not "
    "describe the design as valid or invalid on your own authority, and do not "
    "invent values. The deterministic verdict and findings are authoritative."
)

# Finding code -> workflow task that owns the correction.
RESPONSIBLE_STEPS: dict[str, str] = {
    "subnet_overlap": "ip_vlan",
    "duplicate_ip": "ip_vlan",
    "twin_vlan_subnet_missing": "ip_vlan",
    "twin_duplicate_vlan_id": "ip_vlan",
    "demand_unserved": "ip_vlan",
    "topology_disconnected": "topology",
    "twin_topology_disconnected": "topology",
    "isolated_device": "topology",
    "routing_unreachable": "topology",
    "twin_nonpositive_link_capacity": "topology",
    "spof_device": "topology",
    "spof_link": "topology",
    "missing_redundancy": "topology",
    "link_overloaded": "optimization",
    "link_critical_utilization": "optimization",
    "no_working_twin": "topology",
}


def responsible_step_for(code: str) -> str:
    """Return the workflow task that owns a finding code."""
    known = RESPONSIBLE_STEPS.get(code)
    if known is not None:
        return known
    if code.startswith(("SEC-", "POLICY-")):
        return "security"
    if code == "security_high_risk":
        return "security"
    return "revalidation"


class CriticVerdict(str, Enum):
    """Deterministic design verdict."""

    approved = "APPROVED"
    approved_with_warnings = "APPROVED_WITH_WARNINGS"
    rejected = "REJECTED"


class CriticInput(BaseModel):
    """Optional requirements used only for the deterministic redundancy check."""

    requirements: NetworkRequirements | None = None


class CriticFinding(BaseModel):
    """One independent critic finding with a responsible workflow step."""

    code: str
    severity: Severity
    entities: list[str] = Field(default_factory=list)
    explanation: str
    remediation: str = ""
    responsible_step: str
    blocking: bool


class CriticOutput(BaseModel):
    """Verdict, findings, and the optional non-authoritative model summary."""

    verdict: CriticVerdict
    findings: list[CriticFinding] = Field(default_factory=list)
    is_valid: bool
    issue_codes: list[str] = Field(default_factory=list)
    replan_target: str | None = None
    summary: str
    model_summary: str = ""
    provider_used: bool = False


class CriticAgent(BaseAgent):
    """Independently validate a design and return a deterministic verdict."""

    name = "critic"
    responsibility = (
        "Independently re-check topology, addressing, routing, capacity, and "
        "redundancy with deterministic tools, then return a verdict."
    )
    input_model = CriticInput
    output_model = CriticOutput
    allowed_tools = frozenset(
        {
            "topology_connectivity",
            "addressing_validate",
            "twin_validate",
            "routing_path",
            "twin_load_state",
            "spof_analysis",
            "security_analysis",
        }
    )

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    def run(self, payload: CriticInput, context: AgentContext) -> CriticOutput:
        """Run every independent check and compute the verdict deterministically."""
        findings: list[CriticFinding] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()

        def add(finding: CriticFinding) -> None:
            key = (finding.code, tuple(sorted(finding.entities)))
            if key in seen:
                return
            seen.add(key)
            findings.append(finding)

        def add_finding(
            *,
            code: str,
            severity: Severity,
            explanation: str,
            remediation: str = "",
            entities: list[str] | None = None,
            responsible_step: str | None = None,
        ) -> None:
            add(
                self._finding(
                    code=code,
                    severity=severity,
                    explanation=explanation,
                    remediation=remediation,
                    entities=entities,
                    responsible_step=responsible_step,
                )
            )

        def add_engine_finding(finding: Finding) -> None:
            add(
                CriticFinding(
                    code=finding.code,
                    severity=finding.severity,
                    entities=list(finding.affected_entities),
                    explanation=finding.explanation,
                    remediation=finding.remediation,
                    responsible_step=responsible_step_for(finding.code),
                    blocking=finding.severity in {Severity.error, Severity.critical},
                )
            )

        twin = context.current_twin
        if twin is None:
            add_finding(
                code="no_working_twin",
                severity=Severity.critical,
                explanation=(
                    "No derived or baseline digital twin is available for the "
                    "critic to inspect."
                ),
                remediation="Complete the topology and IP planning steps first.",
            )
        else:
            self._check_topology(twin, context, add_finding)
            self._check_addressing(context, twin, add_finding, add_engine_finding)
            self._check_twin(twin, context, add_engine_finding)
            self._check_routing(twin, context, add_finding)
            self._check_load(twin, context, add_finding)
            self._check_redundancy(payload, twin, context, add_finding)
            self._check_security(twin, context, add_engine_finding, add_finding)

        blocking = [finding for finding in findings if finding.blocking]
        warnings = [
            finding for finding in findings if finding.severity is Severity.warning
        ]
        if blocking:
            verdict = CriticVerdict.rejected
        elif warnings:
            verdict = CriticVerdict.approved_with_warnings
        else:
            verdict = CriticVerdict.approved

        issue_codes = sorted({finding.code for finding in blocking})
        replan_target = (
            blocking[0].responsible_step if blocking else None
        )
        summary = (
            f"{len(blocking)} blocking finding(s), {len(warnings)} warning(s); "
            f"verdict {verdict.value}."
        )
        model_summary, provider_used = self._model_summary(
            verdict,
            findings,
            issue_codes,
        )
        return CriticOutput(
            verdict=verdict,
            findings=findings,
            is_valid=verdict is not CriticVerdict.rejected,
            issue_codes=issue_codes,
            replan_target=replan_target,
            summary=summary,
            model_summary=model_summary,
            provider_used=provider_used,
        )

    # ------------------------------------------------------------------
    # Independent checks
    # ------------------------------------------------------------------
    @staticmethod
    def _check_topology(twin: DigitalTwin, context: AgentContext, add_finding) -> None:
        connectivity = context.call_tool(
            "topology_connectivity",
            {"topology": twin.topology},
        )
        if twin.topology.devices and not connectivity.is_connected:
            add_finding(
                code="topology_disconnected",
                severity=Severity.error,
                explanation=(
                    f"The topology has {connectivity.component_count} connected "
                    "component(s); not every device can reach every other device."
                ),
                remediation=(
                    "Add links between the components or remove unintentional "
                    "partitions before approving the design."
                ),
                entities=list(connectivity.isolated_device_ids),
                responsible_step="topology",
            )

    @staticmethod
    def _check_addressing(
        context: AgentContext,
        twin: DigitalTwin,
        add_finding,
        add_engine_finding,
    ) -> None:
        ip_output = context.result("ip_vlan")
        if isinstance(ip_output, IpVlanOutput):
            subnets = list(ip_output.plan.subnets)
        elif twin.addressing is not None:
            subnets = list(addressing_subnets(twin))
        else:
            return
        if not subnets:
            return
        report = context.call_tool("addressing_validate", {"subnets": subnets})
        for finding in report.findings:
            if finding.severity in {Severity.error, Severity.critical}:
                add_engine_finding(finding)

    @staticmethod
    def _check_twin(twin: DigitalTwin, context: AgentContext, add_engine_finding) -> None:
        report = context.call_tool("twin_validate", {"twin": twin})
        for finding in report.findings:
            if finding.code == "twin_topology_disconnected":
                continue
            add_engine_finding(finding)

    @staticmethod
    def _check_routing(twin: DigitalTwin, context: AgentContext, add_finding) -> None:
        devices = sorted(device.id for device in twin.topology.devices)
        if len(devices) < 2:
            return
        source, destination = devices[0], devices[-1]
        path = context.call_tool(
            "routing_path",
            {
                "topology": twin.topology,
                "source": source,
                "destination": destination,
            },
        )
        if not path.reachable:
            add_finding(
                code="routing_unreachable",
                severity=Severity.error,
                explanation=(
                    f"No path exists from {source} to {destination}: "
                    f"{path.reason or 'unreachable'}."
                ),
                remediation=(
                    "Restore connectivity between the endpoints or confirm that "
                    "the modeled partition is intentional."
                ),
                entities=[source, destination],
                responsible_step="topology",
            )

    @staticmethod
    def _check_load(twin: DigitalTwin, context: AgentContext, add_finding) -> None:
        state = context.call_tool("twin_load_state", {"twin": twin})
        for load in state.links:
            if load.level is CongestionLevel.overloaded:
                add_finding(
                    code="link_overloaded",
                    severity=Severity.error,
                    explanation=(
                        f"Link {load.link_id!r} is modeled at "
                        f"{load.utilization_percent:.2f}% utilization "
                        f"({load.load_mbps:.2f} of {load.capacity_mbps:.2f} Mbps)."
                    ),
                    remediation=(
                        "Increase link capacity, reduce modeled demand, or choose "
                        "a topology that distributes the load."
                    ),
                    entities=[load.link_id, *load.endpoints],
                    responsible_step="optimization",
                )
            elif load.level is CongestionLevel.critical:
                add_finding(
                    code="link_critical_utilization",
                    severity=Severity.warning,
                    explanation=(
                        f"Link {load.link_id!r} is modeled at "
                        f"{load.utilization_percent:.2f}% utilization, above the "
                        "critical threshold but not overloaded."
                    ),
                    remediation="Review capacity headroom before deployment.",
                    entities=[load.link_id, *load.endpoints],
                    responsible_step="optimization",
                )
        for demand in state.unserved_demands:
            add_finding(
                code="demand_unserved",
                severity=Severity.error,
                explanation=(
                    f"Demand {demand.name!r} from {demand.source} to "
                    f"{demand.destination} has no modeled path: {demand.reason}."
                ),
                remediation="Restore connectivity or remove the unreachable demand.",
                entities=[demand.name, demand.source, demand.destination],
                responsible_step="ip_vlan",
            )

    @staticmethod
    def _check_redundancy(
        payload: CriticInput,
        twin: DigitalTwin,
        context: AgentContext,
        add_finding,
    ) -> None:
        if payload.requirements is None:
            return
        if not redundancy_requested(payload.requirements):
            return
        report = context.call_tool(
            "spof_analysis",
            {"topology": twin.topology},
        )
        if not report.entries:
            return
        entities = sorted({entry.entity_id for entry in report.entries})
        add_finding(
            code="missing_redundancy",
            severity=Severity.error,
            explanation=(
                f"Redundancy was requested, but the topology has "
                f"{len(report.entries)} single point(s) of failure."
            ),
            remediation=(
                "Add independent paths or dual-homed devices so no single device "
                "or link partitions the design."
            ),
            entities=entities,
            responsible_step="topology",
        )

    @staticmethod
    def _check_security(
        twin: DigitalTwin,
        context: AgentContext,
        add_engine_finding,
        add_finding,
    ) -> None:
        """Re-run the offline security tool when an optional result exists."""
        security = context.result("security")
        previous = getattr(security, "analysis", None)
        if not isinstance(previous, SecurityAnalysis):
            return
        report = context.call_tool(
            "security_analysis",
            {
                "twin": twin,
                "model": previous.model,
                "flows": tuple(check.request for check in previous.flow_checks),
            },
        )
        if not isinstance(report, SecurityAnalysis):
            return
        for finding in report.findings:
            add_engine_finding(finding)
        if report.risk.level is RiskLevel.high:
            add_finding(
                code="security_high_risk",
                severity=Severity.warning,
                explanation=(
                    "The reproducible modeled risk score is in the high band "
                    f"({report.risk.score}): {report.risk.formula}"
                ),
                remediation=(
                    "Review the security findings and accept proposed rules only "
                    "after a design decision. This is a modeled assessment."
                ),
                entities=[finding.code for finding in report.findings],
                responsible_step="security",
            )

    # ------------------------------------------------------------------
    # Optional, non-authoritative model note
    # ------------------------------------------------------------------
    def _model_summary(
        self,
        verdict: CriticVerdict,
        findings: list[CriticFinding],
        issue_codes: list[str],
    ) -> tuple[str, bool]:
        if self.provider is None:
            return "", False
        payload = {
            "verdict": verdict.value,
            "blocking_codes": issue_codes,
            "findings": [
                {
                    "code": finding.code,
                    "severity": finding.severity.value,
                    "explanation": finding.explanation,
                }
                for finding in findings
            ],
        }
        messages = [
            LLMMessage(role=MessageRole.system, content=CRITIC_SUMMARY_PROMPT),
            LLMMessage(role=MessageRole.user, content=json.dumps(payload)),
        ]
        try:
            response = self.provider.complete(messages)
        except LLMError:
            return "", False
        except Exception:  # noqa: BLE001 - the model note must never fail a task
            return "", False
        text = (response.text or "").strip()
        return text[:MAX_CRITIC_SUMMARY_CHARS], bool(text)

    @staticmethod
    def _finding(
        *,
        code: str,
        severity: Severity,
        explanation: str,
        remediation: str = "",
        entities: list[str] | None = None,
        responsible_step: str | None = None,
    ) -> CriticFinding:
        return CriticFinding(
            code=code,
            severity=severity,
            entities=list(entities or []),
            explanation=explanation,
            remediation=remediation,
            responsible_step=responsible_step or responsible_step_for(code),
            blocking=severity in {Severity.error, Severity.critical},
        )


__all__ = [
    "CRITIC_SUMMARY_PROMPT",
    "RESPONSIBLE_STEPS",
    "CriticAgent",
    "CriticFinding",
    "CriticInput",
    "CriticOutput",
    "CriticVerdict",
    "responsible_step_for",
]
