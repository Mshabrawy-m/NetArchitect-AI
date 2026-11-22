"""Compact executive-summary report with per-value provenance (task B4).

The document is a single-section :class:`~services.reporting.models.ReportDocument`
whose blocks are deliberately bounded so the IR can be rendered as a short PDF.
Every printed number is copied from the twin or from a supplied engine run and
is registered in ``document.values`` with step, tool, and twin fingerprint.
Missing optional inputs become explicit not-run notes with the producer page;
no placeholder number is ever invented.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from config.limits import MAX_REPORT_TABLE_ROWS
from digital_twin import failed_entities
from network.analysis import analyze_topology
from security import analyze_design
from simulation import twin_reference

from .builder import ReportSources, _Collector
from .models import (
    DISCLOSURE_TEXT,
    MODELED_ESTIMATE_LABEL,
    REPORT_SCHEMA_VERSION,
    KeyValueBlock,
    KeyValueItem,
    NoteBlock,
    ParagraphBlock,
    Provenance,
    ReportDocument,
    ReportSection,
    ReportTwin,
    TableBlock,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.copilot import DecisionRecord

EXECUTIVE_SECTION_ID: Final[str] = "executive_summary"
LANGUAGES: Final[tuple[str, ...]] = ("en", "ar")

_TOPOLOGY_STEP = "topology"
_TOPOLOGY_TOOL = "digital_twin.topology"
_TWIN_STEP = "twin"
_TWIN_TOOL = "digital_twin.TwinMetadata"
_ANALYSIS_STEP = "analysis"
_ANALYSIS_TOOL = "network.analysis"
_SIMULATION_STEP = "simulation"
_SIMULATION_TOOL = "simulation.run_scenario"
_SECURITY_STEP = "security"
_SECURITY_TOOL = "security.analyze_design"
_CAPACITY_STEP = "capacity"
_CAPACITY_TOOL = "capacity.engine.evaluate_capacity"
_DECISION_STEP = "decision"
_DECISION_TOOL = "services.copilot.decisions"
_REPORT_TOOL = "services.reporting.executive"

_MAX_RISK_ROWS = min(5, MAX_REPORT_TABLE_ROWS)

_SIMULATION_PAGE = "Simulation Lab"
_SECURITY_PAGE = "Security Analysis"
_CAPACITY_PAGE = "Capacity Planning"
_DECISION_PAGE = "Digital Twin"
_TOPOLOGY_PAGE = "Topology Editor"

EN: Final[dict[str, str]] = {
    "title": "Executive summary",
    "subtitle": "A compact view of modeled, validated design evidence.",
    "section": "Executive summary",
    "overview": (
        "The twin {name} models {devices} device(s) and {links} link(s). "
        "Twin fingerprint: {fingerprint}."
    ),
    "metrics": "Key metrics",
    "metric.served": "Served demands / total",
    "metric.utilization": "Maximum link utilization (%)",
    "metric.critical_links": "Critical links",
    "metric.overloaded_links": "Overloaded links",
    "metric.spof": "Single points of failure",
    "metric.twin_fingerprint": "Twin fingerprint",
    "metric.simulation_fingerprint": "Simulation source fingerprint",
    "metric.failure_fingerprint": "Failure sweep source fingerprint",
    "metric.capacity_fingerprint": "Capacity source fingerprint",
    "metric.simulation_status": "Simulation metrics",
    "not_run": "Not run. Produce this input on {page}.",
    "risks": "Top risks",
    "risk.id": "ID",
    "risk.severity": "Severity",
    "risk.description": "Description",
    "risk.step": "Source step",
    "risk.tool": "Source tool",
    "risk.not_run": (
        "Failure sweep and security findings were not run. Produce them on "
        "Simulation Lab / Security Analysis."
    ),
    "failure.description": (
        "Served demand loss {loss}; utilization delta {delta} percentage points."
    ),
    "capacity": "Capacity outlook",
    "capacity.horizon": "Projection horizon",
    "capacity.peak": "Projected peak utilization (%)",
    "capacity.recommendation_count": "Recommendation count",
    "capacity.recommendations": "Capacity recommendation labels",
    "capacity.source": "Capacity source fingerprint",
    "capacity.stop_reason": "Stop reason",
    "capacity.not_run": (
        "No capacity run was selected. Produce one on Capacity Planning."
    ),
    "cost": "Modeled cost / BOM proxy (proxy, not a quote)",
    "cost.tier": "Capacity tier (Mbps)",
    "cost.count": "Link count",
    "cost.basis": "Basis",
    "cost.basis_value": "Twin link capacity",
    "cost.not_run": (
        "The twin has no links, so no link-based BOM proxy can be derived. "
        "Build links on Topology Editor."
    ),
    "decisions": "Recorded decisions",
    "decision.count": "Decision count",
    "decision.latest": "Latest decision",
    "decision.kind": "Kind",
    "decision.page": "Page",
    "decision.time": "Time",
    "decision.source": "Source fingerprint",
    "decision.result": "Result fingerprint",
    "decision.not_run": (
        "No decisions were supplied. Record decisions on Digital Twin."
    ),
    "limits": "Assumptions and limits",
    "limits.not_run_prefix": "Skipped inputs:",
    "limits.all_available": "All optional inputs were available.",
    "proxy.note": "Cost figures are a modeled proxy, not a quote.",
    "missing.simulation": (
        "Simulation metrics were not run; produce them on Simulation Lab."
    ),
    "missing.risks": (
        "Failure sweep and security findings were not run; produce them on "
        "Simulation Lab / Security Analysis."
    ),
    "missing.capacity": (
        "Capacity outlook was not run; produce it on Capacity Planning."
    ),
    "missing.decisions": (
        "Decision log was not supplied; record decisions on Digital Twin."
    ),
    "missing.cost": (
        "No link-based BOM proxy was available; build links on Topology Editor."
    ),
}

AR: Final[dict[str, str]] = {
    "title": "ملخص تنفيذي",
    "subtitle": "عرض مختصر لأدلة تصميم نموذجية مُتحقق منها.",
    "section": "الملخص التنفيذي",
    "overview": (
        "يصف التوأم {name} طوبولوجيا نموذجية تضم {devices} جهازًا و{links} "
        "رابطًا. بصمة التوأم: {fingerprint}."
    ),
    "metrics": "المقاييس الرئيسية",
    "metric.served": "الطلبات المخدومة من الإجمالي",
    "metric.utilization": "أقصى استخدام للروابط (%)",
    "metric.critical_links": "الروابط الحرجة",
    "metric.overloaded_links": "الروابط المحمّلة فوق الطاقة",
    "metric.spof": "نقاط الفشل المنفردة",
    "metric.twin_fingerprint": "بصمة التوأم",
    "metric.simulation_fingerprint": "بصمة مصدر المحاكاة",
    "metric.failure_fingerprint": "بصمة مصدر فحص الأعطال",
    "metric.capacity_fingerprint": "بصمة مصدر السعة",
    "metric.simulation_status": "مقاييس المحاكاة",
    "not_run": "لم يُشغّل. أنتج هذه البيانات من صفحة {page}.",
    "risks": "أبرز المخاطر",
    "risk.id": "المعرّف",
    "risk.severity": "الخطورة",
    "risk.description": "الوصف",
    "risk.step": "خطوة المصدر",
    "risk.tool": "أداة المصدر",
    "risk.not_run": (
        "لم يُشغّل فحص الأعطال ولا تحليل الأمان. أنتجهما من صفحتي "
        "Simulation Lab وSecurity Analysis."
    ),
    "failure.description": (
        "فقدان الطلبات المخدومة {loss}؛ فرق الاستخدام {delta} نقطة مئوية."
    ),
    "capacity": "توقعات السعة",
    "capacity.horizon": "أفق التوقع",
    "capacity.peak": "ذروة الاستخدام المتوقع (%)",
    "capacity.recommendation_count": "عدد التوصيات",
    "capacity.recommendations": "تسميات توصيات السعة",
    "capacity.source": "بصمة مصدر السعة",
    "capacity.stop_reason": "سبب التوقف",
    "capacity.not_run": "لم يتم اختيار تشغيل للسعة. أنتجه من صفحة Capacity Planning.",
    "cost": "بديل التكلفة / قائمة المواد النموذجية (تقدير تقريبي، وليس عرض سعر)",
    "cost.tier": "مستوى السعة",
    "cost.count": "عدد الروابط",
    "cost.basis": "الأساس",
    "cost.basis_value": "سعة رابط التوأم",
    "cost.not_run": (
        "لا يحتوي التوأم على روابط، لذلك لا يمكن اشتقاق بديل قائمة مواد. "
        "أضف روابط من صفحة Topology Editor."
    ),
    "decisions": "القرارات المسجلة",
    "decision.count": "عدد القرارات",
    "decision.latest": "آخر قرار",
    "decision.kind": "النوع",
    "decision.page": "الصفحة",
    "decision.time": "الوقت",
    "decision.source": "بصمة المصدر",
    "decision.result": "بصمة النتيجة",
    "decision.not_run": "لم يتم تقديم قرارات. سجّل القرارات من صفحة Digital Twin.",
    "limits": "الافتراضات والقيود",
    "limits.not_run_prefix": "المدخلات المتخطاة:",
    "limits.all_available": "جميع المدخلات الاختيارية كانت متاحة.",
    "proxy.note": "أرقام التكلفة تقدير نموذجي، وليست عرض سعر.",
    "missing.simulation": "لم تُشغّل مقاييس المحاكاة؛ أنتجها من صفحة Simulation Lab.",
    "missing.risks": (
        "لم يُشغّل فحص الأعطال ولا تحليل الأمان؛ أنتجهما من صفحتي "
        "Simulation Lab وSecurity Analysis."
    ),
    "missing.capacity": "لم تُشغّل توقعات السعة؛ أنتجها من صفحة Capacity Planning.",
    "missing.decisions": "لم يتم تقديم سجل قرارات؛ سجّل القرارات من صفحة Digital Twin.",
    "missing.cost": "لا يوجد بديل قائمة مواد مستند إلى الروابط؛ أضف روابط من صفحة Topology Editor.",
}


def _prov(
    step: str,
    tool: str,
    fingerprint: str,
    *,
    twin_version: str | None = None,
) -> Provenance:
    """Build provenance, defaulting to the current twin fingerprint."""
    return Provenance(step=step, tool=tool, twin_version=twin_version or fingerprint)


def _labels_for(language: str) -> dict[str, str]:
    if language == "en":
        return EN
    if language == "ar":
        return AR
    raise ValueError(f"Unsupported executive summary language: {language!r}")


def _decision_records(
    sources: ReportSources,
    decisions: Sequence[DecisionRecord],
) -> tuple[DecisionRecord, ...]:
    """Return keyword-supplied decisions, falling back to the sources log."""
    if decisions:
        return tuple(decisions)
    log = getattr(sources, "decisions", None)
    records = getattr(log, "records", None)
    return tuple(records or ())


def _simulation_state(
    sources: ReportSources,
) -> tuple[Any, str, str, str] | None:
    """Return the freshest evaluated baseline state and its provenance."""
    run = sources.scenario_run
    if run is not None:
        return (
            run.baseline_state,
            run.baseline_twin.fingerprint,
            _SIMULATION_STEP,
            _SIMULATION_TOOL,
        )
    capacity_run = sources.capacity_run
    if capacity_run is not None:
        return (
            capacity_run.baseline,
            capacity_run.twin_fingerprint,
            _CAPACITY_STEP,
            _CAPACITY_TOOL,
        )
    return None


def _security_findings(sources: ReportSources) -> tuple[Any, ...]:
    """Return findings for the twin's stored security model, if any."""
    security_model = sources.twin.security
    if security_model is None:
        return ()
    analysis = sources.security_analysis
    if analysis is None or analysis.model != security_model:
        analysis = analyze_design(sources.twin)
    return tuple(analysis.findings)


