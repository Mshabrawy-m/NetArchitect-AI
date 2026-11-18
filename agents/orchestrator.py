"""Bounded workflow orchestrator for the deterministic agent framework.

The orchestrator executes a typed task DAG in dependency order. It validates
the plan up front (duplicate ids, missing dependencies, cycles, unknown agents,
and disallowed tool references), retries recoverable task failures, skips every
dependent of a failed task, enforces step/runtime/replan bounds, and records
every attempt in an :class:`~agents.models.ExecutionTrace`.

Re-planning is selective: when a validation result reports a modeled addressing
issue, only the responsible task and its dependents are reset and re-run. The
base twin is never copied or mutated; derived twins are stored as the current
working twin by :class:`~agents.models.WorkflowState`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from config.limits import (
    MAX_AGENT_REPLANS,
    MAX_AGENT_RETRIES,
    MAX_AGENT_RUNTIME_SECONDS,
    MAX_WORKFLOW_STEPS,
)
from core.exceptions import (
    AgentError,
    AgentValidationError,
    WorkflowCycleError,
    WorkflowLimitError,
)
from core.schemas.requirements import NetworkRequirements
from digital_twin import DigitalTwin

from .base import AgentContext, BaseAgent
from .models import (
    Clock,
    ExecutionTrace,
    TaskStatus,
    WorkflowPlan,
    WorkflowState,
    WorkflowStopReason,
    WorkflowTask,
    missing_dependencies,
    summarize,
    workflow_cycle_error,
)
from .network_agents import (
    IpVlanInput,
    RequirementsInput,
    TopologyInput,
    default_agents,
)
from .tools import ToolRegistry

# Validation issue code -> task that owns the fix. Re-planning resets this task
# and every dependent of it, leaving upstream results intact.
ISSUE_TASK_POLICY: dict[str, str] = {
    "subnet_overlap": "ip_vlan",
    "duplicate_ip": "ip_vlan",
    "twin_vlan_subnet_missing": "ip_vlan",
}


def build_standard_plan(
    requirements: NetworkRequirements | None = None,
    *,
    include_security: bool = False,
) -> WorkflowPlan:
    """Return the deterministic structured-form plan.

    The default order is requirements -> topology -> IP/VLAN -> routing ->
    validation -> simulation -> optimization -> re-validation -> critic ->
    documentation -> report (eleven steps). With ``include_security=True`` one
    offline security step is inserted after re-validation and before the critic,
    making twelve steps. When ``requirements`` is supplied it is embedded in the
    tasks that need it, so :meth:`Orchestrator.run` can execute the plan without
    extra inputs.
    """
    base_payload: dict[str, Any] = (
        {} if requirements is None else {"requirements": requirements}
    )
    tasks: list[WorkflowTask] = [
        WorkflowTask(
            id="requirements",
            agent="requirements",
            description="Validate the structured requirements.",
            payload=base_payload,
        ),
        WorkflowTask(
            id="topology",
            agent="topology",
            description="Generate the deterministic topology and working twin.",
            dependencies=("requirements",),
            payload=base_payload,
        ),
        WorkflowTask(
            id="ip_vlan",
            agent="ip_vlan",
            description="Allocate VLSM subnets, VLAN ids, and modeled demands.",
            dependencies=("topology",),
            payload=base_payload,
        ),
        WorkflowTask(
            id="routing",
            agent="routing",
            description="Compute a deterministic path and routing table.",
            dependencies=("ip_vlan",),
        ),
        WorkflowTask(
            id="validation",
            agent="validation",
            description="Validate addressing and the working twin.",
            dependencies=("routing", "ip_vlan"),
        ),
        WorkflowTask(
            id="simulation",
            agent="simulation",
            description="Run one bounded link-failure scenario.",
            dependencies=("validation",),
        ),
        WorkflowTask(
            id="optimization",
            agent="optimization",
            description="Run the bounded deterministic optimization baseline.",
            dependencies=("simulation",),
        ),
        WorkflowTask(
            id="revalidation",
            agent="revalidation",
            description="Re-validate the final working twin.",
            dependencies=("optimization",),
        ),
    ]
    critic_dependencies = ("revalidation",)
    if include_security:
        tasks.append(
            WorkflowTask(
                id="security",
                agent="security",
                description=(
                    "Run the offline design-time security analysis on the final "
                    "working twin."
                ),
                dependencies=("revalidation",),
            )
        )
        critic_dependencies = ("revalidation", "security")
    tasks.extend(
        (
            WorkflowTask(
                id="critic",
                agent="critic",
                description=(
                    "Independently critique topology, addressing, routing, capacity, "
                    "redundancy, and optional security findings."
                ),
                dependencies=critic_dependencies,
                payload=base_payload,
            ),
            WorkflowTask(
                id="documentation",
                agent="documentation",
                description=(
                    "Assemble validated results into a traceable report with "
                    "provenance, assumptions, and limitations."
                ),
                dependencies=("critic",),
                payload=base_payload,
            ),
            WorkflowTask(
                id="report",
                agent="report",
                description="Summarize the plan, assumptions, and results.",
                dependencies=("documentation",),
            ),
        )
    )
    return WorkflowPlan(name="Structured design plan", tasks=tuple(tasks))


def structured_inputs(requirements: NetworkRequirements) -> dict[str, BaseModel]:
    """Return the validated initial inputs for :func:`build_standard_plan`."""
    return {
        "requirements": RequirementsInput(requirements=requirements),
        "topology": TopologyInput(requirements=requirements),
        "ip_vlan": IpVlanInput(requirements=requirements),
    }


def validate_workflow_plan(
    plan: WorkflowPlan,
    *,
    agents: Mapping[str, BaseAgent],
    registry: ToolRegistry,
    max_steps: int = MAX_WORKFLOW_STEPS,
) -> None:
    """Raise a typed error when ``plan`` cannot be executed safely."""
    ids = [task.id for task in plan.tasks]
    duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicates:
        raise AgentValidationError(
            "Duplicate workflow task id(s): " + ", ".join(duplicates)
        )
    missing = missing_dependencies(plan)
    if missing:
        raise AgentValidationError(
            "Unknown workflow dependencies: " + ", ".join(missing)
        )
    cycle = workflow_cycle_error(plan)
    if cycle:
        raise WorkflowCycleError(
            "Workflow dependency cycle: " + " -> ".join(cycle)
        )
    if len(plan.tasks) > max_steps:
        raise WorkflowLimitError(
            f"Workflow has {len(plan.tasks)} tasks, above the "
            f"{max_steps}-step limit."
        )
    known_tools = set(registry.names())
    for task in plan.tasks:
        agent = agents.get(task.agent)
        if agent is None:
            raise AgentValidationError(
                f"Task {task.id!r} names unknown agent {task.agent!r}."
            )
        unknown = sorted(set(agent.allowed_tools) - known_tools)
        if unknown:
            raise AgentValidationError(
                f"Agent {agent.name!r} allows unregistered tool(s): "
                + ", ".join(unknown)
            )


class Orchestrator:
    """Execute a workflow DAG with hard step, runtime, and re-plan bounds."""

    def __init__(
        self,
        *,
        agents: Mapping[str, BaseAgent] | None = None,
        registry: ToolRegistry | None = None,
        clock: Clock | None = None,
        baseline_accessor=None,
        max_retries: int = MAX_AGENT_RETRIES,
        max_steps: int = MAX_WORKFLOW_STEPS,
        max_seconds: int = MAX_AGENT_RUNTIME_SECONDS,
        max_replans: int = MAX_AGENT_REPLANS,
    ) -> None:
        self.agents = dict(agents) if agents is not None else default_agents()
        self.registry = registry if registry is not None else ToolRegistry()
        self.clock = clock or Clock()
        self.baseline_accessor = baseline_accessor
        self.max_retries = max(1, int(max_retries))
        self.max_steps = max(1, int(max_steps))
        self.max_seconds = max(0.0, float(max_seconds))
        self.max_replans = max(0, int(max_replans))

    def run_structured(
        self,
        requirements: NetworkRequirements,
        *,
        plan: WorkflowPlan | None = None,
        include_security: bool = False,
    ) -> WorkflowState:
        """Build and run the standard structured-form plan for requirements."""
        resolved = plan or build_standard_plan(
            requirements, include_security=include_security
        )
        return self.run(resolved, inputs=structured_inputs(requirements))

    def run(
        self,
        plan: WorkflowPlan,
        *,
        inputs: Mapping[str, object] | None = None,
    ) -> WorkflowState:
        """Execute ``plan`` and return its final typed state."""
        validate_workflow_plan(
            plan,
            agents=self.agents,
            registry=self.registry,
            max_steps=MAX_WORKFLOW_STEPS,
        )
        initial = dict(inputs or {})
        state = WorkflowState(
            plan,
            baseline_accessor=self.baseline_accessor,
            clock=self.clock,
        )
        trace: ExecutionTrace = state.trace
        order = state.ordered_task_ids()
        queue = list(order)
        payloads: dict[str, BaseModel] = {}
        start = self.clock.monotonic()

        trace.record(
            task_id="",
            agent="orchestrator",
            action="workflow_started",
            status="ok",
            output_summary=summarize(
                {"tasks": [task.id for task in plan.tasks], "name": plan.name}
            ),
        )

        while queue:
            task_id = queue.pop(0)
            task_state = state.tasks[task_id]
            if task_state.status is not TaskStatus.pending:
                continue

            failed_dependencies = [
                dependency
                for dependency in plan.task(task_id).dependencies
                if state.tasks[dependency].status
                in {TaskStatus.failed, TaskStatus.skipped}
            ]
            if failed_dependencies:
                self._skip(
                    state,
                    task_id,
                    "Skipped because dependency failed: "
                    + ", ".join(failed_dependencies),
                )
                continue

            if state.steps >= self.max_steps:
                self._stop(state, WorkflowStopReason.step_limit)
                break

            elapsed = self.clock.monotonic() - start
            if self.max_seconds > 0 and elapsed > self.max_seconds:
                self._stop(state, WorkflowStopReason.runtime_limit)
                break

            succeeded = self._execute(
                state,
                plan.task(task_id),
                initial=initial,
                payloads=payloads,
            )
            if state.stop_reason is not None:
                break
            if not succeeded:
                continue

            output = state.result(task_id)
            target = self._replan_target(output)
            critic_rejection = self._is_critic_rejection(output)
            if target is None:
                if critic_rejection:
                    self._stop(
                        state,
                        WorkflowStopReason.critic_rejected,
                        error=(
                            f"Critic rejected {task_id!r} with no mapped "
                            "re-plan target."
                        ),
                    )
                    break
                continue
            if state.replans >= self.max_replans:
                self._stop(
                    state,
                    (
                        WorkflowStopReason.critic_rejected
                        if critic_rejection
                        else WorkflowStopReason.replan_limit
                    ),
                    error=(
                        f"Re-plan limit ({self.max_replans}) reached while "
                        f"resolving {task_id!r}."
                    ),
                )
                break
            new_input = self._apply_replan(
                state,
                target,
                output,
                payloads=payloads,
                queue=queue,
                trace=trace,
                critic_rejection=critic_rejection,
            )
            if new_input is False:
                break

        if state.stop_reason is None:
            state.stop_reason = (
                WorkflowStopReason.completed
                if state.succeeded()
                else WorkflowStopReason.failed
            )
        trace.record(
            task_id="",
            agent="orchestrator",
            action="workflow_stopped",
            status=state.stop_reason.value,
            output_summary=summarize(
                {
                    "stop_reason": state.stop_reason.value,
                    "steps": state.steps,
                    "replans": state.replans,
                }
            ),
        )
        return state

    def _execute(
        self,
        state: WorkflowState,
        task: WorkflowTask,
        *,
        initial: Mapping[str, object],
        payloads: dict[str, BaseModel],
    ) -> bool:
        agent = self.agents[task.agent]
        task_state = state.tasks[task.id]
        raw: object
        if task.id in payloads:
            raw = payloads[task.id]
        elif task.id in initial:
            raw = initial[task.id]
        elif task.payload:
            raw = dict(task.payload)
        else:
            raw = {}

        for attempt in range(1, self.max_retries + 1):
            if state.steps >= self.max_steps:
                self._stop(state, WorkflowStopReason.step_limit)
                return False
            state.steps += 1
            task_state.status = TaskStatus.running
            task_state.attempts += 1
            started = self.clock.monotonic()
            state.trace.record(
                task_id=task.id,
                agent=agent.name,
                action="task_started",
                status="running",
                attempt=attempt,
                input_summary=summarize(raw),
            )
            try:
                validated = agent.validate_input(raw)
                output = agent.run(
                    validated,
                    AgentContext(
                        agent=agent,
                        state=state,
                        registry=self.registry,
                        trace=state.trace,
                        clock=self.clock,
                        state_task_id=task.id,
                    ),
                )
                validated_output = agent.validate_output(output)
            except AgentValidationError as error:
                task_state.error = str(error)
                state.trace.record(
                    task_id=task.id,
                    agent=agent.name,
                    action="task_failed",
                    status="error",
                    attempt=attempt,
                    input_summary=summarize(raw),
                    output_summary=summarize(str(error)),
                    duration_seconds=max(0.0, self.clock.monotonic() - started),
                )
                self._fail(state, task.id, str(error))
                return False
            except AgentError as error:
                task_state.error = str(error)
                if attempt < self.max_retries:
                    state.trace.record(
                        task_id=task.id,
                        agent=agent.name,
                        action="task_retry",
                        status="retry",
                        attempt=attempt,
                        input_summary=summarize(raw),
                        output_summary=summarize(str(error)),
                        duration_seconds=max(0.0, self.clock.monotonic() - started),
                    )
                    continue
                self._record_failure(state, task, agent.name, raw, error, attempt, started)
                self._fail(state, task.id, str(error))
                return False
            except Exception as error:  # noqa: BLE001 - task boundary
                task_state.error = str(error)
                if attempt < self.max_retries:
                    state.trace.record(
                        task_id=task.id,
                        agent=agent.name,
                        action="task_retry",
                        status="retry",
                        attempt=attempt,
                        input_summary=summarize(raw),
                        output_summary=summarize(str(error)),
                        duration_seconds=max(0.0, self.clock.monotonic() - started),
                    )
                    continue
                self._record_failure(state, task, agent.name, raw, error, attempt, started)
                self._fail(state, task.id, str(error))
                return False

            payloads[task.id] = validated
            state.inputs[task.id] = validated
            state.results[task.id] = validated_output
            twin = getattr(validated_output, "twin", None)
            if isinstance(twin, DigitalTwin):
                state.working_twin = twin
            task_state.status = TaskStatus.succeeded
            task_state.error = ""
            state.trace.record(
                task_id=task.id,
                agent=agent.name,
                action="task_succeeded",
                status="ok",
                attempt=attempt,
                input_summary=summarize(validated),
                output_summary=summarize(validated_output),
                duration_seconds=max(0.0, self.clock.monotonic() - started),
            )
            return True
        return False

    def _record_failure(
        self,
        state: WorkflowState,
        task: WorkflowTask,
        agent_name: str,
        raw: object,
        error: Exception,
        attempt: int,
        started: float,
    ) -> None:
        state.trace.record(
            task_id=task.id,
            agent=agent_name,
            action="task_failed",
            status="error",
            attempt=attempt,
            input_summary=summarize(raw),
            output_summary=summarize(str(error)),
            duration_seconds=max(0.0, self.clock.monotonic() - started),
        )

    def _fail(self, state: WorkflowState, task_id: str, error: str) -> None:
        state.tasks[task_id].status = TaskStatus.failed
        state.tasks[task_id].error = error
        state.error = state.error or f"Task {task_id!r} failed: {error}"
        for dependent in self._dependents(state.plan, task_id):
            if state.tasks[dependent].status is TaskStatus.pending:
                self._skip(
                    state,
                    dependent,
                    f"Skipped because dependency {task_id!r} failed.",
                )

    def _skip(self, state: WorkflowState, task_id: str, reason: str) -> None:
        task_state = state.tasks[task_id]
        task_state.status = TaskStatus.skipped
        task_state.skipped_reason = reason
        state.trace.record(
            task_id=task_id,
            agent=state.plan.task(task_id).agent,
            action="task_skipped",
            status="skipped",
            output_summary=summarize(reason),
        )

    def _stop(
        self,
        state: WorkflowState,
        reason: WorkflowStopReason,
        *,
        error: str = "",
    ) -> None:
        state.stop_reason = reason
        if error:
            state.error = error

    def _replan_target(self, output: object) -> str | None:
        if getattr(output, "is_valid", None) is not False:
            return None
        explicit = getattr(output, "replan_target", None)
        if explicit:
            return str(explicit)
        codes = getattr(output, "issue_codes", None) or ()
        for code in codes:
            target = ISSUE_TASK_POLICY.get(str(code))
            if target is not None:
                return target
        return None

    @staticmethod
    def _is_critic_rejection(output: object) -> bool:
        verdict = getattr(output, "verdict", None)
        return getattr(verdict, "value", verdict) == "REJECTED"

    def _apply_replan(
        self,
        state: WorkflowState,
        target: str,
        output: object,
        *,
        payloads: dict[str, BaseModel],
        queue: list[str],
        trace: ExecutionTrace,
        critic_rejection: bool = False,
    ) -> bool | None:
        unresolved = (
            WorkflowStopReason.critic_rejected
            if critic_rejection
            else WorkflowStopReason.failed
        )
        if target not in state.tasks:
            state.stop_reason = unresolved
            state.error = (
                f"Re-plan target {target!r} is not part of this workflow."
            )
            return False
        agent = self.agents[state.plan.task(target).agent]
        current = payloads.get(target)
        issue = ", ".join(str(code) for code in getattr(output, "issue_codes", ()))
        if current is None:
            state.stop_reason = unresolved
            state.error = f"Task {target!r} has no input to re-plan."
            return False
        try:
            new_input = agent.replan(current, issue)
        except Exception as error:  # noqa: BLE001 - re-plan boundary
            state.stop_reason = unresolved
            state.error = f"Re-plan for task {target!r} failed: {error}"
            return False
        if new_input is None:
            state.stop_reason = unresolved
            state.error = f"Agent {agent.name!r} declined to re-plan ({issue})."
            return False

        state.replans += 1
        task_state = state.tasks[target]
        task_state.replans += 1
        reset = {target, *self._dependents(state.plan, target)}
        for task_id in reset:
            state.tasks[task_id].status = TaskStatus.pending
            state.tasks[task_id].error = ""
            state.tasks[task_id].skipped_reason = ""
            state.results.pop(task_id, None)
            state.inputs.pop(task_id, None)
        state.working_twin = None
        payloads.pop(target, None)
        trace.record(
            task_id=target,
            agent=agent.name,
            action="replan",
            status="pending",
            input_summary=summarize(current),
            output_summary=summarize(
                {"issue": issue, "replan": state.replans}
            ),
        )

        ordered_reset = [
            task_id
            for task_id in state.ordered_task_ids()
            if task_id in reset
        ]
        trailing = [task_id for task_id in queue if task_id not in reset]
        queue[:] = [*ordered_reset, *trailing]
        if new_input is not None:
            payloads[target] = agent.validate_input(new_input)
        return True

    @staticmethod
    def _dependents(plan: WorkflowPlan, task_id: str) -> list[str]:
        found: list[str] = []
        frontier = {task_id}
        while frontier:
            frontier = {
                task.id
                for task in plan.tasks
                if task.id not in found
                and task.id != task_id
                and set(task.dependencies) & frontier
            }
            found.extend(sorted(frontier))
        return found


def run_structured_design(
    requirements: NetworkRequirements,
    *,
    orchestrator: Orchestrator | None = None,
    include_security: bool = False,
) -> WorkflowState:
    """Run the standard deterministic plan end-to-end without any LLM."""
    return (orchestrator or Orchestrator()).run_structured(
        requirements, include_security=include_security
    )


__all__ = [
    "ISSUE_TASK_POLICY",
    "Orchestrator",
    "build_standard_plan",
    "run_structured_design",
    "structured_inputs",
    "validate_workflow_plan",
]
