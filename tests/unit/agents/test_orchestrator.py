"""Orchestrator DAG, bounds, re-plan, trace, and determinism tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents import (
    BaseAgent,
    IpVlanAgent,
    IpVlanOutput,
    Orchestrator,
    ToolRegistry,
    WorkflowPlan,
    WorkflowStopReason,
    WorkflowTask,
    build_ip_plan,
    build_standard_plan,
    build_topology,
    run_structured_design,
    structured_inputs,
)
from agents.network_agents import default_agents
from agents.orchestrator import validate_workflow_plan
from core.exceptions import (
    AgentValidationError,
    WorkflowCycleError,
    WorkflowLimitError,
)
from network.routing import shortest_path
from tests.unit.agents.helpers import (
    MarkerInput,
    MarkerOutput,
    chain_plan,
    fixed_clock,
    marker_agents,
    sample_requirements,
)
from tests.unit.simulation.helpers import diamond_twin


class BoomAgent(BaseAgent):
    """Agent that always fails, used to check bounds and skip behaviour."""

    name = "boom"
    input_model = MarkerInput
    output_model = MarkerOutput
    allowed_tools = frozenset()

    def run(self, payload: MarkerInput, context) -> MarkerOutput:
        raise RuntimeError("boom")


class OverlapOnceIpVlanAgent(IpVlanAgent):
    """Return one deliberately overlapping subnet, then correct it on re-plan."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self, payload, context) -> IpVlanOutput:
        output = super().run(payload, context)
        self.calls += 1
        if self.calls == 1 and len(output.plan.subnets) > 1:
            plan = output.plan.model_copy(deep=True)
            plan.subnets[1] = plan.subnets[1].model_copy(
                update={"network": plan.subnets[0].network}
            )
            return output.model_copy(update={"plan": plan})
        return output


def _orchestrator_for(order: list[str], *names: str, **kwargs) -> Orchestrator:
    agents = marker_agents(order, *names)
    return Orchestrator(agents=agents, registry=ToolRegistry(tools=()), **kwargs)


def test_standard_plan_has_deterministic_shape() -> None:
    plan = build_standard_plan()
    assert [task.id for task in plan.tasks] == [
        "requirements",
        "topology",
        "ip_vlan",
        "routing",
        "validation",
        "simulation",
        "optimization",
        "revalidation",
        "report",
    ]
    assert plan.task("report").dependencies == ("revalidation",)
    assert plan.task("requirements").dependencies == ()
    requirements = sample_requirements()
    inputs = structured_inputs(requirements)
    assert set(inputs) == {"requirements", "topology", "ip_vlan"}
    embedded = build_standard_plan(requirements)
    assert embedded.task("ip_vlan").payload["requirements"] is requirements


def test_plan_validation_rejects_cycle() -> None:
    plan = WorkflowPlan(
        tasks=(
            WorkflowTask(id="a", agent="a", dependencies=("b",)),
            WorkflowTask(id="b", agent="b", dependencies=("a",)),
        )
    )
    with pytest.raises(WorkflowCycleError):
        validate_workflow_plan(
            plan,
            agents=marker_agents([], "a", "b"),
            registry=ToolRegistry(tools=()),
        )


def test_plan_validation_rejects_missing_dependency() -> None:
    plan = WorkflowPlan(
        tasks=(WorkflowTask(id="a", agent="a", dependencies=("ghost",)),)
    )
    with pytest.raises(AgentValidationError):
        validate_workflow_plan(
            plan,
            agents=marker_agents([], "a"),
            registry=ToolRegistry(tools=()),
        )


def test_plan_validation_rejects_unknown_agent() -> None:
    plan = WorkflowPlan(tasks=(WorkflowTask(id="a", agent="ghost"),))
    with pytest.raises(AgentValidationError):
        validate_workflow_plan(plan, agents={}, registry=ToolRegistry(tools=()))


def test_plan_validation_rejects_duplicate_ids_and_step_limit() -> None:
    duplicate = WorkflowPlan(
        tasks=(
            WorkflowTask(id="a", agent="a"),
            WorkflowTask(id="a", agent="a"),
        )
    )
    with pytest.raises(AgentValidationError, match="Duplicate"):
        validate_workflow_plan(
            duplicate,
            agents=marker_agents([], "a"),
            registry=ToolRegistry(tools=()),
        )
    long_plan = chain_plan("a", "b", "c")
    with pytest.raises(WorkflowLimitError):
        validate_workflow_plan(
            long_plan,
            agents=marker_agents([], "a", "b", "c"),
            registry=ToolRegistry(tools=()),
            max_steps=2,
        )


