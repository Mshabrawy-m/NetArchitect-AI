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
from capacity import CapacityRun
from config.limits import MAX_REPORT_TABLE_ROWS
from core.exceptions import ReportError
from digital_twin import DigitalTwin
from optimization import OptimizationRun, ParetoReranking, SensitivityReport
from services.reporting import (
    EXECUTIVE_SECTION_ID,
    KeyValueBlock,
    NoteBlock,
    ParagraphBlock,
    ReportDocument,
    ReportSection,
    ReportSources,
    TableBlock,
    build_executive_summary,
    build_report,
    check_consistency,
    filter_sections,
)
from simulation import (
    FailureSweepResult,
    RoutingModeComparison,
    ScenarioRun,
    twin_fingerprint,
)
from ui import i18n, state
from ui.cache import (
    cached_executive_exports,
    cached_exports,
    cached_report,
    capacity_source_payload,
    decisions_payload,
    source_payload,
    twin_payload,
)
from ui.components import empty_state, format_error, model_estimate_note, page_header
from ui.pages.agent_control_center import PLAN_SOURCES

WORKFLOW_KEY = "reports_workflow_source"
SIMULATION_KEY = "reports_simulation_source"
OPTIMIZATION_KEY = "reports_optimization_source"
CAPACITY_KEY = "reports_capacity_source"
SWEEP_KEY = "reports_sweep_source"
MODE_COMPARE_KEY = "reports_mode_compare_source"
SENSITIVITY_KEY = "reports_sensitivity_source"
RERANK_KEY = "reports_rerank_source"
SECTIONS_KEY = "reports_sections"
EXECUTIVE_PDF_KEY = "reports_executive_pdf"
EXECUTIVE_MARKDOWN_KEY = "reports_executive_markdown"

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


def _select_capacity() -> CapacityRun | None:
    runs = state.peek_capacity_runs()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {len(run.steps)} projected steps | "
        f"{len(run.recommendations)} upgrades | {run.bounds.stop_reason.value}"
        for index, run in enumerate(runs)
    ]
    selected = st.selectbox(
        "Capacity run",
        labels,
        index=len(labels) - 1,
        key=CAPACITY_KEY,
        help=(
            "Adds one retained capacity analysis with its forecast provenance "
            "and modeled upgrade recommendations. Runs are created on the "
            "Capacity Planning page."
        ),
    )
    if selected == NONE_LABEL:
        return None
    return runs[labels.index(selected) - 1]


def _select_sweep() -> FailureSweepResult | None:
    results = state.peek_simulation_sweeps()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {result.depth.value.upper()} | "
        f"{result.evaluated_cases}/{result.total_cases} cases | "
        f"{result.stop_reason.value}"
        for index, result in enumerate(results)
    ]
    selected = st.selectbox(
        i18n.t("reports.failure_sweep_source"),
        labels,
        index=len(labels) - 1,
        key=SWEEP_KEY,
        help="Adds one retained N-1/N-2 failure sweep from the Simulation Lab.",
    )
    if selected == NONE_LABEL:
        return None
    return results[labels.index(selected) - 1]


def _select_mode_comparison() -> RoutingModeComparison | None:
    results = state.peek_mode_comparisons()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {len(result.modes)} modes | "
        f"{result.scenario_id or 'baseline'}"
        for index, result in enumerate(results)
    ]
    selected = st.selectbox(
        i18n.t("reports.mode_compare_source"),
        labels,
        index=len(labels) - 1,
        key=MODE_COMPARE_KEY,
        help="Adds one retained side-by-side routing-mode comparison.",
    )
    if selected == NONE_LABEL:
        return None
    return results[labels.index(selected) - 1]


def _select_sensitivity() -> SensitivityReport | None:
    reports = state.peek_sensitivity_reports()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {report.source_algorithm.value} | "
        f"{len(report.robust_candidate_hashes)} robust | "
        f"{report.stop_reason.value}"
        for index, report in enumerate(reports)
    ]
    selected = st.selectbox(
        i18n.t("reports.sensitivity_source"),
        labels,
        index=len(labels) - 1,
        key=SENSITIVITY_KEY,
        help="Adds one retained demand/capacity sensitivity analysis.",
    )
    if selected == NONE_LABEL:
        return None
    return reports[labels.index(selected) - 1]


def _select_reranking() -> ParetoReranking | None:
    results = state.peek_rerankings()
    labels = [NONE_LABEL] + [
        f"{index + 1}. {result.source_algorithm.value} | "
        f"{len(result.items)} feasible candidates"
        for index, result in enumerate(results)
    ]
    selected = st.selectbox(
        i18n.t("reports.rerank_source"),
        labels,
        index=len(labels) - 1,
        key=RERANK_KEY,
        help="Adds one retained weight-only Pareto re-ranking result.",
    )
    if selected == NONE_LABEL:
        return None
    return results[labels.index(selected) - 1]


def _render_sources() -> tuple[
    WorkflowState | None,
    ScenarioRun | None,
    OptimizationRun | None,
    CapacityRun | None,
    FailureSweepResult | None,
    RoutingModeComparison | None,
    SensitivityReport | None,
    ParetoReranking | None,
]:
    st.subheader("Report sources")
    st.caption(
        "The report always includes the current digital twin. A retained "
        "workflow, scenario run, optimization run, capacity run, failure sweep, "
        "mode comparison, sensitivity analysis, or re-ranking is added only when "
        "it is selected here."
    )
    columns = st.columns(4)
    with columns[0]:
        workflow = _select_workflow()
    with columns[1]:
        scenario_run = _select_simulation()
    with columns[2]:
        optimization_run = _select_optimization()
    with columns[3]:
        capacity_run = _select_capacity()
    derived_columns = st.columns(4)
    with derived_columns[0]:
        sweep = _select_sweep()
    with derived_columns[1]:
        mode_comparison = _select_mode_comparison()
    with derived_columns[2]:
        sensitivity = _select_sensitivity()
    with derived_columns[3]:
        reranking = _select_reranking()
    return (
        workflow,
        scenario_run,
        optimization_run,
        capacity_run,
        sweep,
        mode_comparison,
        sensitivity,
        reranking,
    )


