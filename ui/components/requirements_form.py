"""Structured requirements form and deterministic design-plan runner.

The form is intentionally small and explicit: no free-form natural language is
interpreted here. It builds a typed :class:`~core.schemas.requirements.
NetworkRequirements`, runs the deterministic eleven-step agent plan with no LLM,
and shows the task statuses, execution trace, and report. Nothing is applied to
the baseline twin automatically.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from agents import DocumentationOutput, Orchestrator, WorkflowState
from core.exceptions import NetArchitectError
from core.schemas.organization import Department, Organization, Site
from core.schemas.requirements import NetworkRequirements, UserFacts
from ui import state
from ui.components import format_error

PLAN_STATE_KEY = "structured_plan_state"
RUN_BUTTON_KEY = "run_structured_plan"
DEPARTMENT_COUNT_KEY = "req_dept_count"
ORG_NAME_KEY = "req_org_name"
SITE_NAME_KEY = "req_site_name"
GOALS_KEY = "req_goals"
CONSTRAINTS_KEY = "req_constraints"
MAX_DEPARTMENTS = 6

_DEFAULTS = (
    ("Engineering", 25),
    ("Sales", 12),
    ("Operations", 8),
    ("Guest users", 4),
    ("Support", 6),
    ("Lab", 2),
)


def _department_keys(index: int) -> tuple[str, str]:
    return f"req_dept_name_{index}", f"req_dept_users_{index}"


def build_requirements(
    *,
    organization_name: str,
    site_name: str,
    departments: list[tuple[str, int]],
    design_goals: list[str],
    constraints: list[str],
) -> NetworkRequirements:
    """Build typed requirements from already-cleaned form values."""
    cleaned = [
        (name.strip(), max(0, int(users)))
        for name, users in departments
        if name.strip()
    ]
    if not cleaned:
        raise ValueError("At least one department with a name is required.")
    site = Site(
        id="site-1",
        name=site_name.strip() or "Main site",
        departments=[
            Department(
                id=f"dept-{index + 1}",
                name=name,
                user_count=users,
            )
            for index, (name, users) in enumerate(cleaned)
        ],
    )
    organization = Organization(
        id="org-1",
        name=organization_name.strip() or "Organization",
        sites=[site],
    )
    return NetworkRequirements(
        user_provided=UserFacts(
            organization=organization,
            total_user_count=sum(users for _, users in cleaned),
            constraints=[line.strip() for line in constraints if line.strip()],
        ),
        design_goals=[line.strip() for line in design_goals if line.strip()],
    )


def _form_requirements() -> NetworkRequirements:
    count = int(st.session_state.get(DEPARTMENT_COUNT_KEY, 2))
    departments: list[tuple[str, int]] = []
    for index in range(min(MAX_DEPARTMENTS, count)):
        name_key, users_key = _department_keys(index)
        name = str(st.session_state.get(name_key, "")).strip()
        users = int(st.session_state.get(users_key, 0))
        if name:
            departments.append((name, users))
    goals = str(st.session_state.get(GOALS_KEY, "")).splitlines()
    constraints = str(st.session_state.get(CONSTRAINTS_KEY, "")).splitlines()
    return build_requirements(
        organization_name=str(st.session_state.get(ORG_NAME_KEY, "")),
        site_name=str(st.session_state.get(SITE_NAME_KEY, "")),
        departments=departments,
        design_goals=goals,
        constraints=constraints,
    )


def _task_frame(plan_state: WorkflowState) -> pd.DataFrame:
    rows = []
    for task in plan_state.plan.tasks:
        task_state = plan_state.tasks[task.id]
        rows.append(
            {
                "task": task.id,
                "agent": task.agent,
                "description": task.description,
                "status": task_state.status.value,
                "attempts": task_state.attempts,
                "replans": task_state.replans,
                "error": task_state.error,
                "skipped_reason": task_state.skipped_reason,
            }
        )
    return pd.DataFrame(rows)


def _trace_frame(plan_state: WorkflowState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "step": entry.step,
                "timestamp": entry.timestamp.isoformat(),
                "task": entry.task_id,
                "agent": entry.agent,
                "action": entry.action,
                "status": entry.status,
                "tool": entry.tool,
                "attempt": entry.attempt,
                "duration_seconds": round(entry.duration_seconds, 4),
            }
            for entry in plan_state.trace.entries
        ]
    )


def _render_plan(plan_state: WorkflowState) -> None:
    st.subheader("Deterministic plan result")
    stop = plan_state.stop_reason.value if plan_state.stop_reason else "unknown"
    if stop == "completed":
        st.success(f"Plan completed. Stop reason: {stop}.")
    else:
        st.error(f"Plan stopped: {stop}.")
        if plan_state.error:
            st.caption(plan_state.error)

    succeeded = sum(
        1 for task in plan_state.tasks.values() if task.status.value == "succeeded"
    )
    metric_columns = st.columns(4)
    metric_columns[0].metric("Tasks succeeded", f"{succeeded}/{len(plan_state.tasks)}")
    metric_columns[1].metric("Steps", plan_state.steps)
    metric_columns[2].metric("Re-plans", plan_state.replans)
    metric_columns[3].metric("Trace events", len(plan_state.trace.entries))

    st.markdown("**Task statuses**")
    st.dataframe(_task_frame(plan_state), hide_index=True, width="stretch")

    report = plan_state.result("report")
    if report is not None:
        st.markdown(f"### {report.headline}")
        for section in report.sections:
            st.markdown(f"**{section.title}**")
            st.write(section.body)

    documentation = plan_state.result("documentation")
    if isinstance(documentation, DocumentationOutput) and documentation.assumptions:
        st.markdown("**Assumptions (system-inferred)**")
        st.markdown("\n".join(f"- {item}" for item in documentation.assumptions))

    with st.expander("Execution trace", expanded=False):
        st.dataframe(_trace_frame(plan_state), hide_index=True, width="stretch")
        st.download_button(
            "Download trace JSON",
            data=plan_state.trace.to_json(),
            file_name="structured-plan-trace.json",
            mime="application/json",
            key="download_structured_plan_trace",
        )

    if plan_state.working_twin is not None:
        st.caption(
            "The plan produced a derived working twin. Your baseline digital twin "
            "was not replaced; saving the derived design is a separate action."
        )


def render_requirements_form() -> None:
    """Render the structured form, run the deterministic plan, and show results."""
    st.subheader("Structured design plan (no API key required)")
    st.caption(
        "This form exercises the deterministic workflow: requirements -> topology "
        "-> IP/VLAN -> routing -> validation -> simulation -> optimization -> "
        "re-validation -> report. No LLM is called and the baseline twin is not "
        "modified."
    )

    st.text_input(
        "Organization name",
        value="Acme",
        key=ORG_NAME_KEY,
    )
    st.text_input(
        "Site name",
        value="Headquarters",
        key=SITE_NAME_KEY,
    )
    st.number_input(
        "Departments",
        min_value=1,
        max_value=MAX_DEPARTMENTS,
        value=2,
        step=1,
        key=DEPARTMENT_COUNT_KEY,
    )
    count = int(st.session_state.get(DEPARTMENT_COUNT_KEY, 2))
    for index in range(min(MAX_DEPARTMENTS, count)):
        name_key, users_key = _department_keys(index)
        default_name, default_users = _DEFAULTS[index]
        columns = st.columns([3, 1])
        columns[0].text_input(
            f"Department {index + 1}",
            value=default_name,
            key=name_key,
        )
        columns[1].number_input(
            "Users",
            min_value=0,
            max_value=1_000_000,
            value=int(default_users),
            step=1,
            key=users_key,
        )

    st.text_area(
        "Design goals (one per line)",
        value="Keep the design simple and fully connected",
        key=GOALS_KEY,
    )
    st.text_area(
        "Constraints (one per line)",
        placeholder="For example: base network: 10.20.0.0/16",
        key=CONSTRAINTS_KEY,
    )

    if st.button(
        "Run deterministic design plan",
        type="primary",
        key=RUN_BUTTON_KEY,
    ):
        try:
            requirements = _form_requirements()
        except (ValidationError, ValueError) as error:
            st.error(format_error(error))
        else:
            try:
                plan_state = Orchestrator(
                    baseline_accessor=state.get_twin
                ).run_structured(requirements)
            except NetArchitectError as error:
                st.error(format_error(error))
            else:
                state.session_set(PLAN_STATE_KEY, plan_state)
                st.success("Deterministic plan finished.")

    plan_state = state.session_get(PLAN_STATE_KEY)
    if isinstance(plan_state, WorkflowState):
        _render_plan(plan_state)
    else:
        st.info("Run the form to build a deterministic plan and see its trace.")


__all__ = [
    "CONSTRAINTS_KEY",
    "DEPARTMENT_COUNT_KEY",
    "GOALS_KEY",
    "MAX_DEPARTMENTS",
    "ORG_NAME_KEY",
    "PLAN_STATE_KEY",
    "RUN_BUTTON_KEY",
    "SITE_NAME_KEY",
    "build_requirements",
    "render_requirements_form",
]
