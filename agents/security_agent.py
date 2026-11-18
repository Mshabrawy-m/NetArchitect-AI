"""Optional Security Agent for design-time security analysis.

The agent may call exactly one deterministic tool. Its verdict, risk, findings,
and posture come from that tool; a language model may only add a short prose
explanation that is labelled as non-authoritative. Numeric tokens in that prose
must already appear in the deterministic analysis or the prose is rejected.
"""

from __future__ import annotations

import json
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from config.limits import MAX_SECURITY_EXPLANATION_CHARS, MAX_SECURITY_FLOW_CHECKS
from core.exceptions import AgentValidationError, LLMError
from core.schemas.validation import Severity
from security import (
    SECURITY_DISCLAIMER,
    DisclosedModel,
    FlowRequest,
    RiskLevel,
    SecurityAnalysis,
    SecurityModel,
    SecurityPosture,
)
from services.llm.models import LLMMessage, MessageRole
from services.llm.provider import LLMProvider
from services.reporting.models import AIExplanation

from .base import AgentContext, BaseAgent

SECURITY_EXPLANATION_PROMPT = (
    "You explain a deterministic design-time network security assessment in "
    "plain language. Use only numbers that already appear in the supplied "
    "assessment; do not invent measurements, results, or thresholds. Do not "
    "scan or probe anything, do not describe vulnerabilities or attack steps, "
    "and do not suggest device commands. Do not change the verdict, risk, "
    "findings, or posture. Keep the explanation short."
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_FORBIDDEN_EXPLANATION_TERMS = (
    "attack",
    "cve-",
    "exploit",
    "penetration test",
    "vulnerability scan",
)


class SecurityGate(str, Enum):
    """Deterministic gate derived only from the security analysis."""

    passed = "PASSED"
    review = "REVIEW"
    rejected = "REJECTED"


class SecurityAgentInput(BaseModel):
    """Optional modeled flows and an optional explicit security model."""

    model_config = ConfigDict(extra="forbid")

    model: SecurityModel | None = None
    flows: tuple[FlowRequest, ...] = Field(
        default_factory=tuple,
        max_length=MAX_SECURITY_FLOW_CHECKS,
    )
    include_explanation: bool = True


class SecurityAgentOutput(DisclosedModel):
    """Deterministic security result with a separate, labelled AI note."""

    analysis: SecurityAnalysis
    gate: SecurityGate
    risk_score: int = Field(ge=0)
    risk_level: RiskLevel
    posture: SecurityPosture
    finding_codes: tuple[str, ...]
    deterministic_explanation: str
    ai_explanation: AIExplanation


class SecurityAgent(BaseAgent):
    """Run one allowlisted security tool and optionally label prose about it."""

    name = "security"
    responsibility = (
        "Analyze the modeled design's zones, policy, flows, findings, and risk "
        "with deterministic offline tools."
    )
    input_model = SecurityAgentInput
    output_model = SecurityAgentOutput
    allowed_tools = frozenset({"security_analysis"})

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    def run(
        self, payload: SecurityAgentInput, context: AgentContext
    ) -> SecurityAgentOutput:
        twin = context.current_twin
        if twin is None:
            raise AgentValidationError(
                "No digital twin is available for security analysis."
            )
        result = context.call_tool(
            "security_analysis",
            {
                "twin": twin,
                "model": payload.model,
                "flows": payload.flows,
            },
        )
        if not isinstance(result, SecurityAnalysis):
            raise AgentValidationError(
                "The security_analysis tool did not return a SecurityAnalysis."
            )
        gate = _gate_for(result)
        codes = tuple(finding.code for finding in result.findings)
        explanation = _deterministic_explanation(result, gate)
        ai_explanation = self._explain(payload, result, explanation)
        return SecurityAgentOutput(
            analysis=result,
            gate=gate,
            risk_score=result.risk.score,
            risk_level=result.risk.level,
            posture=result.summary.posture,
            finding_codes=codes,
            deterministic_explanation=explanation,
            ai_explanation=ai_explanation,
        )

    def replan(self, payload: BaseModel, issue: str) -> BaseModel | None:
        """Decline automatic changes: fixes require explicit user acceptance."""
        return None

    def _explain(
        self,
        payload: SecurityAgentInput,
        analysis: SecurityAnalysis,
        deterministic_explanation: str,
    ) -> AIExplanation:
        if not payload.include_explanation or self.provider is None:
            return AIExplanation()
        request_payload = {
            "disclaimer": SECURITY_DISCLAIMER,
            "posture": analysis.summary.posture.value,
            "risk_score": analysis.risk.score,
            "risk_level": analysis.risk.level.value,
            "risk_formula": analysis.risk.formula,
            "findings": [
                {
                    "code": finding.code,
                    "severity": finding.severity.value,
                    "explanation": finding.explanation,
                }
                for finding in analysis.findings
            ],
        }
        messages = [
            LLMMessage(role=MessageRole.system, content=SECURITY_EXPLANATION_PROMPT),
            LLMMessage(role=MessageRole.user, content=json.dumps(request_payload)),
        ]
        try:
            response = self.provider.complete(messages)
        except LLMError:
            return AIExplanation(
                note="The optional AI explanation was unavailable.",
            )
        except Exception:  # noqa: BLE001 - model prose must never fail a task
            return AIExplanation(
                note="The optional AI explanation was unavailable.",
            )
        text = (response.text or "").strip()
        if not text:
            return AIExplanation()
        allowed = _numeric_tokens(analysis.model_dump_json())
        if any(token not in allowed for token in _numeric_tokens(text)):
            return AIExplanation(
                text=deterministic_explanation,
                rejected=True,
                note=(
                    "The AI explanation was rejected because it contained a "
                    "number that does not match the deterministic analysis."
                ),
            )
        lowered = text.lower()
        if any(term in lowered for term in _FORBIDDEN_EXPLANATION_TERMS):
            return AIExplanation(
                text=deterministic_explanation,
                rejected=True,
                note=(
                    "The AI explanation was rejected because it contained "
                    "out-of-scope security content."
                ),
            )
        if len(text) > MAX_SECURITY_EXPLANATION_CHARS:
            return AIExplanation(
                text=deterministic_explanation,
                rejected=True,
                note="The AI explanation exceeded the configured length limit.",
            )
        return AIExplanation(text=text[:MAX_SECURITY_EXPLANATION_CHARS], provider_used=True)


def _gate_for(analysis: SecurityAnalysis) -> SecurityGate:
    if analysis.summary.posture is SecurityPosture.high_risk or any(
        finding.severity in {Severity.error, Severity.critical}
        for finding in analysis.findings
    ):
        return SecurityGate.rejected
    if (
        analysis.summary.posture is SecurityPosture.needs_review
        or analysis.risk.level is not RiskLevel.low
    ):
        return SecurityGate.review
    return SecurityGate.passed


def _deterministic_explanation(
    analysis: SecurityAnalysis, gate: SecurityGate
) -> str:
    return (
        f"Modeled design posture {analysis.summary.posture.value}; risk "
        f"{analysis.risk.score} ({analysis.risk.level.value}); "
        f"{len(analysis.findings)} finding(s); gate {gate.value}. "
        + SECURITY_DISCLAIMER
    )


def _numeric_tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group() for match in _NUMBER.finditer(text))


__all__ = [
    "SECURITY_EXPLANATION_PROMPT",
    "SecurityAgent",
    "SecurityAgentInput",
    "SecurityAgentOutput",
    "SecurityGate",
]
