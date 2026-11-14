"""AppTest coverage for the Phase 10d Agent Control Center page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from agents import (
    BaseAgent,
    Orchestrator,
    WorkflowState,
    run_structured_design,
)
from agents.network_agents import TopologyInput, TopologyOutput, default_agents
from core.exceptions import AgentValidationError
from core.schemas.requirements import NetworkRequirements, UserFacts
from tests.unit.agents.helpers import sample_requirements
from ui import state
from ui.pages import agent_control_center

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


class ExplodingTopologyAgent(BaseAgent):
    """Deterministic test double that always fails its task."""

    name = "topology"
    responsibility = "Fail on purpose for the control-center test."
    input_model = TopologyInput
    output_model = TopologyOutput
    allowed_tools = frozenset()

    def run(self, payload: TopologyInput, context) -> TopologyOutput:
        raise AgentValidationError("topology engine unavailable")


def control_center() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    assert not at.exception
    at.selectbox(key="page_nav").select("Agent Control Center").run()
    assert not at.exception
    return at


def metric(at: AppTest, label: str) -> str:
    for item in at.get("metric"):
        if item.label == label:
            return item.value
    raise AssertionError(f"metric {label!r} was not rendered")


def test_without_a_workflow_the_page_explains_how_to_populate_it() -> None:
    at = control_center()

    assert any("No workflow has run" in info.value for info in at.info)
    assert not at.get("dataframe")


def test_read_only_dag_trace_and_critic_for_a_completed_workflow() -> None:
    plan_state = run_structured_design(sample_requirements())
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[agent_control_center.PLAN_SOURCES[0][1]] = plan_state
    at.run()
    at.selectbox(key="page_nav").select("Agent Control Center").run()

    assert not at.exception
    assert metric(at, "Tasks succeeded") == "11/11"
    assert metric(at, "Steps") == "11"
    assert metric(at, "Verdict") == "APPROVED"
    frames = at.get("dataframe")
    assert len(frames) >= 2
    dag = frames[0].value
    assert list(dag.columns) == [
        "step",
        "agent",
        "depends_on",
        "status",
        "attempts",
        "replans",
        "duration_seconds",
        "skipped_reason",
        "error",
    ]
    assert dag.iloc[0]["step"] == "requirements"
    assert set(dag["status"]) == {"succeeded"}
    assert at.get("download_button")
    assert any("Workflow completed" in success.value for success in at.success)


def test_unresolved_workflow_shows_the_typed_stop_reason_and_error() -> None:
    requirements = NetworkRequirements(user_provided=UserFacts())
    plan_state = Orchestrator(
        agents={**default_agents(), "topology": ExplodingTopologyAgent()},
        max_retries=0,
    ).run_structured(requirements)
    assert isinstance(plan_state, WorkflowState)
    assert plan_state.stop_reason.value == "failed"

    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[agent_control_center.PLAN_SOURCES[0][1]] = plan_state
    at.run()
    at.selectbox(key="page_nav").select("Agent Control Center").run()

    assert not at.exception
    assert any("Workflow stopped: failed" in error.value for error in at.error)
    assert any("Workflow error" in markdown.value for markdown in at.markdown)
    assert any("No critic result" in info.value for info in at.info)


def test_two_workflows_can_be_selected_by_source() -> None:
    first = run_structured_design(sample_requirements())
    second = run_structured_design(sample_requirements())
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[agent_control_center.PLAN_SOURCES[0][1]] = first
    at.session_state[agent_control_center.PLAN_SOURCES[1][1]] = second
    at.run()
    at.selectbox(key="page_nav").select("Agent Control Center").run()

    assert not at.exception
    selector = at.selectbox(key=agent_control_center.SELECTOR_KEY)
    assert list(selector.options) == [label for label, _ in agent_control_center.PLAN_SOURCES]
    selector.select(agent_control_center.PLAN_SOURCES[1][0]).run()
    assert not at.exception
    assert metric(at, "Steps") == "11"


def test_trace_json_never_contains_the_session_key() -> None:
    secret = "gsk-control-center-secret"
    plan_state = run_structured_design(sample_requirements())
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.LLM_SESSION_KEY] = secret
    at.session_state[agent_control_center.PLAN_SOURCES[0][1]] = plan_state
    at.run()
    at.selectbox(key="page_nav").select("Agent Control Center").run()

    assert not at.exception
    assert secret not in plan_state.trace.to_json()
    for name, value in at.session_state.to_dict().items():
        if name == state.LLM_SESSION_KEY:
            continue
        assert secret not in str(value), f"session key {name!r} leaked the secret"
