"""Independent Critic Agent tests (Phase 10b).

Every test runs without a network or a real provider. The critic is given a
digital twin directly so each deterministic check can be exercised in isolation.
The scripted :class:`FakeProvider` proves that model text never changes the
verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agents import (
    AgentContext,
    Clock,
    CriticAgent,
    CriticInput,
    CriticVerdict,
    DemandPlan,
    ExecutionTrace,
    IpPlanResult,
    IpVlanOutput,
    Orchestrator,
    WorkflowPlan,
    WorkflowState,
    WorkflowStopReason,
    WorkflowTask,
    registry_with_defaults,
    responsible_step_for,
)
from agents.network_agents import default_agents
from core.exceptions import LLMProviderError
from core.schemas.addressing import Subnet
from core.schemas.requirements import NetworkRequirements, UserFacts
from digital_twin import DigitalTwin
from services.llm.testing import FakeProvider
from tests.unit.agents.helpers import sample_requirements
from tests.unit.simulation.helpers import (
    diamond_twin,
    line_twin,
    make_demand,
    make_topology,
    make_twin,
)


def disconnected_twin() -> DigitalTwin:
    """Two devices with no link between them."""
    return make_twin(make_topology(["a", "b"], []))


def run_critic(
    twin: DigitalTwin | None,
    *,
    requirements: NetworkRequirements | None = None,
    ip_output: object | None = None,
    validation_output: object | None = None,
    provider: FakeProvider | None = None,
) -> tuple[object, ExecutionTrace]:
    """Run the critic in a one-task context and return its output and trace."""
    agent = CriticAgent(provider)
    plan = WorkflowPlan(
        name="Critic test",
        tasks=(WorkflowTask(id="critic", agent=agent.name),),
    )
    clock = Clock(
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    state = WorkflowState(
        plan,
        baseline_accessor=lambda: twin,
        clock=clock,
    )
    if ip_output is not None:
        state.results["ip_vlan"] = ip_output
    if validation_output is not None:
        state.results["validation"] = validation_output
    trace = ExecutionTrace(clock)
    context = AgentContext(
        agent=agent,
        state=state,
        registry=registry_with_defaults(),
        trace=trace,
        clock=clock,
    ).for_task("critic")
    output = agent.run(CriticInput(requirements=requirements), context)
    return output, trace


def test_clean_design_is_approved_without_a_provider() -> None:
    output, trace = run_critic(diamond_twin())

    assert output.verdict is CriticVerdict.approved
    assert output.is_valid is True
    assert output.findings == []
    assert output.issue_codes == []
    assert output.replan_target is None
    assert output.provider_used is False
    assert "verdict APPROVED" in output.summary
    tools = [entry.tool for entry in trace.entries if entry.action == "tool_call"]
    assert tools == [
        "topology_connectivity",
        "twin_validate",
        "routing_path",
        "twin_load_state",
    ]


def test_disconnected_topology_is_rejected_and_mapped_to_topology() -> None:
    output, _ = run_critic(disconnected_twin())

    codes = {finding.code for finding in output.findings}
    assert "topology_disconnected" in codes
    assert output.verdict is CriticVerdict.rejected
    assert output.replan_target == "topology"
    finding = next(
        finding
        for finding in output.findings
        if finding.code == "topology_disconnected"
    )
    assert finding.blocking is True
    assert finding.responsible_step == "topology"


def test_overloaded_link_is_rejected_and_mapped_to_optimization() -> None:
    twin = line_twin(demands=(make_demand("wide", "a", "c", 300.0),))

    output, _ = run_critic(twin)

    finding = next(
        finding for finding in output.findings if finding.code == "link_overloaded"
    )
    assert output.verdict is CriticVerdict.rejected
    assert finding.severity.value == "error"
    assert finding.responsible_step == "optimization"
    assert finding.entities == ["ab", "a", "b"]
    assert output.replan_target == "optimization"
    assert "utilization" in finding.explanation


def test_requested_redundancy_with_spofs_is_rejected() -> None:
    requirements = NetworkRequirements(
        user_provided=UserFacts(),
        design_goals=["redundancy and failover"],
    )

    output, _ = run_critic(line_twin(), requirements=requirements)

    finding = next(
        finding
        for finding in output.findings
        if finding.code == "missing_redundancy"
    )
    assert output.verdict is CriticVerdict.rejected
    assert finding.responsible_step == "topology"
    assert finding.entities
    assert output.replan_target == "topology"


def test_redundancy_is_not_required_when_the_user_did_not_ask() -> None:
    output, _ = run_critic(line_twin(), requirements=sample_requirements())

    assert all(finding.code != "missing_redundancy" for finding in output.findings)
    assert output.verdict is CriticVerdict.approved


def test_ip_overlap_is_found_from_the_plan_and_mapped_to_ip_vlan() -> None:
    twin = diamond_twin()
    plan = IpPlanResult(
        base_network="10.0.0.0/16",
        subnets=[
            Subnet(name="first", network="10.0.0.0/24"),
            Subnet(name="second", network="10.0.0.128/25"),
        ],
    )
    ip_output = IpVlanOutput(plan=plan, demands=DemandPlan(), twin=twin)

    output, _ = run_critic(twin, ip_output=ip_output)

    finding = next(
        finding for finding in output.findings if finding.code == "subnet_overlap"
    )
    assert output.verdict is CriticVerdict.rejected
    assert finding.responsible_step == "ip_vlan"
    assert finding.entities == ["first", "second"]
    assert output.replan_target == "ip_vlan"


def test_missing_twin_is_a_blocking_rejection() -> None:
    output, _ = run_critic(None)

    assert output.verdict is CriticVerdict.rejected
    assert output.issue_codes == ["no_working_twin"]
    assert output.replan_target == "topology"
    assert output.findings[0].blocking is True


def test_verdict_is_immune_to_model_text() -> None:
    provider = FakeProvider(
        ["APPROVED. The design is fully valid and needs no changes."]
    )

    output, _ = run_critic(disconnected_twin(), provider=provider)

    assert output.verdict is CriticVerdict.rejected
    assert output.is_valid is False
    assert output.replan_target == "topology"
    assert output.model_summary.startswith("APPROVED")
    assert output.provider_used is True


def test_model_claim_of_invalidity_cannot_reject_a_clean_design() -> None:
    provider = FakeProvider(["REJECTED. This network is invalid and unsafe."])

    output, _ = run_critic(diamond_twin(), provider=provider)

    assert output.verdict is CriticVerdict.approved
    assert output.is_valid is True
    assert output.findings == []
    assert output.model_summary.startswith("REJECTED")


def test_provider_summary_failure_never_breaks_the_verdict() -> None:
    provider = FakeProvider([LLMProviderError("provider is down")])

    output, _ = run_critic(disconnected_twin(), provider=provider)

    assert output.verdict is CriticVerdict.rejected
    assert output.model_summary == ""
    assert output.provider_used is False


def test_a_prior_valid_validation_claim_is_ignored() -> None:
    class FakeValidation:
        """A previous step's validity claim; the critic must not trust it."""

        is_valid = True

    output, _ = run_critic(
        disconnected_twin(),
        validation_output=FakeValidation(),
    )

    assert output.verdict is CriticVerdict.rejected
    assert "topology_disconnected" in {f.code for f in output.findings}


