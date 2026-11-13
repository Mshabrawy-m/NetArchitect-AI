"""Base agent contract and the typed context used inside a workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from core.exceptions import AgentValidationError
from digital_twin import DigitalTwin

from .models import Clock, ExecutionTrace, WorkflowState, summarize
from .tools import Tool, ToolRegistry


@dataclass
class AgentContext:
    """Execution context handed to one agent run.

    The context exposes validated workflow results and the current twin. Every
    tool call is traced; the agent cannot call a tool outside its allowlist.
    """

    agent: BaseAgent
    state: WorkflowState
    registry: ToolRegistry
    trace: ExecutionTrace
    clock: Clock

    @property
    def current_twin(self) -> DigitalTwin | None:
        """Return the workflow's current twin (derived or baseline)."""
        return self.state.current_twin

    def result(self, task_id: str) -> Any:
        """Return a completed dependency result."""
        return self.state.result(task_id)

    def call_tool(self, name: str, payload: object) -> BaseModel:
        """Call an allowed, validated tool and record both sides of the call."""
        tool: Tool = self.registry.resolve(name, self.agent.allowed_tools)
        started = self.clock.monotonic()
        validated = self.registry.validate_input(tool, payload)
        try:
            output = self.registry.execute(tool, validated)
        except Exception as error:
            self.trace.record(
                task_id=self.state_task_id,
                agent=self.agent.name,
                tool=name,
                action="tool_call",
                status="error",
                input_summary=summarize(validated),
                output_summary=summarize(str(error)),
                duration_seconds=self.clock.monotonic() - started,
            )
            raise
        self.trace.record(
            task_id=self.state_task_id,
            agent=self.agent.name,
            tool=name,
            action="tool_call",
            status="ok",
            input_summary=summarize(validated),
            output_summary=summarize(output),
            duration_seconds=self.clock.monotonic() - started,
        )
        return output

    state_task_id: str = ""

    def for_task(self, task_id: str) -> AgentContext:
        """Return a shallow copy bound to ``task_id`` for trace attribution."""
        return AgentContext(
            agent=self.agent,
            state=self.state,
            registry=self.registry,
            trace=self.trace,
            clock=self.clock,
            state_task_id=task_id,
        )


class BaseAgent:
    """Typed, tool-bounded agent base class.

    Subclasses declare a name, responsibility, typed input/output models, and
    the exact tool names they may call. ``run`` receives an already-validated
    input model and must return an output model (the orchestrator validates it
    again at the boundary).
    """

    name: str = "agent"
    responsibility: str = ""
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_tools: frozenset[str] = frozenset()

    def validate_input(self, payload: object) -> BaseModel:
        """Validate a raw payload against this agent's input contract."""
        try:
            return self.input_model.model_validate(payload)
        except Exception as error:
            raise AgentValidationError(
                f"Invalid input for agent {self.name!r}: {error}"
            ) from error

    def validate_output(self, payload: object) -> BaseModel:
        """Validate a result against this agent's output contract."""
        try:
            return self.output_model.model_validate(payload)
        except Exception as error:
            raise AgentValidationError(
                f"Invalid output from agent {self.name!r}: {error}"
            ) from error

    def run(self, payload: BaseModel, context: AgentContext) -> BaseModel:
        """Execute the agent's responsibility."""
        raise NotImplementedError

    def replan(self, payload: BaseModel, issue: str) -> BaseModel | None:
        """Return corrected input after a failure, or ``None`` to stop.

        The default agent cannot re-plan. The IP/VLAN agent overrides this to
        move to a non-overlapping base block without re-running upstream tasks.
        """
        return None


__all__ = ["AgentContext", "BaseAgent"]
