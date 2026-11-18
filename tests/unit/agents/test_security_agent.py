"""Security Agent tests: one allowlisted tool and labelled optional prose."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents import (
    AgentContext,
    Clock,
    ExecutionTrace,
    SecurityAgent,
    SecurityAgentInput,
    SecurityGate,
    WorkflowPlan,
    WorkflowState,
    WorkflowTask,
    registry_with_defaults,
)
from core.exceptions import LLMProviderError, ToolNotAllowedError
from security import PolicyAction, RiskLevel, SecurityPosture
from services.llm.testing import FakeProvider
from services.reporting.models import AIExplanation
from tests.unit.security.design_helpers import hardened_design

DISCLAIMER = (
    "Modeled design-time assessment. Not a vulnerability scan, penetration "
    "test or audit."
)


def _run_agent(
    *,
    provider: FakeProvider | None = None,
    payload: SecurityAgentInput | None = None,
):
    twin, model = hardened_design()
    agent = SecurityAgent(provider)
    plan = WorkflowPlan(
        name="Security test",
        tasks=(WorkflowTask(id="security", agent=agent.name),),
    )
    clock = Clock(
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    state = WorkflowState(plan, baseline_accessor=lambda: twin, clock=clock)
    trace = ExecutionTrace(clock)
    context = AgentContext(
        agent=agent,
        state=state,
        registry=registry_with_defaults(),
        trace=trace,
        clock=clock,
    ).for_task("security")
    resolved = payload or SecurityAgentInput(
        model=model, include_explanation=provider is not None
    )
    output = agent.run(resolved, context)
    return output, trace, twin


def test_security_agent_has_exactly_one_allowlisted_tool() -> None:
    assert SecurityAgent.allowed_tools == frozenset({"security_analysis"})
    assert "security_analysis" in registry_with_defaults().names()


def test_security_agent_produces_deterministic_disclosed_output() -> None:
    output, trace, _ = _run_agent()
    again, _, _ = _run_agent()

    assert output.disclaimer == DISCLAIMER
    assert output.gate is SecurityGate.passed
    assert output.risk_score == 0
    assert output.risk_level is RiskLevel.low
    assert output.posture is SecurityPosture.hardened
    assert output.finding_codes == ()
    assert DISCLAIMER in output.deterministic_explanation
    assert output.analysis.model_dump_json() == again.analysis.model_dump_json()
    calls = [entry for entry in trace.entries if entry.action == "tool_call"]
    assert [entry.tool for entry in calls] == ["security_analysis"]
    assert all(entry.status == "ok" for entry in calls)


def test_security_gate_is_rejected_for_a_blocking_policy_finding() -> None:
    twin, model = hardened_design()
    assert twin is not None
    strict = model.model_copy(update={"default_action": PolicyAction.allow})
    output, _, _ = _run_agent(
        payload=SecurityAgentInput(model=strict, include_explanation=False)
    )

    assert output.gate is SecurityGate.rejected
    assert "POLICY-DEFAULT-ALLOW" in output.finding_codes
    assert output.risk_score == 6


def test_agent_replans_never_apply_a_fix_silently() -> None:
    agent = SecurityAgent()

    assert agent.replan(SecurityAgentInput(), "SEC-DW-001") is None


def test_disallowed_tool_is_rejected_by_the_context() -> None:
    twin, _ = hardened_design()
    agent = SecurityAgent()
    plan = WorkflowPlan(
        name="Security allowlist test",
        tasks=(WorkflowTask(id="security", agent="security"),),
    )
    clock = Clock(
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    state = WorkflowState(plan, baseline_accessor=lambda: twin, clock=clock)
    context = AgentContext(
        agent=agent,
        state=state,
        registry=registry_with_defaults(),
        trace=ExecutionTrace(clock),
        clock=clock,
    ).for_task("security")

    with pytest.raises(ToolNotAllowedError, match="not in this agent's allowlist"):
        context.call_tool("twin_validate", {"twin": twin})


def test_accepted_ai_explanation_is_labelled_and_bounded() -> None:
    provider = FakeProvider(
        ["The modeled risk score is 0, so the modeled posture is hardened."]
    )
    output, _, _ = _run_agent(provider=provider)

    assert output.ai_explanation.provider_used is True
    assert output.ai_explanation.rejected is False
    assert output.ai_explanation.label == (
        "AI-generated text; not a source of design data."
    )
    assert "modeled risk score" in output.ai_explanation.text
    assert output.analysis.risk.score == 0


def test_ai_explanation_with_an_invented_number_is_rejected() -> None:
    provider = FakeProvider(["The modeled risk score is 987654321."])

    output, _, _ = _run_agent(provider=provider)

    assert isinstance(output.ai_explanation, AIExplanation)
    assert output.ai_explanation.rejected is True
    assert output.ai_explanation.text == output.deterministic_explanation
    assert "number that does not match" in output.ai_explanation.note


def test_ai_provider_failure_never_changes_the_deterministic_result() -> None:
    provider = FakeProvider([LLMProviderError("provider unavailable")])

    output, _, _ = _run_agent(provider=provider)

    assert output.ai_explanation.provider_used is False
    assert output.ai_explanation.rejected is False
    assert "unavailable" in output.ai_explanation.note
    assert output.gate is SecurityGate.passed
    assert output.risk_score == 0


def test_security_agent_has_no_execution_or_network_escape_hatches() -> None:
    import agents.security_agent as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "eval(",
        "exec(",
        "http.client",
        "httpx",
        "nmap",
        "requests",
        "scapy",
        "socket",
        "subprocess",
        "urllib",
    ):
        assert forbidden not in source