def _capacity_peak(capacity_run: Any) -> float:
    """Return the engine's projected peak utilization over the whole horizon."""
    if capacity_run.bottlenecks:
        return max(
            item.peak_utilization_percent for item in capacity_run.bottlenecks
        )
    if capacity_run.steps:
        return max(
            load.utilization_percent
            for step in capacity_run.steps
            for load in step.state.links
        )
    return max(
        (load.utilization_percent for load in capacity_run.baseline.links),
        default=0.0,
    )


def _text_item(
    *,
    values: _Collector,
    record_key: str,
    label: str,
    text: str,
    item_key: str,
    step: str,
    tool: str,
    fingerprint: str,
    twin_version: str,
) -> KeyValueItem:
    display = values.text(
        record_key,
        label,
        text,
        step=step,
        tool=tool,
        twin_version=twin_version,
    )
    return KeyValueItem(
        key=item_key,
        value=display,
        provenance=_prov(step, tool, fingerprint, twin_version=twin_version),
    )


def _overview_block(
    sources: ReportSources,
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
) -> ParagraphBlock:
    twin = sources.twin
    name = values.scan(
        "executive.twin_name",
        "Twin name",
        twin.metadata.name,
        step=_TWIN_STEP,
        tool=_TWIN_TOOL,
    )
    devices = values.number(
        "executive.device_count",
        "Devices",
        len(twin.topology.devices),
        step=_TOPOLOGY_STEP,
        tool=_TOPOLOGY_TOOL,
        digits=0,
    )
    links = values.number(
        "executive.link_count",
        "Links",
        len(twin.topology.links),
        step=_TOPOLOGY_STEP,
        tool=_TOPOLOGY_TOOL,
        digits=0,
    )
    version = values.text(
        "executive.twin_fingerprint",
        "Twin fingerprint",
        fingerprint,
        step=_TWIN_STEP,
        tool="simulation.twin_fingerprint",
    )
    return ParagraphBlock(
        text=labels["overview"].format(
            name=name,
            devices=devices,
            links=links,
            fingerprint=version,
        ),
        provenance=_prov("report", _REPORT_TOOL, fingerprint),
    )


