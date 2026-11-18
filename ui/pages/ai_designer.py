"""AI Network Designer page (Phase 10d).

The page places the optional natural-language path and the deterministic
structured form side by side. The language model is used only to interpret free
text into validated requirements; the plan itself is always produced by the
deterministic agents. Without an API key the page shows the structured form
alone, with a note explaining that the form needs no key.

Results are shown read-only: the critic verdict and findings, the documentation
preview, and the trace. Saving the derived design always creates a new snapshot
and never replaces the baseline twin.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from agents import (
    CriticOutput,
    DocumentationOutput,
    Orchestrator,
    RequirementsAgentOutput,
    WorkflowState,
    export_json,
    export_markdown,
    understand_requirements,
)
from config.limits import MAX_REQUIREMENTS_TEXT_CHARS
from config.settings import get_settings
from core.exceptions import NetArchitectError
from core.schemas.requirements import NetworkRequirements, UserFacts
from services.llm import GroqProvider, LLMProvider
from ui import state
from ui.components import format_error, page_header
from ui.components.requirements_form import MAX_DEPARTMENTS, build_requirements

FREE_TEXT_KEY = "ai_designer_free_text"
UNDERSTANDING_KEY = "ai_requirements_understanding"
PLAN_STATE_KEY = "ai_designer_plan_state"
SNAPSHOT_LABEL_KEY = "ai_designer_snapshot_label"

INTERPRET_BUTTON = "ai_interpret_requirements"
RUN_BUTTON = "ai_run_workflow"
APPLY_BUTTON = "ai_save_snapshot"
CLEAR_BUTTON = "ai_clear_interpretation"

ORG_NAME_KEY = "aid_org_name"
SITE_NAME_KEY = "aid_site_name"
DEPARTMENT_COUNT_KEY = "aid_dept_count"
GOALS_KEY = "aid_goals"
CONSTRAINTS_KEY = "aid_constraints"
MERGE_FORM_KEY = "aid_merge_form"

_DEFAULTS = (
    ("Engineering", 25),
    ("Sales", 12),
    ("Operations", 8),
    ("Guest users", 4),
    ("Support", 6),
    ("Lab", 2),
)


def _department_keys(index: int) -> tuple[str, str]:
    return f"aid_dept_name_{index}", f"aid_dept_users_{index}"


def _active_key() -> str:
    """Return the session key, else the configured key, else an empty string."""
    return state.get_llm_session_key() or get_settings().GROQ_API_KEY.strip()


def _build_provider(api_key: str) -> LLMProvider:
    """Build a bounded provider for one interpretation request.

    Module-level so tests can substitute a scripted provider and never contact
    the network.
    """
    return GroqProvider.from_settings(
        api_key=api_key,
        budget=state.get_llm_budget(),
    )


def _form_requirements() -> NetworkRequirements:
    """Build typed requirements from the right-hand structured form."""
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


def _render_form() -> None:
    st.subheader("Structured requirements")
    st.caption(
        "This form is the no-key path. It runs the full deterministic workflow "
        "and never modifies the baseline twin."
    )
    st.text_input("Organization name", value="Acme", key=ORG_NAME_KEY)
    st.text_input("Site name", value="Headquarters", key=SITE_NAME_KEY)
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


def _fact_rows(facts: UserFacts) -> list[dict[str, object]]:
    """Return the user-fact departments without double counting identifiers."""
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for site in sites:
        for department in site.departments:
            if department.id in seen:
                continue
            seen.add(department.id)
            rows.append(
                {
                    "department": department.name,
                    "users": department.user_count,
                    "source": f"site {site.name}",
                }
            )
    for department in facts.departments:
        if department.id in seen:
            continue
        seen.add(department.id)
        rows.append(
            {
                "department": department.name,
                "users": department.user_count,
                "source": "department list",
            }
        )
    return rows


def _interpret(active_key: str) -> None:
    """Run the requirements agent on the free text and optional form values."""
    text = str(st.session_state.get(FREE_TEXT_KEY, "")).strip()
    requirements = None
    if st.session_state.get(MERGE_FORM_KEY, False):
        try:
            requirements = _form_requirements()
        except (ValidationError, ValueError):
            requirements = None
    try:
        provider = _build_provider(active_key)
        output = understand_requirements(
            text,
            requirements=requirements,
            provider=provider,
        )
    except NetArchitectError as error:
        st.error(format_error(error))
    else:
        state.session_set(UNDERSTANDING_KEY, output)


def _render_understanding() -> None:
    output = state.session_get(UNDERSTANDING_KEY)
    if not isinstance(output, RequirementsAgentOutput):
        return

    st.divider()
    st.subheader("Requirements interpretation")
    columns = st.columns(3)
    columns[0].metric("Status", output.status.value)
    columns[1].metric("Model used", "Yes" if output.provider_used else "No")
    columns[2].metric("Assumptions", len(output.assumptions))
    st.write(output.summary)

    if output.status.value == "unavailable":
        st.warning(output.error)
        for note in output.notes:
            st.caption(note)
    elif output.status.value == "failed":
        st.error(output.error or "Requirement extraction failed.")

    if output.facts is not None:
        st.markdown("**User-provided facts**")
        st.dataframe(
            pd.DataFrame(_fact_rows(output.facts)),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            f"Reported total: {output.facts.total_user_count} user(s). Only "
            "numbers stated literally in the text or entered in the form appear "
            "here."
        )
    else:
        st.info("No user-provided facts were produced.")

    st.markdown("**System assumptions (not user facts)**")
    if output.assumptions:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "category": assumption.category,
                        "description": assumption.description,
                        "rationale": assumption.rationale,
                    }
                    for assumption in output.assumptions
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No assumptions were inferred.")

    if output.missing_information:
        st.markdown("**Missing information**")
        st.dataframe(
            _gap_frame(output.missing_information),
            hide_index=True,
            width="stretch",
        )
    if output.contradictions:
        st.markdown("**Contradictory information**")
        st.dataframe(
            _gap_frame(output.contradictions),
            hide_index=True,
            width="stretch",
        )
    if output.questions:
        st.markdown("**Clarification questions**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "severity": question.severity.value,
                        "question": question.question,
                        "reason": question.reason,
                        "field": question.field,
                    }
                    for question in output.questions
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    if st.button("Discard interpretation", key=CLEAR_BUTTON):
        state.session_delete(UNDERSTANDING_KEY)
        state.session_delete(PLAN_STATE_KEY)
        st.rerun()


def _gap_frame(gaps) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "severity": gap.severity.value,
                "code": gap.code,
                "description": gap.description,
                "affected": ", ".join(gap.affected),
            }
            for gap in gaps
        ]
    )


def _resolved_requirements() -> NetworkRequirements:
    """Prefer a successful interpretation, else the structured form."""
    output = state.session_get(UNDERSTANDING_KEY)
    if isinstance(output, RequirementsAgentOutput) and output.requirements is not None:
        return output.requirements
    return _form_requirements()


def _run_workflow() -> None:
    try:
        requirements = _resolved_requirements()
    except (ValidationError, ValueError) as error:
        st.error(format_error(error))
        return
    try:
        plan_state = Orchestrator(
            baseline_accessor=state.get_twin
        ).run_structured(requirements)
    except NetArchitectError as error:
        st.error(format_error(error))
        return
    state.session_set(PLAN_STATE_KEY, plan_state)


def _render_critic(plan_state: WorkflowState) -> None:
    critic = plan_state.result("critic")
    if not isinstance(critic, CriticOutput):
        return
    st.markdown("**Critic verdict**")
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
        st.success("The independent critic found no issues.")
    if critic.model_summary:
        st.caption(f"Optional model note (not authoritative): {critic.model_summary}")


def _render_report(plan_state: WorkflowState) -> None:
    report = plan_state.result("documentation")
    if not isinstance(report, DocumentationOutput):
        return
    st.markdown("**Documentation preview**")
    st.write(report.summary)
    for section in report.sections:
        st.markdown(f"*{section.title}*")
        st.write(section.body)
    if report.assumptions:
        st.markdown("**Assumptions**")
        st.markdown("\n".join(f"- {item}" for item in report.assumptions))
    if report.limitations:
        st.markdown("**Limitations**")
        st.markdown("\n".join(f"- {item}" for item in report.limitations))
    if report.ai_explanation:
        label = (
            "AI explanation (rejected and replaced deterministically)"
            if report.ai_rejected
            else "AI explanation (optional, model-written)"
        )
        st.markdown(f"**{label}**")
        st.write(report.ai_explanation)
        if report.ai_note:
            st.caption(report.ai_note)
    downloads = st.columns(2)
    downloads[0].download_button(
        "Download report JSON",
        data=export_json(report),
        file_name="ai-designer-report.json",
        mime="application/json",
        key="ai_designer_report_json",
    )
    downloads[1].download_button(
        "Download report Markdown",
        data=export_markdown(report),
        file_name="ai-designer-report.md",
        mime="text/markdown",
        key="ai_designer_report_markdown",
    )


def _render_apply(plan_state: WorkflowState) -> None:
    st.markdown("**Apply this design**")
    st.caption(
        "Saving creates a new snapshot in the bounded snapshot store. The "
        "baseline digital twin is never replaced by this page."
    )
    if plan_state.working_twin is None:
        st.warning("The workflow did not produce a derived design to save.")
        return
    default_label = (
        "AI design "
        + datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    )
    label = st.text_input(
        "Snapshot label",
        value=default_label,
        key=SNAPSHOT_LABEL_KEY,
    )
    if st.button("Save as new snapshot", key=APPLY_BUTTON):
        try:
            snapshot = state.save_twin_snapshot(plan_state.working_twin, label)
        except NetArchitectError as error:
            st.error(format_error(error), title="Snapshot rejected")
        except ValueError as error:
            st.error(format_error(error), title="Snapshot rejected")
        else:
            st.success(f"Saved new snapshot {snapshot.label!r}. Baseline unchanged.")


def _render_results() -> None:
    plan_state = state.session_get(PLAN_STATE_KEY)
    if not isinstance(plan_state, WorkflowState):
        return

    st.divider()
    st.subheader("Workflow result")
    stop = plan_state.stop_reason.value if plan_state.stop_reason else "unknown"
    if stop == "completed":
        st.success(f"Workflow completed. Stop reason: {stop}.")
    else:
        st.error(f"Workflow stopped: {stop}.")
        if plan_state.error:
            st.caption(plan_state.error)
    columns = st.columns(3)
    columns[0].metric("Steps", plan_state.steps)
    columns[1].metric("Re-plans", plan_state.replans)
    columns[2].metric("Trace events", len(plan_state.trace.entries))

    report = plan_state.result("documentation")
    if isinstance(report, DocumentationOutput):
        st.markdown(f"### {report.title}")
        st.write(report.summary)
    _render_critic(plan_state)
    _render_report(plan_state)
    _render_apply(plan_state)

    with st.expander("Failure detail", expanded=False):
        failed = [
            f"{task.id}: {task.error or task.skipped_reason}"
            for task in plan_state.tasks.values()
            if task.status.value not in {"succeeded"}
        ]
        if failed:
            st.markdown("\n".join(f"- {item}" for item in failed))
        else:
            st.caption("No failed or skipped tasks.")
        if plan_state.error:
            st.caption(plan_state.error)


def render() -> None:
    """Render the AI Network Designer page."""
    page_header(
        "AI Network Designer",
        "Describe the network in free text or enter it in the structured form. "
        "The optional language model interprets free text only; topology, "
        "addressing, routing, validation, simulation, optimization, the critic, "
        "and the report are deterministic.",
    )

    active_key = _active_key()
    if active_key:
        st.caption(
            "A model key is configured. Free-text interpretation is available; "
            "results are still computed by the deterministic engines."
        )
        left, right = st.columns(2)
        with left:
            st.subheader("Natural-language requirements")
            st.text_area(
                "Describe sites, departments, user counts, and goals",
                key=FREE_TEXT_KEY,
                height=300,
                max_chars=MAX_REQUIREMENTS_TEXT_CHARS,
                placeholder=(
                    "For example: Acme has one site, Headquarters. Engineering "
                    "has 25 users and Sales has 12. The design must be resilient."
                ),
            )
            if st.button(
                "Interpret requirements",
                type="primary",
                key=INTERPRET_BUTTON,
            ):
                _interpret(active_key)
            st.checkbox(
                "Merge the structured form values into free-text interpretation",
                value=False,
                key=MERGE_FORM_KEY,
                help=(
                    "When off, the interpretation uses the free text alone. When "
                    "on, structured departments, sites, and user counts are kept "
                    "as user facts."
                ),
            )
        with right:
            _render_form()
    else:
        st.info(
            "No API key is configured, so free-text interpretation is unavailable "
            "and only the structured form is shown. The form runs the complete "
            "deterministic workflow without a key."
        )
        _render_form()

    _render_understanding()

    st.divider()
    if st.button(
        "Run deterministic workflow",
        type="primary",
        key=RUN_BUTTON,
    ):
        _run_workflow()
    st.caption(
        "Requirements -> topology -> IP/VLAN -> routing -> validation -> "
        "simulation -> optimization -> re-validation -> critic -> documentation "
        "-> report."
    )

    _render_results()


__all__ = [
    "APPLY_BUTTON",
    "CLEAR_BUTTON",
    "CONSTRAINTS_KEY",
    "DEPARTMENT_COUNT_KEY",
    "FREE_TEXT_KEY",
    "GOALS_KEY",
    "INTERPRET_BUTTON",
    "MERGE_FORM_KEY",
    "ORG_NAME_KEY",
    "PLAN_STATE_KEY",
    "RUN_BUTTON",
    "SITE_NAME_KEY",
    "SNAPSHOT_LABEL_KEY",
    "UNDERSTANDING_KEY",
    "render",
]
