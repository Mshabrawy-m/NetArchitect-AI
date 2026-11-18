"""Reports & Documentation page (Phase 11c).

The page assembles one report document from validated session data and renders a
section selector, an unavailable-section summary, a consistency check, a
preview, and in-memory downloads.

The page never calls a language model, writes a file, or contacts a device.
Every number in the report is copied from an engine and registered with the
step, tool, and twin fingerprint that produced it. Sections whose inputs are
absent stay visible as "not run" with the reason and the page that produces the
missing data.
"""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from agents import WorkflowState
from config.limits import MAX_REPORT_TABLE_ROWS
from core.exceptions import ReportError
from digital_twin import DigitalTwin
from optimization import OptimizationRun
from services.reporting import (
    KeyValueBlock,
    NoteBlock,
    ParagraphBlock,
    ReportDocument,
    ReportSection,
    ReportSources,
    TableBlock,
    build_report,
    check_consistency,
    filter_sections,
)
from simulation import ScenarioRun, twin_fingerprint
from ui import state
from ui.cache import (
    cached_exports,
    cached_report,
    source_payload,
    twin_payload,
)
from ui.components import empty_state, format_error, model_estimate_note, page_header
from ui.pages.agent_control_center import PLAN_SOURCES

WORKFLOW_KEY = "reports_workflow_source"
SIMULATION_KEY = "reports_simulation_source"
OPTIMIZATION_KEY = "reports_optimization_source"
SECTIONS_KEY = "reports_sections"

NONE_LABEL = "None"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "report"


def _workflow_choices() -> list[tuple[str, WorkflowState | None]]:
    """Return the session workflows that can feed the report."""
    choices: list[tuple[str, WorkflowState | None]] = [(NONE_LABEL, None)]
    for label, key in PLAN_SOURCES:
        value = state.session_get(key)
        if isinstance(value, WorkflowState):
            choices.append((label, value))
    return choices


def _select_workflow() -> WorkflowState | None:
    choices = _workflow_choices()
    labels = [label for label, _ in choices]
    selected = st.selectbox(
        "Workflow source",
        labels,
        index=1 if len(choices) > 1 else 0,
        key=WORKFLOW_KEY,
        help=(
            "Adds the agent execution trace. No workflow is stored in this "
            "session until one has run."
        ),
    )
    return next(value for label, value in choices if label == selected)


def _select_simulation() -> ScenarioRun | None:
    runs = state.get_simulation_runs()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {run.scenario.name} ({run.scenario.type.value})"
        for index, run in enumerate(runs)
    ]
    selected = st.selectbox(
        "Simulation run",
        labels,
        index=len(labels) - 1,
        key=SIMULATION_KEY,
        help=(
            "Adds the before/after comparison for one retained scenario run. "
            "Runs are created on the Simulation Lab page."
        ),
    )
    if selected == NONE_LABEL:
        return None
    return runs[labels.index(selected) - 1]


def _select_optimization() -> OptimizationRun | None:
    runs = state.get_optimization_runs()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {run.algorithm.value} | seed {run.seed} | "
        f"{run.stop_reason.value}"
        for index, run in enumerate(runs)
    ]
    selected = st.selectbox(
        "Optimization run",
        labels,
        index=len(labels) - 1,
        key=OPTIMIZATION_KEY,
        help=(
            "Adds one retained optimization result and its baseline "
            "comparison. Runs are created on the Optimization Center page."
        ),
    )
    if selected == NONE_LABEL:
        return None
    return runs[labels.index(selected) - 1]


def _render_sources() -> tuple[
    WorkflowState | None,
    ScenarioRun | None,
    OptimizationRun | None,
]:
    st.subheader("Report sources")
    st.caption(
        "The report always includes the current digital twin. A retained "
        "workflow, scenario run, or optimization run is added only when it is "
        "selected here."
    )
    columns = st.columns(3)
    with columns[0]:
        workflow = _select_workflow()
    with columns[1]:
        scenario_run = _select_simulation()
    with columns[2]:
        optimization_run = _select_optimization()
    return workflow, scenario_run, optimization_run


def _section_label(document: ReportDocument, section_id: str) -> str:
    section = document.section(section_id)
    if section is None:
        return section_id
    state_text = "available" if section.status.value == "available" else "not run"
    return f"{section.title} ({state_text})"