def _metrics_block(
    sources: ReportSources,
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
    analysis: Any,
) -> KeyValueBlock:
    items: list[KeyValueItem] = []
    simulation = _simulation_state(sources)
    if simulation is None:
        items.append(
            KeyValueItem(
                key=labels["metric.simulation_status"],
                value=labels["not_run"].format(page=_SIMULATION_PAGE),
                provenance=_prov(_SIMULATION_STEP, _SIMULATION_TOOL, fingerprint),
            )
        )
    else:
        state, version, step, tool = simulation
        served = values.number(
            "executive.served_demand_count",
            "Served demands",
            state.served_demand_count,
            step=step,
            tool=tool,
            twin_version=version,
            digits=0,
        )
        total = values.number(
            "executive.demand_count",
            "Total demands",
            state.demand_count,
            step=step,
            tool=tool,
            twin_version=version,
            digits=0,
        )
        utilization = values.number(
            "executive.max_utilization_percent",
            "Maximum link utilization",
            state.max_utilization_percent,
            step=step,
            tool=tool,
            twin_version=version,
            digits=2,
        )
        overloaded = values.number(
            "executive.overloaded_link_count",
            "Overloaded links",
            state.overloaded_link_count,
            step=step,
            tool=tool,
            twin_version=version,
            digits=0,
        )
        items.extend(
            [
                KeyValueItem(
                    key=labels["metric.served"],
                    value=f"{served} / {total}",
                    provenance=_prov(step, tool, fingerprint, twin_version=version),
                ),
                KeyValueItem(
                    key=labels["metric.utilization"],
                    value=utilization,
                    unit="%",
                    provenance=_prov(step, tool, fingerprint, twin_version=version),
                ),
                KeyValueItem(
                    key=labels["metric.overloaded_links"],
                    value=overloaded,
                    provenance=_prov(step, tool, fingerprint, twin_version=version),
                ),
            ]
        )

    critical = values.number(
        "executive.critical_link_count",
        "Critical links",
        len(analysis.critical_links.links),
        step=_ANALYSIS_STEP,
        tool=f"{_ANALYSIS_TOOL}.critical_links",
        digits=0,
    )
    spof = values.number(
        "executive.spof_count",
        "Single points of failure",
        len(analysis.spof.entries),
        step=_ANALYSIS_STEP,
        tool=f"{_ANALYSIS_TOOL}.spof_report",
        digits=0,
    )
    items.extend(
        [
            KeyValueItem(
                key=labels["metric.critical_links"],
                value=critical,
                provenance=_prov(_ANALYSIS_STEP, _ANALYSIS_TOOL, fingerprint),
            ),
            KeyValueItem(
                key=labels["metric.spof"],
                value=spof,
                provenance=_prov(_ANALYSIS_STEP, _ANALYSIS_TOOL, fingerprint),
            ),
            _text_item(
                values=values,
                record_key="executive.twin_fingerprint_metrics",
                label="Twin fingerprint",
                text=fingerprint,
                item_key=labels["metric.twin_fingerprint"],
                step=_TWIN_STEP,
                tool="simulation.twin_fingerprint",
                fingerprint=fingerprint,
                twin_version=fingerprint,
            ),
        ]
    )
    if simulation is not None:
        _, version, step, tool = simulation
        items.append(
            _text_item(
                values=values,
                record_key="executive.simulation_fingerprint",
                label="Simulation source fingerprint",
                text=version,
                item_key=labels["metric.simulation_fingerprint"],
                step=step,
                tool="simulation.twin_fingerprint",
                fingerprint=fingerprint,
                twin_version=version,
            )
        )
    sweep = sources.failure_sweep
    if sweep is not None:
        items.append(
            _text_item(
                values=values,
                record_key="executive.failure_fingerprint",
                label="Failure sweep source fingerprint",
                text=sweep.baseline.fingerprint or fingerprint,
                item_key=labels["metric.failure_fingerprint"],
                step=_SIMULATION_STEP,
                tool="simulation.run_failure_sweep",
                fingerprint=fingerprint,
                twin_version=sweep.baseline.fingerprint or fingerprint,
            )
        )
    capacity_run = sources.capacity_run
    if capacity_run is not None:
        items.append(
            _text_item(
                values=values,
                record_key="executive.capacity_fingerprint_metrics",
                label="Capacity source fingerprint",
                text=capacity_run.twin_fingerprint or fingerprint,
                item_key=labels["metric.capacity_fingerprint"],
                step=_CAPACITY_STEP,
                tool=_CAPACITY_TOOL,
                fingerprint=fingerprint,
                twin_version=capacity_run.twin_fingerprint or fingerprint,
            )
        )
    return KeyValueBlock(title=labels["metrics"], items=tuple(items))


