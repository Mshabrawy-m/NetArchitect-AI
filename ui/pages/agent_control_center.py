"""Agent Control Center page (Phase 10d).

A read-only view of the most recent deterministic workflow: the task DAG, each
step's status, attempts, and duration, the critic verdict and findings, the
typed stop reason, errors, and the execution trace with a JSON download.

The page never runs an agent, edits a plan, or touches the digital twin.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
import streamlit as st

from agents import CriticOutput, WorkflowState
from ui import state
from ui.components.requirements_form import PLAN_STATE_KEY as FORM_PLAN_KEY
from ui.pages.ai_designer import PLAN_STATE_KEY as AI_DESIGNER_PLAN_KEY

PLAN_SOURCES: tuple[tuple[str, str], ...] = (
    ("AI Network Designer", AI_DESIGNER_PLAN_KEY),
    ("Settings structured plan", FORM_PLAN_KEY),
)
SELECTOR_KEY = "agent_control_source"


def _available_states() -> list[tuple[str, WorkflowState]]:
    available: list[tuple[str, WorkflowState]] = []
    for label, key in PLAN_SOURCES:
        value = state.session_get(key)
        if isinstance(value, WorkflowState):
            available.append((label, value))
    return available


def _select_state(
    available: list[tuple[str, WorkflowState]],
) -> tuple[str, WorkflowState]:
    if len(available) == 1:
        return available[0]
    labels = [label for label, _ in available]
    selected = st.selectbox("Workflow source", labels, key=SELECTOR_KEY)
    return next(item for item in available if item[0] == selected)


def _task_frame(plan_state: WorkflowState) -> pd.DataFrame:
    durations: dict[str, float] = defaultdict(float)
    for entry in plan_state.trace.entries:
        durations[entry.task_id] += entry.duration_seconds
    rows = []
    for task in plan_state.plan.tasks:
        task_state = plan_state.tasks[task.id]
        rows.append(
            {
                "step": task.id,
                "agent": task.agent,
                "depends_on": ", ".join(task.dependencies) or "-",
                "status": task_state.status.value,
                "attempts": task_state.attempts,
                "replans": task_state.replans,
                "duration_seconds": round(durations.get(task.id, 0.0), 4),
                "skipped_reason": task_state.skipped_reason,
                "error": task_state.error,
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


def _render_overview(plan_state: WorkflowState) -> None:
    stop = plan_state.stop_reason.value if plan_state.stop_reason else "unknown"
    if stop == "completed":
        st.success(f"Workflow completed. Stop reason: {stop}.")
    else:
        st.error(f"Workflow stopped: {stop}.")
        if plan_state.error:
            st.caption(plan_state.error)

    succeeded = sum(
        1 for task in plan_state.tasks.values() if task.status.value == "succeeded"
    )
    columns = st.columns(4)
    columns[0].metric("Tasks succeeded", f"{succeeded}/{len(plan_state.tasks)}")
    columns[1].metric("Steps", plan_state.steps)
    columns[2].metric("Re-plans", plan_state.replans)
    columns[3].metric("Trace events", len(plan_state.trace.entries))

    st.markdown("**Task DAG (read-only)**")
    st.caption(
        "Rows follow the plan's deterministic topological order. Duration is the "
        "summed wall-clock time recorded for the task's trace entries."
    )
    st.dataframe(_task_frame(plan_state), hide_index=True, width="stretch")

    if plan_state.error:
        st.markdown("**Workflow error**")
        st.code(plan_state.error, language=None)


def _render_critic(plan_state: WorkflowState) -> None:
    critic = plan_state.result("critic")
    if not isinstance(critic, CriticOutput):
        st.info("No critic result is available for this workflow.")
        return

    st.markdown("**Critic review**")
    columns = st.columns(3)
    columns[0].metric("Verdict", critic.verdict.value)
    columns[1].metric(
        "Blocking findings",
        sum(1 for finding in critic.findings if finding.blocking),
    )
    columns[2].metric("All findings", len(critic.findings))
    if critic.findings:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "severity": finding.severity.value,
                        "code": finding.code,
                        "blocking": finding.blocking,
                        "responsible_step": finding.responsible_step,
                        "entities": ", ".join(finding.entities),
                        "explanation": finding.explanation,
                        "remediation": finding.remediation,
                    }
                    for finding in critic.findings
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.success("No critic findings were recorded.")
    if critic.model_summary:
        st.caption(
            "Optional model note (not authoritative): " + critic.model_summary
        )


def _render_trace(plan_state: WorkflowState) -> None:
    st.markdown("**Execution trace**")
    st.dataframe(_trace_frame(plan_state), hide_index=True, width="stretch")
    st.download_button(
        "Download trace JSON",
        data=plan_state.trace.to_json(),
        file_name="agent-trace.json",
        mime="application/json",
        key="agent_control_trace_download",
    )


def render() -> None:
    """Render the read-only Agent Control Center."""
    st.title("Agent Control Center")
    st.write(
        "Read-only execution view of the deterministic workflow. This page does "
        "not run agents, change a plan, or modify the baseline twin."
    )

    available = _available_states()
    if not available:
        st.info(
            "No workflow has run in this session. Run the AI Network Designer or "
            "the Settings structured plan to populate this page."
        )
        return

    _, plan_state = _select_state(available)
    _render_overview(plan_state)
    st.divider()
    _render_critic(plan_state)
    st.divider()
    _render_trace(plan_state)


__all__ = [
    "PLAN_SOURCES",
    "SELECTOR_KEY",
    "render",
]