def _render_section_selection(document: ReportDocument) -> tuple[str, ...]:
    st.subheader("Sections")
    st.caption(
        "Unselected sections are omitted from the report body and section list. "
        "The source-value registry still covers the whole build so provenance "
        "stays complete. Not-run sections remain listed below with their reason "
        "and the page that produces the missing data."
    )
    selected = st.multiselect(
        "Sections to include",
        list(document.section_ids()),
        default=list(document.available_section_ids()),
        format_func=lambda section_id: _section_label(document, section_id),
        key=SECTIONS_KEY,
    )
    return tuple(selected)


def _render_unavailable(document: ReportDocument) -> None:
    missing = tuple(
        section
        for section in document.sections
        if section.status.value != "available"
    )
    st.markdown("**Sections not run**")
    if not missing:
        st.caption("Every section was produced from available data.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Section": section.title,
                    "Reason": section.unavailable_reason,
                    "Producing page": section.producer_page,
                }
                for section in missing
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def _render_key_value(block: KeyValueBlock) -> None:
    if block.title:
        st.markdown(f"**{block.title}**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Key": item.key,
                    "Value": item.value,
                    "Unit": item.unit,
                    "Source": f"{item.provenance.step} / {item.provenance.tool}",
                }
                for item in block.items
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def _render_table(block: TableBlock) -> None:
    if block.title:
        st.markdown(f"**{block.title}**")
    st.dataframe(
        pd.DataFrame(block.rows, columns=list(block.columns)),
        hide_index=True,
        width="stretch",
    )
    if block.truncated:
        st.caption(block.truncation_note())
    st.caption(
        "Source: "
        f"{block.provenance.step} / {block.provenance.tool} / "
        f"twin {block.provenance.twin_version}"
    )


def _render_note(block: NoteBlock) -> None:
    if block.severity == "warning":
        st.warning(block.text)
    elif block.severity == "limitation":
        st.caption(f"Limitation: {block.text}")
    else:
        st.info(block.text)


def _render_block(block: ParagraphBlock | KeyValueBlock | TableBlock | NoteBlock) -> None:
    if isinstance(block, ParagraphBlock):
        st.write(block.text)
    elif isinstance(block, KeyValueBlock):
        _render_key_value(block)
    elif isinstance(block, TableBlock):
        _render_table(block)
    elif isinstance(block, NoteBlock):
        _render_note(block)
    else:  # pragma: no cover - guarded by the typed document
        raise TypeError(f"Unsupported report block: {type(block).__name__}")


def _render_section(index: int, section: ReportSection) -> None:
    st.markdown(f"#### {index}. {section.title}")
    if section.status.value != "available":
        st.info(
            f"{section.unavailable_reason} Produced on: {section.producer_page}.",
            title="Section not run",
        )
        return
    for block in section.blocks:
        _render_block(block)


def _render_preview(document: ReportDocument) -> None:
    st.subheader("Preview")
    st.caption(
        "The preview renders the same typed document used by every download. "
        "Values are copied from the engines listed in each table's source line."
    )
    if not document.sections:
        st.info("No section is selected.")
        return
    for index, section in enumerate(document.sections, start=1):
        _render_section(index, section)


def _render_values(document: ReportDocument) -> None:
    with st.expander(f"Source values ({len(document.values)})"):
        st.caption(
            "The registry covers every value computed for this report, "
            "including values behind sections that are not selected. The JSON "
            "download contains the complete registry."
        )
        shown = document.values[:MAX_REPORT_TABLE_ROWS]
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Key": record.key,
                        "Label": record.label,
                        "Value": record.display,
                        "Unit": record.unit,
                        "Step": record.provenance.step,
                        "Tool": record.provenance.tool,
                        "Twin version": record.provenance.twin_version,
                    }
                    for record in shown
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        if len(document.values) > len(shown):
            st.caption(
                f"Showing first {len(shown)} of {len(document.values)} values. "
                "The JSON download contains every record."
            )


def _render_consistency(document: ReportDocument) -> None:
    st.subheader("Consistency check")
    st.caption(
        "Every printed number is compared with the sourced-value registry. "
        "IP addresses and identifier-embedded digits are masked before the "
        "comparison; the required disclosure labels and provenance are checked "
        "too."
    )
    result = check_consistency(document)
    if result.ok:
        st.success(result.summary())
    else:
        st.error(result.summary(), title="Consistency errors")
    if result.findings:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Code": finding.code.value,
                        "Severity": finding.severity.value,
                        "Section": finding.section_id or "-",
                        "Token": finding.token or "-",
                        "Message": finding.message,
                    }
                    for finding in result.findings
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No consistency findings.")