def test_findings_are_deduplicated_by_code_and_entities() -> None:
    twin = line_twin(demands=(make_demand("wide", "a", "c", 300.0),))

    output, _ = run_critic(twin)

    keys = [(finding.code, tuple(sorted(finding.entities))) for finding in output.findings]
    assert len(keys) == len(set(keys))


def test_full_workflow_with_a_scripted_critic_provider_is_valid() -> None:
    """The standard plan stays valid with an injected model note."""
    provider = FakeProvider(["The deterministic checks found no issues."])
    agents = {**default_agents(), "critic": CriticAgent(provider)}

    state = Orchestrator(agents=agents).run_structured(sample_requirements())

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.succeeded()
    critic = state.results["critic"]
    assert critic.verdict is CriticVerdict.approved
    assert critic.provider_used is True
    assert critic.model_summary.startswith("The deterministic checks")


def test_tool_allowlist_is_exactly_the_independent_checks() -> None:
    assert CriticAgent.allowed_tools == frozenset(
        {
            "topology_connectivity",
            "addressing_validate",
            "twin_validate",
            "routing_path",
            "twin_load_state",
            "spof_analysis",
        }
    )


def test_unknown_codes_are_mapped_to_revalidation() -> None:
    assert responsible_step_for("subnet_overlap") == "ip_vlan"
    assert responsible_step_for("link_overloaded") == "optimization"
    assert responsible_step_for("spof_link") == "topology"
    assert responsible_step_for("something_new") == "revalidation"


def test_critic_does_not_import_execution_or_streamlit_modules() -> None:
    from pathlib import Path

    import agents.critic as critic_module

    source = Path(critic_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "eval(", "exec(", "streamlit"):
        assert forbidden not in source