def _risks_block(
    sources: ReportSources,
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
) -> tuple[TableBlock | NoteBlock, bool]:
    rows: list[tuple[str, ...]] = []
    sweep = sources.failure_sweep
    findings = _security_findings(sources)
    total_rows = (len(sweep.cases) if sweep is not None else 0) + len(findings)

    if sweep is not None:
        version = sweep.baseline.fingerprint or fingerprint
        for index, case in enumerate(sweep.cases[:_MAX_RISK_ROWS]):
            loss = values.number(
                f"executive.risk.sweep.{index}.loss",
                "Served demand loss",
                case.impact.served_demand_delta,
                step=_SIMULATION_STEP,
                tool="simulation.run_failure_sweep",
                twin_version=version,
                digits=0,
            )
            delta = values.number(
                f"executive.risk.sweep.{index}.delta",
                "Maximum utilization delta",
                case.impact.max_utilization_delta,
                step=_SIMULATION_STEP,
                tool="simulation.run_failure_sweep",
                twin_version=version,
                digits=2,
            )
            severity = case.state.thresholds.level_for(
                case.state.max_utilization_percent
            ).value
            rows.append(
                (
                    values.scan(
                        f"executive.risk.sweep.{index}.id",
                        "Failure case id",
                        case.plan.case_id,
                        step=_SIMULATION_STEP,
                        tool="simulation.run_failure_sweep",
                        twin_version=version,
                    ),
                    severity,
                    labels["failure.description"].format(loss=loss, delta=delta),
                    _SIMULATION_STEP,
                    "simulation.run_failure_sweep",
                )
            )

    for index, finding in enumerate(findings[: max(0, _MAX_RISK_ROWS - len(rows))]):
        code = values.scan(
            f"executive.risk.security.{index}.code",
            "Security finding code",
            finding.code,
            step=_SECURITY_STEP,
            tool=_SECURITY_TOOL,
        )
        explanation = values.scan(
            f"executive.risk.security.{index}.description",
            "Security finding explanation",
            finding.explanation,
            step=_SECURITY_STEP,
            tool=_SECURITY_TOOL,
        )
        rows.append(
            (
                code,
                finding.severity.value,
                explanation,
                _SECURITY_STEP,
                _SECURITY_TOOL,
            )
        )

    if not rows:
        note = NoteBlock(
            text=labels["risk.not_run"],
            severity="warning",
            provenance=_prov("report", _REPORT_TOOL, fingerprint),
        )
        return note, False
    table = TableBlock(
        id="executive_top_risks",
        title=labels["risks"],
        columns=(
            labels["risk.id"],
            labels["risk.severity"],
            labels["risk.description"],
            labels["risk.step"],
            labels["risk.tool"],
        ),
        rows=tuple(rows),
        total_rows=total_rows,
        provenance=_prov("report", _REPORT_TOOL, fingerprint),
    )
    return table, True


