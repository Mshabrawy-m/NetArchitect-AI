"""Typed workflow, task, and execution-trace models for the agent framework.

The LLM is optional in this package: agents call deterministic tools, and the
structured-form path builds and executes a plan without any provider.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from digital_twin import DigitalTwin

_SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "authorization")


class TaskStatus(str, Enum):
    """Lifecycle state of one workflow task."""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class WorkflowStopReason(str, Enum):
    """Why a workflow stopped. Every run ends with exactly one value."""

    completed = "completed"
    failed = "failed"
    step_limit = "step_limit"
    runtime_limit = "runtime_limit"
    replan_limit = "replan_limit"
    critic_rejected = "critic_rejected"


class WorkflowTask(BaseModel):
    """One typed task in a workflow DAG."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    description: str = ""
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowPlan(BaseModel):
    """A typed, serializable list of tasks with dependencies."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(default="Structured design plan", min_length=1)
    tasks: tuple[WorkflowTask, ...] = Field(min_length=1)

    def task(self, task_id: str) -> WorkflowTask:
        """Return one task by id."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)


class TaskState(BaseModel):
    """Mutable run state for one task (stored inside :class:`WorkflowState`)."""

    id: str
    status: TaskStatus = TaskStatus.pending
    attempts: int = Field(default=0, ge=0)
    replans: int = Field(default=0, ge=0)
    error: str = ""
    skipped_reason: str = ""


class TraceEntry(BaseModel):
    """One auditable trace event, with no credentials or raw secrets."""

    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=0)
    timestamp: datetime
    task_id: str
    agent: str
    tool: str = ""
    action: str
    status: str
    attempt: int = Field(default=1, ge=0)
    input_summary: str = ""
    output_summary: str = ""
    duration_seconds: float = Field(default=0.0, ge=0.0)


def _redact_key(key: object) -> bool:
    text = str(key).lower()
    return any(marker in text for marker in _SECRET_MARKERS)


def _plain(value: Any) -> Any:
    """Return a JSON-friendly value without executing or importing anything."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def summarize(value: Any, *, limit: int = 320) -> str:
    """Return a small, deterministic, secret-free summary of ``value``.

    Mapping keys that look like credentials are redacted, long strings and
    collections are truncated, and the result is a compact JSON string. The
    function never calls ``repr`` on arbitrary objects or executes code.
    """
    try:
        normalized = _normalize(value, depth=0)
        text = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        text = "<unserializable>"
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _normalize(value: Any, *, depth: int) -> Any:
    if depth > 4:
        return "<truncated>"
    plain = _plain(value)
    if isinstance(plain, dict):
        return {
            str(key): "<redacted>" if _redact_key(key) else _normalize(item, depth=depth + 1)
            for key, item in list(plain.items())[:12]
        }
    if isinstance(plain, (list, tuple, set)):
        return [_normalize(item, depth=depth + 1) for item in list(plain)[:12]]
    if isinstance(plain, str):
        return plain if len(plain) <= 160 else plain[:157] + "..."
    return plain


def _redact(value: Any) -> Any:
    """Recursively replace values under credential-looking keys.

    Unlike :func:`summarize`, this keeps the full payload shape so serialized
    workflow state stays readable; only secret-bearing keys are masked.
    """
    plain = _plain(value)
    if isinstance(plain, dict):
        return {
            str(key): "<redacted>" if _redact_key(key) else _redact(item)
            for key, item in plain.items()
        }
    if isinstance(plain, (list, tuple, set)):
        return [_redact(item) for item in plain]
    return plain


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Clock:
    """Injectable wall-clock and monotonic clock used for deterministic tests."""

    now: Callable[[], datetime] = _utcnow
    monotonic: Callable[[], float] = time.monotonic


class ExecutionTrace:
    """Ordered execution trace with timestamps from an injectable clock."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.entries: list[TraceEntry] = []

    def record(
        self,
        *,
        task_id: str,
        agent: str,
        action: str,
        status: str,
        tool: str = "",
        attempt: int = 1,
        input_summary: str = "",
        output_summary: str = "",
        duration_seconds: float = 0.0,
    ) -> TraceEntry:
        """Append one trace event and return it."""
        entry = TraceEntry(
            step=len(self.entries) + 1,
            timestamp=self.clock.now(),
            task_id=task_id,
            agent=agent,
            tool=tool,
            action=action,
            status=status,
            attempt=attempt,
            input_summary=input_summary,
            output_summary=output_summary,
            duration_seconds=max(0.0, float(duration_seconds)),
        )
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable trace payload."""
        return {
            "entry_count": len(self.entries),
            "entries": [entry.model_dump(mode="json") for entry in self.entries],
        }

    def to_json(self) -> str:
        """Return the trace as deterministic JSON."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def summary(self) -> str:
        """Return a one-line summary of the trace."""
        return f"{len(self.entries)} trace event(s)."


