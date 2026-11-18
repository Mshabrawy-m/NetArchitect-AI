"""Critic handling of optional design-time security results."""

from __future__ import annotations

from datetime import UTC, datetime

from agents import (
    AgentContext,
    Clock,
    CriticAgent,
    CriticInput,
    CriticVerdict,
    ExecutionTrace,
    Orchestrator,
    SecurityAgent,
    SecurityAgentInput,
    WorkflowPlan,
    WorkflowState,
    WorkflowStopReason,
    WorkflowTask,
    registry_with_defaults,
    responsible_step_for,
)
from core.schemas.validation import Severity
from security import PolicyAction, RiskLevel
from tests.unit.security.design_helpers import hardened_design
from tests.unit.security.helpers import make_rule


def _security_output(model):
    twin, _ = hardened_design()
    agent = SecurityAgent()
    plan = WorkflowPlan(
        name="Security setup", tasks=(WorkflowTask(id="security", agent="security"),)
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
    return agent.run(
        SecurityAgentInput(model=model, include_explanation=False), context
    )


def _run_critic(security_output):
    twin, _ = hardened_design()
    agent = CriticAgent()
    plan = WorkflowPlan(
        name="Critic security test",
        tasks=(WorkflowTask(id="critic", agent="critic"),),
    )
    clock = Clock(
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    state = WorkflowState(plan, baseline_accessor=lambda: twin, clock=clock)
    state.results["security"] = security_output
    trace = ExecutionTrace(clock)
    context = AgentContext(
        agent=agent,
        state=state,
        registry=registry_with_defaults(),
        trace=trace,
        clock=clock,
    ).for_task("critic")
    return agent.run(CriticInput(), context), trace


def test_security_finding_codes_are_mapped_to_the_security_step() -> None:
    assert responsible_step_for("SEC-DW-001") == "security"
    assert responsible_step_for("SEC-DW-009") == "security"
    assert responsible_step_for("POLICY-DEFAULT-ALLOW") == "security"
    assert responsible_step_for("POLICY-SHADOWED") == "security"
    assert responsible_step_for("security_high_risk") == "security"


def test_security_error_rejects_the_critic_and_maps_to_security() -> None:
    _, model = hardened_design()
    strict = model.model_copy(update={"default_action": PolicyAction.allow})

    output, trace = _run_critic(_security_output(strict))

    assert output.verdict is CriticVerdict.rejected
    assert output.is_valid is False
    assert "POLICY-DEFAULT-ALLOW" in output.issue_codes
    assert output.replan_target == "security"
    finding = next(
        item
        for item in output.findings
        if item.code == "POLICY-DEFAULT-ALLOW"
    )
    assert finding.severity is Severity.error
    assert finding.blocking is True
    assert finding.responsible_step == "security"
    security_calls = [entry for entry in trace.entries if entry.tool == "security_analysis"]
    assert len(security_calls) == 1
    assert security_calls[0].status == "ok"


def test_high_band_risk_adds_a_nonblocking_warning() -> None:
    _, model = hardened_design()
    extra_rules = []
    for index in range(8):
        extra_rules.extend(
            (
                make_rule(
                    f"shadow-a-{index:02d}",
                    order=100 + 2 * index,
                    src_zone="z-user",
                    dst_zone="z-dmz",
                    services=("http",),
                    action=PolicyAction.deny,
                ),
                make_rule(
                    f"shadow-b-{index:02d}",
                    order=101 + 2 * index,
                    src_zone="z-user",
                    dst_zone="z-dmz",
                    services=("http",),
                    action=PolicyAction.allow,
                ),
            )
        )
    high_risk_model = model.model_copy(update={"rules": model.rules + tuple(extra_rules)})
    security_output = _security_output(high_risk_model)
    assert security_output.risk_level is RiskLevel.high

    output, _ = _run_critic(security_output)

    warning = next(
        item for item in output.findings if item.code == "security_high_risk"
    )
    assert warning.severity is Severity.warning
    assert warning.blocking is False
    assert warning.responsible_step == "security"
    assert output.verdict is CriticVerdict.approved_with_warnings
    assert output.is_valid is True
    assert output.issue_codes == []


def test_security_rejection_stops_a_selective_replan_without_silent_fixes() -> None:
    twin, model = hardened_design()
    strict = model.model_copy(update={"default_action": PolicyAction.allow})
    plan = WorkflowPlan(
        name="Security rejection plan",
        tasks=(
            WorkflowTask(
                id="security",
                agent="security",
                payload={"model": strict, "include_explanation": False},
            ),
            WorkflowTask(
                id="critic",
                agent="critic",
                dependencies=("security",),
            ),
        ),
    )

    state = Orchestrator(baseline_accessor=lambda: twin).run(plan)

    assert state.stop_reason is WorkflowStopReason.critic_rejected
    assert state.replans == 0
    assert state.tasks["critic"].attempts == 1
    assert "declined to re-plan" in state.error
    assert "security" in state.error