def _capacity_block(
    sources: ReportSources,
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
) -> KeyValueBlock | NoteBlock:
    run = sources.capacity_run
    if run is None:
        return NoteBlock(
            text=labels["capacity.not_run"],
            severity="warning",
            provenance=_prov(_CAPACITY_STEP, _CAPACITY_TOOL, fingerprint),
        )
    version = run.twin_fingerprint or fingerprint
    horizon = values.number(
        "executive.capacity.horizon",
        "Projection horizon",
        run.projection.horizon,
        step=_CAPACITY_STEP,
        tool=_CAPACITY_TOOL,
        twin_version=version,
        digits=0,
    )
    peak = values.number(
        "executive.capacity.peak_utilization",
        "Projected peak utilization",
        _capacity_peak(run),
        step=_CAPACITY_STEP,
        tool=_CAPACITY_TOOL,
        twin_version=version,
        digits=2,
    )
    recommendation_count = values.number(
        "executive.capacity.recommendation_count",
        "Capacity recommendation count",
        len(run.recommendations),
        step=_CAPACITY_STEP,
        tool=_CAPACITY_TOOL,
        twin_version=version,
        digits=0,
    )
    tier_labels = [
        values.scan(
            f"executive.capacity.recommendation.{index}.tier",
            "Capacity recommendation tier",
            recommendation.target_tier_name,
            step=_CAPACITY_STEP,
            tool=_CAPACITY_TOOL,
            twin_version=version,
        )
        for index, recommendation in enumerate(run.recommendations[:_MAX_RISK_ROWS])
    ]
    recommendation_text = ", ".join(dict.fromkeys(tier_labels)) or "none"
    source = _text_item(
        values=values,
        record_key="executive.capacity.source_fingerprint",
        label="Capacity source fingerprint",
        text=version,
        item_key=labels["capacity.source"],
        step=_CAPACITY_STEP,
        tool=_CAPACITY_TOOL,
        fingerprint=fingerprint,
        twin_version=version,
    )
    stop_reason = _text_item(
        values=values,
        record_key="executive.capacity.stop_reason",
        label="Capacity stop reason",
        text=run.bounds.stop_reason.value,
        item_key=labels["capacity.stop_reason"],
        step=_CAPACITY_STEP,
        tool=_CAPACITY_TOOL,
        fingerprint=fingerprint,
        twin_version=version,
    )
    return KeyValueBlock(
        title=labels["capacity"],
        items=(
            KeyValueItem(
                key=labels["capacity.horizon"],
                value=horizon,
                provenance=_prov(
                    _CAPACITY_STEP, _CAPACITY_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["capacity.peak"],
                value=peak,
                unit="%",
                provenance=_prov(
                    _CAPACITY_STEP, _CAPACITY_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["capacity.recommendation_count"],
                value=recommendation_count,
                provenance=_prov(
                    _CAPACITY_STEP, _CAPACITY_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["capacity.recommendations"],
                value=recommendation_text,
                provenance=_prov(
                    _CAPACITY_STEP, _CAPACITY_TOOL, fingerprint, twin_version=version
                ),
            ),
            source,
            stop_reason,
        ),
    )


def _cost_block(
    sources: ReportSources,
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
) -> TableBlock | NoteBlock:
    links = tuple(sources.twin.topology.links)
    if not links:
        return NoteBlock(
            text=labels["cost.not_run"],
            severity="warning",
            provenance=_prov(_TOPOLOGY_STEP, _TOPOLOGY_TOOL, fingerprint),
        )
    grouped = Counter(link.capacity_mbps for link in links)
    rows: list[tuple[str, ...]] = []
    for index, (capacity, count) in enumerate(sorted(grouped.items())):
        tier = values.number(
            f"executive.cost.{index}.tier",
            "Capacity tier",
            capacity,
            step=_TOPOLOGY_STEP,
            tool=_TOPOLOGY_TOOL,
            unit="Mbps",
            digits=2,
        )
        link_count = values.number(
            f"executive.cost.{index}.count",
            "Links in capacity tier",
            count,
            step=_TOPOLOGY_STEP,
            tool=_TOPOLOGY_TOOL,
            digits=0,
        )
        rows.append((tier, link_count, labels["cost.basis_value"]))
    return TableBlock(
        id="executive_cost_proxy",
        title=labels["cost"],
        columns=(labels["cost.tier"], labels["cost.count"], labels["cost.basis"]),
        rows=tuple(rows),
        total_rows=len(rows),
        provenance=_prov("report", _REPORT_TOOL, fingerprint),
    )


def _decisions_block(
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
    records: tuple[DecisionRecord, ...],
) -> KeyValueBlock | NoteBlock:
    if not records:
        return NoteBlock(
            text=labels["decision.not_run"],
            severity="warning",
            provenance=_prov(_DECISION_STEP, _DECISION_TOOL, fingerprint),
        )
    latest = records[-1]
    version = latest.source_fingerprint or fingerprint
    count = values.number(
        "executive.decision.count",
        "Recorded decisions",
        len(records),
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
        digits=0,
    )
    title = values.scan(
        "executive.decision.title",
        "Decision title",
        latest.title,
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
    )
    kind = values.text(
        "executive.decision.kind",
        "Decision kind",
        latest.kind.value.replace("_", " "),
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
    )
    page = values.text(
        "executive.decision.page",
        "Decision page",
        latest.page,
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
    )
    timestamp = values.scan(
        "executive.decision.time",
        "Decision time",
        latest.created_at.isoformat(),
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
    )
    source = values.scan(
        "executive.decision.source",
        "Decision source fingerprint",
        latest.source_fingerprint or "not recorded",
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
    )
    result = values.scan(
        "executive.decision.result",
        "Decision result fingerprint",
        latest.result_fingerprint or "not recorded",
        step=_DECISION_STEP,
        tool=_DECISION_TOOL,
        twin_version=version,
    )
    return KeyValueBlock(
        title=labels["decisions"],
        items=(
            KeyValueItem(
                key=labels["decision.count"],
                value=count,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["decision.latest"],
                value=title,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["decision.kind"],
                value=kind,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["decision.page"],
                value=page,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["decision.time"],
                value=timestamp,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["decision.source"],
                value=source,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
            KeyValueItem(
                key=labels["decision.result"],
                value=result,
                provenance=_prov(
                    _DECISION_STEP, _DECISION_TOOL, fingerprint, twin_version=version
                ),
            ),
        ),
    )


def _limits_block(
    labels: dict[str, str],
    values: _Collector,
    fingerprint: str,
    *,
    missing: tuple[str, ...],
) -> ParagraphBlock:
    detail = (
        f"{labels['limits.not_run_prefix']} {'; '.join(missing)}."
        if missing
        else labels["limits.all_available"]
    )
    text = (
        f"{MODELED_ESTIMATE_LABEL} {DISCLOSURE_TEXT} {detail} "
        f"{labels['proxy.note']}"
    )
    values.text(
        "executive.limits.note",
        "Assumptions and limits",
        text,
        step="report",
        tool=_REPORT_TOOL,
    )
    return ParagraphBlock(
        text=text,
        provenance=_prov("report", _REPORT_TOOL, fingerprint),
    )


def build_executive_summary(
    sources: ReportSources,
    *,
    language: str = "en",
    decisions: Sequence[DecisionRecord] = (),
) -> ReportDocument:
    """Build the bounded, single-section executive summary report."""
    labels = _labels_for(language)
    fingerprint = twin_reference(sources.twin).fingerprint
    generated_at = sources.generated_at or datetime.now(UTC)
    values = _Collector(fingerprint)

    analysis = analyze_topology(
        sources.twin.topology,
        **failed_entities(sources.twin).as_kwargs(),
    )
    records = _decision_records(sources, decisions)

    overview = _overview_block(sources, labels, values, fingerprint)
    metrics = _metrics_block(sources, labels, values, fingerprint, analysis)
    risks, has_risks = _risks_block(sources, labels, values, fingerprint)
    capacity = _capacity_block(sources, labels, values, fingerprint)
    cost = _cost_block(sources, labels, values, fingerprint)
    decision_block = _decisions_block(labels, values, fingerprint, records)

    missing: list[str] = []
    if _simulation_state(sources) is None:
        missing.append(labels["missing.simulation"])
    if not has_risks:
        missing.append(labels["missing.risks"])
    if sources.capacity_run is None:
        missing.append(labels["missing.capacity"])
    if not records:
        missing.append(labels["missing.decisions"])
    if not sources.twin.topology.links:
        missing.append(labels["missing.cost"])
    limits = _limits_block(labels, values, fingerprint, missing=tuple(missing))

    section = ReportSection(
        id=EXECUTIVE_SECTION_ID,
        title=labels["section"],
        blocks=(overview, metrics, risks, capacity, cost, decision_block, limits),
    )
    return ReportDocument(
        schema_version=REPORT_SCHEMA_VERSION,
        title=labels["title"],
        subtitle=labels["subtitle"],
        generated_at=generated_at,
        twin=ReportTwin(
            name=sources.twin.metadata.name,
            created_at=sources.twin.metadata.created_at,
            schema_version=sources.twin.metadata.schema_version,
            fingerprint=fingerprint,
        ),
        sections=(section,),
        values=tuple(values.records.values()),
    )


__all__ = [
    "AR",
    "EN",
    "EXECUTIVE_SECTION_ID",
    "LANGUAGES",
    "build_executive_summary",
]