def _render_downloads(document: ReportDocument, twin: DigitalTwin) -> None:
    st.subheader("Downloads")
    st.caption(
        "Every export is generated in memory for the current section selection. "
        "Nothing is written to disk, and configuration templates are never "
        "applied to a device."
    )
    try:
        bundle = cached_exports(document.model_dump_json(), twin_payload(twin))
    except ReportError as error:
        st.error(format_error(error), title="Export failed")
        return

    if bundle.warnings:
        st.warning(" ".join(bundle.warnings), title="PDF font coverage")

    slug = _safe_slug(
        f"{document.twin.name}-{document.generated_at.date().isoformat()}"
    )
    columns = st.columns(3)
    with columns[0]:
        st.download_button(
            "Download PDF report",
            data=bundle.pdf,
            file_name=f"{slug}.pdf",
            mime="application/pdf",
            key="reports_download_pdf",
        )
        st.download_button(
            "Download Markdown report",
            data=bundle.markdown,
            file_name=f"{slug}.md",
            mime="text/markdown",
            key="reports_download_markdown",
        )
    with columns[1]:
        st.download_button(
            "Download JSON report",
            data=bundle.json,
            file_name=f"{slug}.json",
            mime="application/json",
            key="reports_download_json",
        )
        st.download_button(
            "Download CSV tables (ZIP)",
            data=bundle.csv,
            file_name=f"{slug}-tables.zip",
            mime="application/zip",
            key="reports_download_csv",
        )
    with columns[2]:
        st.download_button(
            "Download configuration templates (ZIP)",
            data=bundle.config,
            file_name=f"{slug}-templates.zip",
            mime="application/zip",
            key="reports_download_templates",
        )
    st.caption(
        "The PDF uses a Latin-only built-in font; text outside Latin is replaced "
        "with a visible notice and the original text remains in the Markdown and "
        "JSON exports. Configuration templates start with the line "
        "'TEMPLATE - not applied to any device'."
    )


def _render_empty_state() -> None:
    empty_state(
        "No digital twin with a topology is loaded. Open the Topology Editor "
        "from the sidebar to create, generate, or import one, then return here.",
        title="Digital twin required",
        hint=(
            "A report is built only from validated application data. It never "
            "uses raw model prose and never fills a missing section with a "
            "placeholder."
        ),
    )


def render() -> None:
    """Render the Reports & Documentation page."""
    page_header(
        "Reports & Documentation",
        "A provenance-tagged network design report assembled from the digital "
        "twin and the retained engineering runs. Every number is copied from "
        "an engine, and every export is generated in memory.",
    )
    model_estimate_note(
        "The report contains deterministic sections and the values behind "
        "them. This page does not request AI-written prose; every section comes "
        "from an engine or from the stored twin.",
        title="Report scope",
    )

    twin = state.get_twin()
    if twin is None or not twin.topology.devices:
        _render_empty_state()
        return

    workflow, scenario_run, optimization_run = _render_sources()
    generated_at = state.report_generated_at(twin_fingerprint(twin))
    try:
        if workflow is None:
            document = cached_report(
                twin_payload(twin),
                source_payload(scenario_run),
                source_payload(optimization_run),
                generated_at.isoformat(),
            )
        else:
            # WorkflowState holds a live accessor and is not serializable, so it
            # cannot be a content-keyed cache argument. Exports are still cached.
            document = build_report(
                ReportSources(
                    twin=twin,
                    workflow=workflow,
                    scenario_run=scenario_run,
                    optimization_run=optimization_run,
                    generated_at=generated_at,
                )
            )
    except (ReportError, ValueError) as error:
        st.error(format_error(error), title="Report could not be built")
        return

    st.caption(
        f"Twin {document.twin.name}; fingerprint {document.twin.fingerprint}. "
        f"Prepared at {document.generated_at.isoformat()}."
    )

    section_ids = _render_section_selection(document)
    st.divider()
    _render_unavailable(document)
    if not section_ids:
        st.warning(
            "Select at least one section to preview and export.",
            title="No sections selected",
        )
        return

    filtered = filter_sections(document, section_ids)
    st.divider()
    _render_consistency(filtered)
    st.divider()
    _render_preview(filtered)
    st.divider()
    _render_values(filtered)
    st.divider()
    _render_downloads(filtered, twin)