def test_orchestrator_runs_in_dependency_order() -> None:
    order: list[str] = []
    plan = WorkflowPlan(
        tasks=(
            WorkflowTask(id="b", agent="b", dependencies=("a",)),
            WorkflowTask(id="a", agent="a"),
        )
    )
    state = _orchestrator_for(order, "a", "b").run(plan)

    assert order == ["a", "b"]
    assert state.stop_reason is WorkflowStopReason.completed
    assert state.succeeded()
    assert state.steps == 2


def test_failed_task_skips_every_dependent() -> None:
    plan = chain_plan("a", "b", "c")
    state = Orchestrator(
        agents={"a": BoomAgent(), "b": BoomAgent(), "c": BoomAgent()},
        registry=ToolRegistry(tools=()),
        max_retries=1,
    ).run(plan)

    assert state.stop_reason is WorkflowStopReason.failed
    assert state.status("a").value == "failed"
    assert state.status("b").value == "skipped"
    assert state.status("c").value == "skipped"
    assert "dependency" in state.tasks["b"].skipped_reason
    assert state.steps == 1


def test_retry_bounds_are_enforced() -> None:
    plan = chain_plan("boom")
    state = Orchestrator(
        agents={"boom": BoomAgent()},
        registry=ToolRegistry(tools=()),
        max_retries=3,
    ).run(plan)

    assert state.tasks["boom"].attempts == 3
    assert state.steps == 3
    assert state.stop_reason is WorkflowStopReason.failed
    retries = [entry for entry in state.trace.entries if entry.action == "task_retry"]
    assert len(retries) == 2
    assert any(entry.action == "task_failed" for entry in state.trace.entries)


def test_step_limit_stop_reason_is_typed() -> None:
    plan = chain_plan("a", "b", "c")
    state = _orchestrator_for(["a", "b", "c"], "a", "b", "c", max_steps=2).run(plan)

    assert state.stop_reason is WorkflowStopReason.step_limit
    assert state.steps == 2
    assert state.status("c").value == "pending"


def test_runtime_limit_stop_reason_is_typed() -> None:
    clock, _ = fixed_clock(step=10.0)
    plan = chain_plan("a")
    state = _orchestrator_for(["a"], "a", clock=clock, max_seconds=5).run(plan)

    assert state.stop_reason is WorkflowStopReason.runtime_limit
    assert state.steps == 0


def test_validation_issue_triggers_selective_replan() -> None:
    requirements = sample_requirements()
    agent = OverlapOnceIpVlanAgent()
    state = Orchestrator(
        agents={**default_agents(), "ip_vlan": agent},
    ).run_structured(requirements)

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.replans == 1
    assert state.tasks["ip_vlan"].replans == 1
    assert state.tasks["ip_vlan"].attempts == 2
    assert state.tasks["validation"].attempts == 2
    assert state.tasks["requirements"].attempts == 1
    assert state.tasks["topology"].attempts == 1
    assert state.status("report").value == "succeeded"
    assert state.results["validation"].is_valid is True
    assert state.results["ip_vlan"].plan.base_network == "10.1.0.0/16"


def test_replan_limit_terminates_the_workflow() -> None:
    class AlwaysOverlap(IpVlanAgent):
        def run(self, payload, context) -> IpVlanOutput:
            output = super().run(payload, context)
            plan = output.plan.model_copy(deep=True)
            plan.subnets[1] = plan.subnets[1].model_copy(
                update={"network": plan.subnets[0].network}
            )
            return output.model_copy(update={"plan": plan})

    state = Orchestrator(
        agents={**default_agents(), "ip_vlan": AlwaysOverlap()},
        max_replans=1,
    ).run_structured(sample_requirements())

    assert state.stop_reason is WorkflowStopReason.replan_limit
    assert state.replans == 1
    assert "Re-plan limit" in state.error