def _render_executive(sources: ReportSources) -> None:
    """Render the compact two-page executive summary and its downloads."""
    language = i18n.current_language()
    language_label = "العربية" if language == "ar" else "English"
    st.subheader(i18n.t("reports.executive.title"))
    st.caption(i18n.t("reports.executive.caption"))
    st.caption(
        f"{i18n.t('reports.executive.language', language=language_label)} "
        f"{i18n.t('reports.executive.language_switch')}"
    )

    try:
        document = build_executive_summary(sources, language=language)
        bundle = cached_executive_exports(document.model_dump_json(), language)
    except (ReportError, ValueError) as error:
        st.error(format_error(error), title=i18n.t("reports.executive.title"))
        return

    section = document.section(EXECUTIVE_SECTION_ID)
    notes = (
        tuple(
            block
            for block in section.blocks
            if isinstance(block, NoteBlock) and block.severity == "warning"
        )
        if section is not None
        else ()
    )
    consistency = check_consistency(document)
    if consistency.ok:
        st.success(
            i18n.t("reports.executive.consistent", count=len(document.values))
        )
    else:
        st.error(
            i18n.t(
                "reports.executive.inconsistent", count=len(consistency.findings)
            )
        )
    st.caption(i18n.t("reports.executive.not_run", count=len(notes)))
    if (
        sources.scenario_run is None
        and sources.capacity_run is None
        and sources.failure_sweep is None
    ):
        st.caption(i18n.t("reports.executive.empty_sources"))
    for note in notes:
        st.caption(f"- {note.text}")

    st.caption(
        i18n.t(
            "reports.executive.pdf_ready",
            pages=bundle.pages,
            bytes=len(bundle.pdf),
        )
    )
    if bundle.warnings:
        st.warning(" ".join(bundle.warnings), title="PDF font coverage")

    slug = _safe_slug(
        f"executive-{document.twin.name}-"
        f"{document.generated_at.date().isoformat()}-{language}"
    )
    pdf_column, markdown_column = st.columns(2)
    with pdf_column:
        st.download_button(
            i18n.t("reports.executive.download_pdf"),
            data=bundle.pdf,
            file_name=f"{slug}.pdf",
            mime="application/pdf",
            key=EXECUTIVE_PDF_KEY,
        )
    with markdown_column:
        st.download_button(
            i18n.t("reports.executive.download_markdown"),
            data=bundle.markdown,
            file_name=f"{slug}.md",
            mime="text/markdown",
            key=EXECUTIVE_MARKDOWN_KEY,
        )
    st.divider()


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
        bundle = cached_exports(
            document.model_dump_json(), twin_payload(twin), i18n.current_language()
        )
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
        "PDFs use a Latin font in English mode and embed the bundled Arabic font "
        "when the interface language is Arabic; unsupported scripts are replaced "
        "with a visible notice, and the original text remains in Markdown and "
        "JSON. Configuration templates start with the line "
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
    if twin is None:
        _render_empty_state()
        return

    (
        workflow,
        scenario_run,
        optimization_run,
        capacity_run,
        sweep,
        mode_comparison,
        sensitivity,
        reranking,
    ) = _render_sources()
    generated_at = state.report_generated_at(twin_fingerprint(twin))
    optimization_source_fingerprint = (
        state.get_optimization_source_fingerprint(optimization_run)
        if optimization_run is not None
        else ""
    )
    sensitivity_source_fingerprint = (
        sensitivity.source_twin_fingerprint if sensitivity is not None else ""
    )
    rerank_source_fingerprint = (
        state.peek_rerank_source_fingerprint(reranking) if reranking is not None else ""
    )
    sources = ReportSources(
        twin=twin,
        workflow=workflow,
        scenario_run=scenario_run,
        optimization_run=optimization_run,
        capacity_run=capacity_run,
        failure_sweep=sweep,
        mode_comparison=mode_comparison,
        sensitivity_report=sensitivity,
        reranking=reranking,
        optimization_source_fingerprint=optimization_source_fingerprint,
        sensitivity_source_fingerprint=sensitivity_source_fingerprint,
        rerank_source_fingerprint=rerank_source_fingerprint,
        decisions=state.peek_copilot_decisions(),
        generated_at=generated_at,
    )
    _render_executive(sources)

    # The executive summary handles the zero case explicitly; the full report
    # still needs at least one device to have meaningful sections.
    if not twin.topology.devices:
        _render_empty_state()
        return

    try:
        if workflow is None:
            document = cached_report(
                twin_payload(twin),
                source_payload(scenario_run),
                source_payload(optimization_run),
                generated_at.isoformat(),
                capacity_payload=capacity_source_payload(capacity_run),
                optimization_source_fingerprint=optimization_source_fingerprint,
                sweep_payload=source_payload(sweep),
                mode_comparison_payload=source_payload(mode_comparison),
                sensitivity_payload=source_payload(sensitivity),
                reranking_payload=source_payload(reranking),
                sensitivity_source_fingerprint=sensitivity_source_fingerprint,
                rerank_source_fingerprint=rerank_source_fingerprint,
                decisions_json=decisions_payload(state.peek_copilot_decisions()),
            )
        else:
            # WorkflowState holds a live accessor and is not serializable, so it
            # cannot be a content-keyed cache argument. Exports are still cached.
            document = build_report(sources)
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
