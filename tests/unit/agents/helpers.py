"""Shared builders for agent-framework unit tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from agents import BaseAgent, Clock, WorkflowPlan, WorkflowTask
from core.schemas.organization import Department, Organization, Site
from core.schemas.requirements import NetworkRequirements, UserFacts


def sample_requirements() -> NetworkRequirements:
    """Return a deterministic two-department requirement set."""
    site = Site(
        id="site-1",
        name="Headquarters",
        departments=[
            Department(id="dept-eng", name="Engineering", user_count=25),
            Department(id="dept-sales", name="Sales", user_count=12),
        ],
    )
    return NetworkRequirements(
        user_provided=UserFacts(
            organization=Organization(
                id="org-1",
                name="Acme",
                sites=[site],
            ),
            sites=[site],
            total_user_count=37,
        ),
        design_goals=["Keep the design simple and fully connected"],
    )


class MarkerInput(BaseModel):
    """Simple input carrying one integer."""

    value: int = 0
    api_key: str = ""


class MarkerOutput(BaseModel):
    """Simple output recording the producing agent."""

    agent: str
    value: int


class MarkerAgent(BaseAgent):
    """Agent that records its execution order and returns a typed result."""

    input_model = MarkerInput
    output_model = MarkerOutput
    allowed_tools = frozenset()

    def __init__(self, name: str, order: list[str]) -> None:
        self.name = name
        self.responsibility = "Test marker agent."
        self._order = order

    def run(self, payload: MarkerInput, context) -> MarkerOutput:
        self._order.append(self.name)
        return MarkerOutput(agent=self.name, value=payload.value + 1)


def chain_plan(*names: str) -> WorkflowPlan:
    """Return a linear plan where each task depends on the previous one."""
    tasks = []
    previous: str | None = None
    for name in names:
        tasks.append(
            WorkflowTask(
                id=name,
                agent=name,
                dependencies=() if previous is None else (previous,),
            )
        )
        previous = name
    return WorkflowPlan(name="Test chain", tasks=tuple(tasks))


def marker_agents(
    order: list[str],
    *names: str,
) -> dict[str, MarkerAgent]:
    """Return marker agents for every requested name."""
    return {name: MarkerAgent(name, order) for name in names}


def fixed_clock(*, step: float = 1.0) -> tuple[Clock, Callable[[], float]]:
    """Return a clock whose monotonic value advances by ``step`` per call."""
    state = {"value": 0.0}

    def monotonic() -> float:
        current = state["value"]
        state["value"] += step
        return current

    clock = Clock(now=lambda: datetime(2026, 1, 1, tzinfo=UTC), monotonic=monotonic)
    return clock, monotonic