class WorkflowState:
    """Run state for one workflow.

    The baseline twin is read through ``baseline_accessor`` (the existing
    session accessor in the UI); it is never copied into this object. Tasks may
    produce a *derived* working twin, which is stored as the current twin.
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        *,
        baseline_accessor: Callable[[], DigitalTwin | None] | None = None,
        trace: ExecutionTrace | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.plan = plan
        self.clock = clock or Clock()
        self.trace = trace or ExecutionTrace(self.clock)
        self._baseline_accessor = baseline_accessor or (lambda: None)
        self.tasks: dict[str, TaskState] = {
            task.id: TaskState(id=task.id) for task in plan.tasks
        }
        self.inputs: dict[str, BaseModel] = {}
        self.results: dict[str, Any] = {}
        self.working_twin: DigitalTwin | None = None
        self.stop_reason: WorkflowStopReason | None = None
        self.error: str = ""
        self.steps = 0
        self.replans = 0

    @property
    def baseline_twin(self) -> DigitalTwin | None:
        """Return the baseline twin through the injected accessor."""
        return self._baseline_accessor()

    @property
    def current_twin(self) -> DigitalTwin | None:
        """Return the derived working twin, or the baseline when none exists."""
        return self.working_twin if self.working_twin is not None else self.baseline_twin

    def result(self, task_id: str) -> Any:
        """Return a completed task result (``None`` when absent)."""
        return self.results.get(task_id)

    def status(self, task_id: str) -> TaskStatus:
        """Return one task's status."""
        return self.tasks[task_id].status

    def succeeded(self) -> bool:
        """Return whether every task completed successfully."""
        return all(
            task.status is TaskStatus.succeeded for task in self.tasks.values()
        )

    def ordered_task_ids(self) -> list[str]:
        """Return task ids in deterministic dependency order."""
        order: list[str] = []
        remaining = list(self.plan.tasks)
        done: set[str] = set()
        while remaining:
            progressed = False
            for task in list(remaining):
                if all(dependency in done for dependency in task.dependencies):
                    order.append(task.id)
                    done.add(task.id)
                    remaining.remove(task)
                    progressed = True
            if not progressed:
                break
        return order

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable state snapshot (baseline twin excluded)."""
        return {
            "plan": _redact(self.plan.model_dump(mode="json")),
            "tasks": {
                task_id: task.model_dump(mode="json")
                for task_id, task in self.tasks.items()
            },
            "inputs": {
                task_id: (
                    _redact(value)
                    if isinstance(value, BaseModel)
                    else summarize(value)
                )
                for task_id, value in self.inputs.items()
            },
            "results": {
                task_id: (
                    _redact(value)
                    if isinstance(value, BaseModel)
                    else summarize(value)
                )
                for task_id, value in self.results.items()
            },
            "working_twin": (
                self.working_twin.model_dump(mode="json")
                if self.working_twin is not None
                else None
            ),
            "stop_reason": (
                self.stop_reason.value if self.stop_reason is not None else None
            ),
            "error": self.error,
            "steps": self.steps,
            "replans": self.replans,
        }


def workflow_cycle_error(plan: WorkflowPlan) -> list[str]:
    """Return a human-readable cycle path when the plan is not a DAG."""
    known = {task.id for task in plan.tasks}
    dependencies = {
        task.id: tuple(dep for dep in task.dependencies if dep in known)
        for task in plan.tasks
    }
    temporary: set[str] = set()
    permanent: set[str] = set()
    stack: list[str] = []

    def visit(task_id: str) -> list[str] | None:
        if task_id in permanent:
            return None
        if task_id in temporary:
            start = stack.index(task_id)
            return [*stack[start:], task_id]
        temporary.add(task_id)
        stack.append(task_id)
        for dependency in dependencies.get(task_id, ()):
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        stack.pop()
        temporary.remove(task_id)
        permanent.add(task_id)
        return None

    for task_id in dependencies:
        cycle = visit(task_id)
        if cycle is not None:
            return cycle
    return []


def missing_dependencies(plan: WorkflowPlan) -> list[str]:
    """Return task ids referenced as dependencies but not present in the plan."""
    known = {task.id for task in plan.tasks}
    missing: list[str] = []
    for task in plan.tasks:
        missing.extend(
            dependency for dependency in task.dependencies if dependency not in known
        )
    return sorted(set(missing))


def iter_entries(trace: ExecutionTrace) -> Iterable[TraceEntry]:
    """Return trace entries in recording order."""
    return tuple(trace.entries)


__all__ = [
    "Clock",
    "ExecutionTrace",
    "TaskState",
    "TaskStatus",
    "TraceEntry",
    "WorkflowPlan",
    "WorkflowState",
    "WorkflowStopReason",
    "WorkflowTask",
    "iter_entries",
    "missing_dependencies",
    "summarize",
    "workflow_cycle_error",
]