def test_structured_plan_matches_direct_engines_without_a_provider() -> None:
    requirements = sample_requirements()
    state = run_structured_design(requirements)

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.succeeded()
    assert state.steps == 9
    assert state.replans == 0

    topology = state.results["topology"].topology
    assert topology.model_dump() == build_topology(requirements).model_dump()

    ip_plan = state.results["ip_vlan"].plan
    expected_ip = build_ip_plan(requirements)
    assert ip_plan.subnets == expected_ip.subnets
    assert ip_plan.base_network == expected_ip.base_network

    routing = state.results["routing"]
    expected_path = shortest_path(
        topology, routing.source, routing.destination
    )
    assert routing.path is not None
    assert routing.path.model_dump() == expected_path.model_dump()

    report = state.results["report"]
    assert "no blocking validation issues" in report.headline
    assert [section.title for section in report.sections] == [
        "Requirements",
        "Topology",
        "IP and VLANs",
        "Routing",
        "Validation",
        "Simulation",
        "Optimization",
        "Re-validation",
    ]


def test_baseline_twin_is_never_mutated_or_copied() -> None:
    baseline = diamond_twin()
    before = baseline.model_dump()
    accessor_calls: list[object] = []

    def accessor():
        accessor_calls.append(baseline)
        return baseline

    state = Orchestrator(baseline_accessor=accessor).run_structured(
        sample_requirements()
    )

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.baseline_twin is baseline
    assert accessor_calls
    assert state.working_twin is not baseline
    assert baseline.model_dump() == before
    assert "baseline_twin" not in state.to_dict()


def test_trace_is_serializable_and_redacts_secrets() -> None:
    class SecretAgent(BaseAgent):
        name = "secret"
        input_model = MarkerInput
        output_model = MarkerOutput
        allowed_tools = frozenset()

        def run(self, payload: MarkerInput, context) -> MarkerOutput:
            return MarkerOutput(agent=self.name, value=payload.value)

    plan = WorkflowPlan(
        tasks=(
            WorkflowTask(
                id="secret",
                agent="secret",
                payload={"value": 1, "api_key": "sk-live-supersecret"},
            ),
        )
    )
    state = Orchestrator(
        agents={"secret": SecretAgent()},
        registry=ToolRegistry(tools=()),
    ).run(plan)

    entry = state.trace.entries[1]
    assert entry.input_summary == '{"api_key":"<redacted>","value":1}'
    payload = state.trace.to_json()
    assert "supersecret" not in payload
    assert json.loads(payload)["entry_count"] == len(state.trace.entries)
    assert [item.step for item in state.trace.entries] == list(
        range(1, len(state.trace.entries) + 1)
    )
    assert state.trace.entries[0].action == "workflow_started"
    assert state.trace.entries[-1].action == "workflow_stopped"

    state_payload = json.dumps(state.to_dict())
    assert "supersecret" not in state_payload
    assert "api_key" in state_payload  # the key name remains visible
    assert state.to_dict()["replans"] == 0


def test_trace_summaries_do_not_leak_nested_credentials() -> None:
    from agents import summarize

    summary = summarize(
        {
            "api_key": "sk-1",
            "nested": {"authorization": "Bearer sk-2", "token": "sk-3"},
        }
    )
    assert "sk-1" not in summary
    assert "sk-2" not in summary
    assert "sk-3" not in summary
    assert summary.count("<redacted>") == 3


def test_agent_input_validation_failure_is_not_retried() -> None:
    class StrictAgent(BaseAgent):
        name = "strict"
        input_model = MarkerInput
        output_model = MarkerOutput
        allowed_tools = frozenset()

        def run(self, payload, context):
            return MarkerOutput(agent=self.name, value=payload.value)

    plan = WorkflowPlan(tasks=(WorkflowTask(id="strict", agent="strict"),))
    state = Orchestrator(
        agents={"strict": StrictAgent()},
        registry=ToolRegistry(tools=()),
        max_retries=3,
    ).run(plan, inputs={"strict": {"value": "not-an-integer"}})

    assert state.stop_reason is WorkflowStopReason.failed
    assert state.tasks["strict"].attempts == 1


def test_agent_package_has_no_execution_or_provider_escape_hatches() -> None:
    import agents as agents_package

    package = Path(agents_package.__file__).parent
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package.glob("*.py"))
    )
    for forbidden in (
        "subprocess",
        "os.system",
        "os.popen",
        "eval(",
        "exec(",
        "from services",
        "import services",
    ):
        assert forbidden not in sources
    assert "streamlit" not in sources

