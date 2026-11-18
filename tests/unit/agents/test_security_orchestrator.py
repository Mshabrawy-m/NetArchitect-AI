"""Optional security step in the structured workflow."""

from __future__ import annotations

from agents import (
    CriticVerdict,
    Orchestrator,
    SecurityAgent,
    SecurityAgentOutput,
    SecurityGate,
    WorkflowStopReason,
    build_standard_plan,
    run_structured_design,
)
from tests.unit.agents.helpers import sample_requirements


def test_security_step_is_opt_in_and_preserves_the_default_plan() -> None:
    default_plan = build_standard_plan()
    secure_plan = build_standard_plan(include_security=True)

    assert [task.id for task in default_plan.tasks] == [
        "requirements",
        "topology",
        "ip_vlan",
        "routing",
        "validation",
        "simulation",
        "optimization",
        "revalidation",
        "critic",
        "documentation",
        "report",
    ]
    assert [task.id for task in secure_plan.tasks] == [
        "requirements",
        "topology",
        "ip_vlan",
        "routing",
        "validation",
        "simulation",
        "optimization",
        "revalidation",
        "security",
        "critic",
        "documentation",
        "report",
    ]
    assert secure_plan.task("security").dependencies == ("revalidation",)
    assert secure_plan.task("critic").dependencies == (
        "revalidation",
        "security",
    )


def test_optional_security_step_runs_offline_and_feeds_the_critic() -> None:
    state = run_structured_design(sample_requirements(), include_security=True)

    # The sample design has a flat topology and no management zone, so the
    # deterministic security gate rejects it. The critic sees that result and
    # stops the workflow rather than silently applying any proposed fix.
    assert state.stop_reason is WorkflowStopReason.critic_rejected
    assert state.steps == 10
    assert state.replans == 0
    assert "security" in state.results
    assert "critic" in state.results
    assert "documentation" not in state.results
    assert "report" not in state.results

    security = state.results["security"]
    assert isinstance(security, SecurityAgentOutput)
    assert security.gate is SecurityGate.rejected
    assert "SEC-DW-001" in security.finding_codes
    assert security.analysis.disclaimer == (
        "Modeled design-time assessment. Not a vulnerability scan, penetration "
        "test or audit."
    )

    critic = state.results["critic"]
    assert critic.verdict is CriticVerdict.rejected
    assert "SEC-DW-001" in critic.issue_codes
    assert critic.replan_target == "security"
    assert all(
        finding.responsible_step == "security"
        for finding in critic.findings
        if finding.code.startswith(("SEC-", "POLICY-"))
    )

    tool_calls = [
        entry for entry in state.trace.entries if entry.action == "tool_call"
    ]
    security_calls = [entry for entry in tool_calls if entry.tool == "security_analysis"]
    assert len(security_calls) >= 2  # agent run plus the critic's independent re-check
    assert all(entry.status == "ok" for entry in security_calls)
    assert "declined to re-plan" in state.error
    assert "security" in state.error


def test_default_workflow_still_has_eleven_steps_and_no_security_result() -> None:
    state = run_structured_design(sample_requirements())

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.steps == 11
    assert state.results.get("security") is None
    assert isinstance(Orchestrator().agents["security"], SecurityAgent)
