"""Session-scoped English/Arabic UI text for NetArchitect AI.

The catalog is the single source of translated interface wording. Language is
session-only, like the twin and run history, and never written to disk. Arabic
uses a scoped direction stylesheet and Unicode isolates so Latin engineering
terms, identifiers, numbers, IPs, and CIDRs remain left-to-right. Exports and
PDFs are intentionally outside this module and remain Latin-only.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any

import streamlit as st

LANGUAGE_KEY = "ui_language"
DEFAULT_LANGUAGE = "en"
LANGUAGES: MappingProxyType[str, str] = MappingProxyType(
    {"en": "English", "ar": "العربية"}
)
DIRECTIONS: MappingProxyType[str, str] = MappingProxyType({"en": "ltr", "ar": "rtl"})

_FSI = "\u2068"
_PDI = "\u2069"

# Only injected for Arabic. It sets inherited direction; LTR tokens are isolated
# in text by :func:`protect_latin_tokens`, so no widget internals are restyled.
_RTL_CSS = """<style>
html { direction: rtl; }
.i18n-ltr { direction: ltr; unicode-bidi: isolate; }
</style>"""

EN: MappingProxyType[str, str] = MappingProxyType(
    {
        # Entry point and navigation
        "app.about": (
            "NetArchitect AI v1.0.0-rc1 - deterministic, design-time "
            "network engineering. Results are modeled from the current twin "
            "and stated assumptions. No device access, live scanning, "
            "or guaranteed outcomes. See Settings > Release limitations."
        ),
        "app.sidebar": "NetArchitect AI - deterministic network engineering first.",
        "nav.group.design": "Design",
        "nav.group.analyze": "Analyze",
        "nav.group.operate": "Operate",
        "nav.group.output": "Output",
        "nav.label.dashboard": "Dashboard",
        "nav.label.ai_network_designer": "AI Designer",
        "nav.label.topology_editor": "Topology",
        "nav.label.ip_addressing_subnetting": "IP",
        "nav.label.vlan_dhcp_planner": "VLAN/DHCP",
        "nav.label.routing_analysis": "Routing",
        "nav.label.network_analytics": "Analytics",
        "nav.label.security_analysis": "Security",
        "nav.label.digital_twin": "Digital Twin",
        "nav.label.simulation_lab": "Simulation",
        "nav.label.optimization_center": "Optimization",
        "nav.label.capacity_planning": "Capacity",
        "nav.label.reports_documentation": "Reports",
        "nav.label.agent_control_center": "Agent Center",
        "nav.label.settings": "Settings",
        "nav.help.dashboard": (
            "Session overview: design health, retained runs, and sample projects."
        ),
        "nav.help.ai_network_designer": (
            "Turn structured requirements into a deterministic design plan."
        ),
        "nav.help.topology_editor": (
            "Generate, edit, and inspect the current network topology."
        ),
        "nav.help.ip_addressing_subnetting": (
            "Plan CIDR blocks and VLSM subnets from the current design."
        ),
        "nav.help.vlan_dhcp_planner": (
            "Allocate VLANs and DHCP scopes from department requirements."
        ),
        "nav.help.routing_analysis": (
            "Inspect reachability, shortest paths, and failure paths."
        ),
        "nav.help.network_analytics": (
            "Compute graph metrics and identify structural risks."
        ),
        "nav.help.security_analysis": (
            "Model zones, policy, and design-time flow checks."
        ),
        "nav.help.digital_twin": (
            "Inspect and snapshot the single session model of the design."
        ),
        "nav.help.simulation_lab": (
            "Evaluate deterministic what-if failures and demand changes."
        ),
        "nav.help.optimization_center": (
            "Search bounded trade-offs between cost, resilience, and capacity."
        ),
        "nav.help.capacity_planning": (
            "Project utilization and forecast capacity from bounded series."
        ),
        "nav.help.reports_documentation": (
            "Generate provenance-tagged reports and in-memory downloads."
        ),
        "nav.help.agent_control_center": (
            "Review the deterministic agent trace and task outcomes."
        ),
        "nav.help.settings": (
            "Configure optional AI access and review session-only limits."
        ),
        # Page titles and primary descriptions
        "page.dashboard": "Dashboard",
        "page.dashboard.description": (
            "Current state of the digital twin and the engineering runs retained in "
            "this session."
        ),
        "page.settings": "Settings",
        "page.settings.description": (
            "Optional AI configuration, read-only safety limits, and a deterministic "
            "structured design runner that needs no API key."
        ),
        # Shared components and statuses
        "status.done": "Done",
        "status.incomplete": "Incomplete",
        "status.stale": "Stale",
        "status.ok": "Ok",
        "status.complete": "Complete",
        "status.warning": "Warning",
        "status.warn": "Warn",
        "status.critical": "Critical",
        "status.error": "Error",
        "status.info": "Info",
        "common.field": "Field",
        "common.value": "Value",
        "common.yes": "Yes",
        "common.no": "No",
        "common.na": "n/a",
        "common.cancel": "Cancel",
        "common.review_required": "Review required",
        "common.model_estimate": "Model estimate",
        "common.note": "Note",
        "common.model_scope": "Model scope",
        "common.type": "Type",
        "common.site_zone": "Site / zone",
        "common.role": "Role",
        "common.tier": "Tier",
        "common.attached_links": "Attached links",
        "common.link_utilization": "Link utilization",
        "common.capacity": "Capacity",
        "common.routing_cost": "Routing cost",
        "common.style": "Style",
        "common.utilization": "Utilization",
        "common.directed": "Directed",
        "common.undirected": "Undirected",
        "common.device": "Device",
        "common.link": "Link",
        "common.open_simulation": "Open Simulation Lab",
        "common.no_data": "No data",
        # Loading states for bounded synchronous actions
        "loading.parse": "Parsing supplied CSV...",
        "loading.forecast": "Building forecasts...",
        "loading.capacity": "Evaluating projected demand...",
        "loading.connection": "Testing connection...",
        "loading.scenario": "Running scenario...",
        "loading.provider": "Interpreting requirements...",
        "loading.workflow": "Running the deterministic workflow...",
        "loading.sweep": "Running failure sweep...",
        "loading.mode_compare": "Comparing routing modes...",
        "loading.sensitivity": "Running sensitivity analysis...",
        "chart.congestion": "Congestion level",
        # Progress strip
        "progress.title": "Project progress",
        "progress.step.design": "Design",
        "progress.step.addressing": "Addressing",
        "progress.step.validate": "Validate",
        "progress.step.simulate": "Simulate",
        "progress.step.optimize": "Optimize",
        "progress.step.report": "Report",
        "progress.detail.design": "{devices} devices, {links} links in this session.",
        "progress.detail.design_empty": "No design twin with devices is loaded.",
        "progress.detail.addressing": (
            "{subnet_count} subnet(s), {vlan_count} VLAN plan(s) saved in the twin."
        ),
        "progress.detail.addressing_vlsm": (
            "{count} VLSM block(s) computed but not saved in the twin."
        ),
        "progress.detail.addressing_empty": "No addressing plan in the current twin.",
        "progress.detail.validate_done": "Subnet check retained with {count} finding(s).",
        "progress.detail.validate_stale": (
            "Subnet check was run on a different twin revision."
        ),
        "progress.detail.validate_flows": "{count} modeled flow check(s) retained.",
        "progress.detail.validate_empty": "No validation result retained in this session.",
        "progress.detail.simulate_empty": "No scenario run retained in this session.",
        "progress.detail.simulate_done": "Latest run: {name}.",
        "progress.detail.simulate_stale": (
            "Latest scenario run used a different twin revision."
        ),
        "progress.detail.optimize_empty": "No optimization run retained in this session.",
        "progress.detail.optimize_done": "{algorithm} run retained.",
        "progress.detail.optimize_stale": (
            "Latest optimization run used a different twin revision."
        ),
        "progress.detail.report_done": "Report prepared for the current twin.",
        "progress.detail.report_stale": (
            "Report was prepared for a different twin revision."
        ),
        "progress.detail.report_empty": "No report prepared in this session.",
        # Dashboard and samples
        "dashboard.quick_start": "Quick start",
        "dashboard.quick_start.description": (
            "Load a labeled sample to explore the workflow. Each sample is "
            "built with the same deterministic engines as a working design."
        ),
        "dashboard.sample.select": "Select sample",
        "dashboard.sample.select_help": (
            "Select only; the current twin is not changed yet."
        ),
        "dashboard.sample.replace": "replace the current twin '{name}'",
        "dashboard.sample.new": "load a new twin",
        "dashboard.sample.confirm_body": (
            "{name} will {target} in this browser session. No file is "
            "written and no existing run history is deleted."
        ),
        "dashboard.sample.confirm_title": "Confirm sample load",
        "dashboard.sample.confirm": "Confirm and load sample",
        "sample.small_office.name": "SAMPLE - Small office",
        "sample.small_office.description": (
            "One core switch with four access hosts and a single user VLAN."
        ),
        "sample.campus.name": "SAMPLE - Campus",
        "sample.campus.description": (
            "Redundant two-tier campus with core, distribution, and access switches."
        ),
        "sample.spine_leaf_dc.name": "SAMPLE - Spine-leaf DC",
        "sample.spine_leaf_dc.description": (
            "Two spines and four leaves in a full-mesh fabric with two server VLANs."
        ),
        "sample.summary": "{devices} devices | {links} links | {demands} demands",
        "dashboard.empty.message": (
            "No digital twin is loaded. Create one in the AI Network Designer "
            "or generate or import a topology in the Topology Editor."
        ),
        "dashboard.empty.title": "Digital twin required",
        "dashboard.empty.hint": (
            "The dashboard reports only data already stored in session "
            "state. It does not create a design or run an engine."
        ),
        "dashboard.metric.devices": "Devices",
        "dashboard.metric.links": "Links",
        "dashboard.metric.demands": "Demands",
        "dashboard.metric.snapshots": "Snapshots",
        "dashboard.metric.scenario_runs": "Scenario runs",
        "dashboard.metric.optimization_runs": "Optimization runs",
        "dashboard.twin_caption": (
            "Twin: {name} | Schema version: {schema} | Created: {created} | "
            "Subnets: {subnets} | VLAN plans: {vlans} | DHCP scopes: {dhcp}"
        ),
        "dashboard.design_health": "Design health",
        "dashboard.retained_runs": "Retained runs",
        "dashboard.runs_empty": (
            "No scenario or optimization runs are retained in this session. "
            "Run one from the Simulation Lab or Optimization Center."
        ),
        "dashboard.recovery": "recovery available",
        "dashboard.not_recovered": "not all baseline demands recovered",
        "dashboard.latest_scenario": "Latest scenario served demand",
        "dashboard.scenario_help": "Scenario: {name}. Status: {status}.",
        "dashboard.scenario_caption": (
            "{name} | {type} | {status} | {count} newly unserved demand(s)"
        ),
        "dashboard.no_scenarios": "No scenario runs retained.",
        "dashboard.latest_optimization": "Latest optimization evaluations",
        "dashboard.optimization_help": "{algorithm}; stopped with {reason}.",
        "dashboard.optimization_caption": (
            "{algorithm} | {reason} | {count} Pareto candidate(s) | {best}"
        ),
        "dashboard.feasible_best": "feasible best",
        "dashboard.no_feasible_best": "no feasible best",
        "dashboard.no_optimizations": "No optimization runs retained.",
        # Simulation lab - routing modes, shared risks, and bounded sweeps
        "simulation.routing_mode": "Routing mode",
        "simulation.routing_mode.help": (
            "Models the rule used to place demands on the twin: legacy single "
            "path by default, ECMP, or capacity-aware placement. This is a "
            "modeled rule, not device configuration."
        ),
        "simulation.routing_mode.single_path": "Single path (legacy)",
        "simulation.routing_mode.ecmp": "ECMP",
        "simulation.routing_mode.capacity_aware": "Capacity-aware",
        "simulation.shared_risk.title": "Shared-risk groups",
        "simulation.shared_risk.caption": (
            "Modeled failure domains: devices or links that fail together. "
            "Groups apply to this analysis only and do not change device "
            "configuration."
        ),
        "simulation.shared_risk.id": "ID",
        "simulation.shared_risk.name": "Name",
        "simulation.shared_risk.devices": "Devices",
        "simulation.shared_risk.links": "Links",
        "simulation.shared_risk.add": "Add group",
        "simulation.shared_risk.apply": "Apply groups",
        "simulation.shared_risk.clear": "Clear groups",
        "simulation.mode_compare.title": "Routing mode comparison",
        "simulation.mode_compare.caption": (
            "Compare the same failures under each modeled demand-placement "
            "rule. Results are modeled from the current twin."
        ),
        "simulation.mode_compare.run": "Compare modes",
        "simulation.mode_compare.download": "Download comparison",
        "simulation.sweep.title": "Failure sweep",
        "simulation.sweep.caption": (
            "Evaluate failure combinations up to the selected depth against "
            "the current twin."
        ),
        "simulation.sweep.depth": "Failure depth",
        "simulation.sweep.depth.n1": "N-1",
        "simulation.sweep.depth.n2": "N-2",
        "simulation.sweep.subset_links": "Link subset",
        "simulation.sweep.subset_devices": "Device subset",
        "simulation.sweep.max_pairs": "Max failure pairs",
        "simulation.sweep.slice": "Result slice",
        "simulation.sweep.run": "Run sweep",
        "simulation.sweep.cancel": "Cancel sweep",
        "simulation.sweep.progress": "Sweep progress",
        "simulation.sweep.showing": "Showing results",
        "simulation.sweep.download_json": "Download JSON",
        "simulation.sweep.download_csv": "Download CSV",
        "simulation.sweep.stop_reason": "Stop reason",
        "simulation.sweep.no_result": "No sweep result retained for this twin.",
        "simulation.sweep.srgs": "Shared-risk groups (SRGs)",
        # Optimization center - seeded SA, sensitivity, and re-ranking
        "optimization.algorithm.simulated_annealing": "Simulated annealing (seeded)",
        "optimization.sa.hybrid_start": "Hybrid start",
        "optimization.sa.hybrid_start.help": (
            "Seed simulated annealing from a retained greedy result before "
            "bounded local search. The outcome stays deterministic for the "
            "same seed and twin."
        ),
        "optimization.sensitivity.title": "Sensitivity analysis",
        "optimization.sensitivity.caption": (
            "Re-evaluate the selected design under bounded parameter changes "
            "to show which assumptions drive the result."
        ),
        "optimization.sensitivity.run": "Run sensitivity",
        "optimization.sensitivity.download": "Download sensitivity",
        "optimization.sensitivity.robust": "Robust",
        "optimization.sensitivity.no_robust": "Not robust",
        "optimization.sensitivity.complete": "Analysis complete",
        "optimization.sensitivity.incomplete": "Analysis incomplete",
        "optimization.rerank.title": "Pareto re-ranking",
        "optimization.rerank.caption": (
            "Reorder the retained Pareto front with explicit weights. This "
            "changes presentation only, not the computed candidates."
        ),
        "optimization.rerank.apply": "Apply weights",
        "optimization.rerank.download": "Download re-ranked front",
        "optimization.rerank.no_front": "No Pareto front retained in this session.",
        "optimization.rerank.weights_note": (
            "Weights affect ranking only; they do not recompute engineering scores."
        ),
        # Report source selectors
        "reports.failure_sweep_source": "Failure sweep result",
        "reports.mode_compare_source": "Mode comparison result",
        "reports.sensitivity_source": "Sensitivity result",
        "reports.rerank_source": "Re-ranked Pareto front",
        # Settings
        "settings.language.label": "Language",
        "settings.language.help": (
            "Arabic changes this session's interface only. Engineering terms, "
            "identifiers, and exported files stay Latin."
        ),
        "settings.provider": "AI provider (optional)",
        "settings.key_configured": "API key configured",
        "settings.key_source": "Key source",
        "settings.model": "Model",
        "settings.key_source_session": "session (this browser tab only)",
        "settings.key_source_environment": "environment or Streamlit secrets",
        "settings.key_source_none": "not configured",
        "settings.key_privacy": (
            "The key itself is never displayed, logged, traced, or stored on disk. "
            "A session key is held only in this browser tab and disappears when the "
            "session ends."
        ),
        "settings.key_entry": "Session API key (optional)",
        "settings.key_entry_help": (
            "Used only for this browser session. Prefer environment variables or "
            "Streamlit secrets for deployments."
        ),
        "settings.key_save": "Use key for this session",
        "settings.key_clear": "Clear session key",
        "settings.budget": "Session request budget",
        "settings.requests_used": "Requests used",
        "settings.tokens_used": "Tokens used",
        "settings.requests_remaining": "Requests remaining",
        "settings.tokens_remaining": "Tokens remaining",
        "settings.request_budget_used": "Request budget used",
        "settings.token_budget_used": "Token budget used",
        "settings.budget_reset": "Reset session budget",
        "settings.cache_title": "Copilot response cache",
        "settings.cache_caption": (
            "Bounded in-session cache keyed by model, prompt version, schema, and "
            "a hash of the typed input. A cache hit never calls the provider and "
            "never spends session budget."
        ),
        "settings.cache_hits": "Cache hits",
        "settings.cache_misses": "Cache misses",
        "settings.cache_entries": "Cached entries",
        "settings.cache_reset": "Clear response cache",
        "settings.trace_title": "Prompt trace",
        "settings.trace_caption": (
            "Prompt ids, versions, schemas, models, and cache outcomes only. No "
            "API key, user sentence, or raw model response is recorded."
        ),
        "settings.trace_empty": "No copilot language request has been made yet.",
        "settings.connection": "Connection test",
        "settings.connection_caption": (
            "Bounded test: one request, a {seconds}-second timeout, no rate-limit retries, and "
            "no structured-output repairs. The request counts against the session "
            "budget above."
        ),
        "settings.connection_add_key": (
            "Add a key for this session or configure one to enable the test."
        ),
        "settings.connection_button": "Test connection",
        "settings.connection_success": (
            "Connected. Provider reported model {model}; {tokens} token(s) used."
        ),
        "settings.needs_key": "What needs an API key",
        "settings.needs_key_list": (
            "- Natural-language requirement interpretation and clarification.\n"
            "- Plain-language explanations of plans and recommendations.\n"
            "- Generated report prose and agent narrative.\n"
        ),
        "settings.never_required": (
            "**Never required:** topology design, IP/VLAN planning, routing, "
            "analysis, the digital twin, simulation, optimization, and the "
            "deterministic structured plan below. Those are pure engineering "
            "engines and do not import the provider layer."
        ),
        "settings.limits": "Read-only limits",
        "settings.limits_caption": (
            "These bounds are compiled into the application. Change them in "
            "`config/limits.py`; this page never overrides them."
        ),
        "settings.limit.llm_calls": "LLM calls per session",
        "settings.limit.llm_tokens": "LLM tokens per session",
        "settings.limit.llm_repairs": "LLM repair attempts",
        "settings.limit.llm_retries": "LLM rate-limit retries",
        "settings.limit.llm_timeout": "LLM request timeout (s)",
        "settings.limit.llm_backoff": "LLM backoff cap (s)",
        "settings.limit.llm_response_tokens": "LLM response tokens",
        "settings.limit.agent_attempts": "Agent attempts per task",
        "settings.limit.workflow_steps": "Workflow steps",
        "settings.limit.workflow_runtime": "Workflow runtime (s)",
        "settings.limit.workflow_replans": "Workflow re-plans",
        "settings.deployment": "Deployment configuration",
        "settings.deployment_body": (
            "Secrets and environment variables are read once by "
            "`config.settings.get_settings()`. Precedence is Streamlit secrets, then "
            "environment variables, then the documented defaults."
        ),
        "settings.deployment_caption": (
            "Equivalent environment variables: GROQ_API_KEY, GROQ_MODEL, "
            "GROQ_BASE_URL. The documented model name is a default only; Groq "
            "retires models, so set GROQ_MODEL explicitly for a deployment."
        ),
        "settings.deployment_warning": (
            "Keys pasted into this page live only in Streamlit session state for "
            "this browser tab. They are not written to snapshots, traces, logs, "
            "downloads, or the repository."
        ),
        "settings.limitations": "Release limitations",
        "settings.limitations_warning": (
            "NetArchitect AI is a design-time engineering workspace. It does not "
            "connect to devices, scan or probe networks, run pentests, or apply "
            "configuration. Templates are inert design intent."
        ),
        "settings.limitations_body": (
            "- **Modeled, not measured:** simulation, forecasting, capacity, and "
            "security results come from the current twin and stated assumptions. "
            "They are not measurements or guarantees.\n"
            "- **Session-only state:** twins, runs, traces, and session keys live "
            "in this browser session only. Download what you need before closing "
            "it.\n"
            "- **Optional AI:** the deterministic engines work with no API key. "
            "The optional provider may interpret requirements or write explanatory "
            "text, but it cannot change computed values or call unlisted tools.\n"
            "- **Free-tier bounds:** the compiled caps are shown in the read-only "
            "limits table above and documented in `docs/RUNTIME_LIMITS.md`.\n"
            "- **Verification scope:** release checks are headless and in-process. "
            "Real-browser rendering, a deployed free-tier instance, live provider "
            "responses, and PDF visual layout are not verified here."
        ),
        # Layered topology view
        "topology.diagram": "Diagram",
        "topology.diagram.description": (
            "Deterministic left-to-right tiers. Marker shape shows device type; "
            "color shows the selected dimension. Click a device or link midpoint "
            "to inspect it."
        ),
        "topology.empty": "The topology has no devices to display.",
        "topology.color_by": "Color by",
        "topology.color.role": "Role",
        "topology.color.zone": "Zone",
        "topology.color.utilization": "Utilization",
        "topology.role.core": "Core",
        "topology.role.distribution": "Distribution",
        "topology.role.aggregation": "Aggregation",
        "topology.role.access": "Access",
        "topology.role.border": "Border",
        "topology.role.edge": "Edge",
        "topology.role.wan": "WAN",
        "topology.role.dmz": "DMZ",
        "topology.zone": "Zone {number}",
        "topology.inspector": "Inspector",
        "topology.clear_selection": "Clear selection",
        "topology.none_option": "(none)",
        "topology.inspect_entity": "Inspect entity",
        "topology.inspect_help": (
            "Keyboard-accessible alternative to clicking the diagram."
        ),
        "topology.inspect_empty": (
            "Click a device or a link midpoint to inspect it. The picker "
            "above provides the same selection without a pointer."
        ),
        "topology.queue_node_failure": "Queue node failure",
        "topology.queue_link_failure": "Queue link failure",
        "topology.legend.type": "Type",
        "topology.legend.link": "Link",
        "topology.legend.undirected": "Undirected link",
        "topology.legend.directed": "Directed link",
        "topology.hover.endpoints": "Endpoints",
        "topology.hover.site": "Site",
        "topology.hover.color": "Color",
        "topology.hover.max_utilization": "Max link utilization",
        "topology.utilization.none": "No data",
        "topology.utilization.low": "Low (<70%)",
        "topology.utilization.medium": "Medium (70-89%)",
        "topology.utilization.high": "High (90-100%)",
        "topology.utilization.overload": "Overload (>100%)",
        "topology.alt": (
            "Layered topology diagram with {devices} devices and {links} links"
        ),
    }
)

AR: MappingProxyType[str, str] = MappingProxyType(
    {
        # Entry point and navigation
        "app.about": (
            "نتكاركيت أيه الإصدار 1.0.0-rc1 - هندسة شبكات حتمية للتصميم. "
            "النتائج مشتقة من التوأم الحالي والافتراضات المذكورة. لا يوجد اتصال "
            "بالأجهزة أو فحص مباشر أو نتائج مضمونة. راجع الإعدادات > قيود الإصدار."
        ),
        "app.sidebar": "نتكاركيت أيه - هندسة الشبكات أولاً.",
        "nav.group.design": "التصميم",
        "nav.group.analyze": "التحليل",
        "nav.group.operate": "التشغيل",
        "nav.group.output": "المخرجات",
        "nav.label.dashboard": "لوحة التحكم",
        "nav.label.ai_network_designer": "مصمم الشبكة",
        "nav.label.topology_editor": "الطوبولوجيا",
        "nav.label.ip_addressing_subnetting": "عناوين IP",
        "nav.label.vlan_dhcp_planner": "VLAN/DHCP",
        "nav.label.routing_analysis": "التوجيه",
        "nav.label.network_analytics": "التحليلات",
        "nav.label.security_analysis": "الأمان",
        "nav.label.digital_twin": "التوأم الرقمي",
        "nav.label.simulation_lab": "المحاكاة",
        "nav.label.optimization_center": "التحسين",
        "nav.label.capacity_planning": "السعة",
        "nav.label.reports_documentation": "التقارير",
        "nav.label.agent_control_center": "مركز الوكلاء",
        "nav.label.settings": "الإعدادات",
        "nav.help.dashboard": "نظرة على الجلسة: صحة التصميم والتشغيلات المحفوظة والنماذج.",
        "nav.help.ai_network_designer": "تحويل المتطلبات المنظمة إلى خطة تصميم حتمية.",
        "nav.help.topology_editor": "إنشاء الطوبولوجيا الحالية وتعديلها وفحصها.",
        "nav.help.ip_addressing_subnetting": "تخطيط CIDR ومجموعات VLSM من التصميم الحالي.",
        "nav.help.vlan_dhcp_planner": "تخصيص VLAN ونطاقات DHCP من متطلبات الأقسام.",
        "nav.help.routing_analysis": "فحص الوصول وأقصر المسارات ومسارات الأعطال.",
        "nav.help.network_analytics": "حساب مقاييس الرسم وتحديد المخاطر الهيكلية.",
        "nav.help.security_analysis": "نمذجة المناطق والسياسات وفحوص التدفق وقت التصميم.",
        "nav.help.digital_twin": "فحص النموذج الموحد للجلسة وأخذ لقطة منه.",
        "nav.help.simulation_lab": "تقييم الأعطال وتغيرات الطلب بصورة حتمية.",
        "nav.help.optimization_center": "البحث عن مقايضات محدودة بين التكلفة والمرونة والسعة.",
        "nav.help.capacity_planning": "توقع الاستخدام والسعة من سلاسل زمنية محدودة.",
        "nav.help.reports_documentation": "إنشاء تقارير موسومة بالمصدر وتنزيلات في الذاكرة.",
        "nav.help.agent_control_center": "مراجعة أثر الوكلاء الحتمي ونتائج المهام.",
        "nav.help.settings": "ضبط الوصول الاختياري للذكاء الاصطناعي ومراجعة حدود الجلسة.",
        # Page titles and primary descriptions
        "page.dashboard": "لوحة التحكم",
        "page.dashboard.description": (
            "الحالة الحالية للتوأم الرقمي والتشغيلات الهندسية المحفوظة في هذه الجلسة."
        ),
        "page.settings": "الإعدادات",
        "page.settings.description": (
            "ضبط الذكاء الاصطناعي الاختياري وحدود الأمان للقراءة فقط ومشغل تصميم "
            "منظم حتمي لا يحتاج إلى مفتاح API."
        ),
        # Shared components and statuses
        "status.done": "مكتمل",
        "status.incomplete": "غير مكتمل",
        "status.stale": "قديم",
        "status.ok": "سليم",
        "status.complete": "مكتمل",
        "status.warning": "تحذير",
        "status.warn": "تحذير",
        "status.critical": "حرج",
        "status.error": "خطأ",
        "status.info": "معلومة",
        "common.field": "الحقل",
        "common.value": "القيمة",
        "common.yes": "نعم",
        "common.no": "لا",
        "common.na": "غير متاح",
        "common.cancel": "إلغاء",
        "common.review_required": "مطلوب مراجعة",
        "common.model_estimate": "تقدير النموذج",
        "common.note": "ملاحظة",
        "common.model_scope": "نطاق النموذج",
        "common.type": "النوع",
        "common.site_zone": "الموقع / المنطقة",
        "common.role": "الدور",
        "common.tier": "المستوى",
        "common.attached_links": "الروابط المرتبطة",
        "common.link_utilization": "استخدام الرابط",
        "common.capacity": "السعة",
        "common.routing_cost": "تكلفة التوجيه",
        "common.style": "النمط",
        "common.utilization": "الاستخدام",
        "common.directed": "موجه",
        "common.undirected": "غير موجه",
        "common.device": "جهاز",
        "common.link": "رابط",
        "common.open_simulation": "فتح مختبر المحاكاة",
        "common.no_data": "لا توجد بيانات",
        # Loading states for bounded synchronous actions
        "loading.parse": "جارٍ تحليل ملف CSV...",
        "loading.forecast": "جارٍ بناء التوقعات...",
        "loading.capacity": "جارٍ تقييم الطلب المتوقع...",
        "loading.connection": "جارٍ اختبار الاتصال...",
        "loading.scenario": "جارٍ تشغيل السيناريو...",
        "loading.provider": "جارٍ تفسير المتطلبات...",
        "loading.workflow": "جارٍ تشغيل سير العمل الحتمي...",
        "loading.sweep": "جارٍ تشغيل فحص الأعطال...",
        "loading.mode_compare": "جارٍ مقارنة أوضاع التوجيه...",
        "loading.sensitivity": "جارٍ تشغيل تحليل الحساسية...",
        "chart.congestion": "مستوى الازدحام",
        # Progress strip
        "progress.title": "تقدم المشروع",
        "progress.step.design": "التصميم",
        "progress.step.addressing": "العناوين",
        "progress.step.validate": "التحقق",
        "progress.step.simulate": "المحاكاة",
        "progress.step.optimize": "التحسين",
        "progress.step.report": "التقرير",
        "progress.detail.design": "{devices} جهازاً، {links} رابطاً في هذه الجلسة.",
        "progress.detail.design_empty": "لا يوجد توأم تصميم يحتوي على أجهزة.",
        "progress.detail.addressing": (
            "{subnet_count} شبكة فرعية، {vlan_count} خطة VLAN محفوظة في التوأم."
        ),
        "progress.detail.addressing_vlsm": (
            "{count} كتلة VLSM محسوبة لكنها غير محفوظة في التوأم."
        ),
        "progress.detail.addressing_empty": "لا توجد خطة عناوين في التوأم الحالي.",
        "progress.detail.validate_done": "فحص الشبكات الفرعية محفوظ بـ {count} ملاحظة.",
        "progress.detail.validate_stale": "تم فحص الشبكات الفرعية على نسخة مختلفة من التوأم.",
        "progress.detail.validate_flows": "{count} فحص تدفق مشمول محفوظ.",
        "progress.detail.validate_empty": "لا توجد نتيجة تحقق محفوظة في هذه الجلسة.",
        "progress.detail.simulate_empty": "لا يوجد تشغيل سيناريو محفوظ في هذه الجلسة.",
        "progress.detail.simulate_done": "آخر تشغيل: {name}.",
        "progress.detail.simulate_stale": "استخدم آخر تشغيل سيناريو نسخة مختلفة من التوأم.",
        "progress.detail.optimize_empty": "لا يوجد تشغيل تحسين محفوظ في هذه الجلسة.",
        "progress.detail.optimize_done": "تشغيل {algorithm} محفوظ.",
        "progress.detail.optimize_stale": "استخدم آخر تشغيل تحسين نسخة مختلفة من التوأم.",
        "progress.detail.report_done": "تم إعداد تقرير للتوأم الحالي.",
        "progress.detail.report_stale": "تم إعداد التقرير لنسخة مختلفة من التوأم.",
        "progress.detail.report_empty": "لم يتم إعداد تقرير في هذه الجلسة.",
        # Dashboard and samples
        "dashboard.quick_start": "البدء السريع",
        "dashboard.quick_start.description": (
            "حمّل نموذجاً موسوماً لاستكشاف سير العمل. كل نموذج مبني بمحركات "
            "التصميم الحتمية نفسها."
        ),
        "dashboard.sample.select": "اختيار نموذج",
        "dashboard.sample.select_help": "اختيار فقط؛ التوأم الحالي لم يتغير بعد.",
        "dashboard.sample.replace": "استبدال التوأم الحالي '{name}'",
        "dashboard.sample.new": "تحميل توأم جديد",
        "dashboard.sample.confirm_body": (
            "سيؤدي {name} إلى {target} في هذه الجلسة. لا تتم كتابة أي ملف "
            "ولا حذف أي سجل تشغيل."
        ),
        "dashboard.sample.confirm_title": "تأكيد تحميل النموذج",
        "dashboard.sample.confirm": "تأكيد وتحميل النموذج",
        "sample.small_office.name": "نموذج - مكتب صغير",
        "sample.small_office.description": "مبدل أساسي مع أربعة مضيفين وشبكة VLAN واحدة.",
        "sample.campus.name": "نموذج - حرم جامعي",
        "sample.campus.description": (
            "حرم احتياطي من مستويين مع مبدلات أساسية وتوزيع ووصول."
        ),
        "sample.spine_leaf_dc.name": "نموذج - مركز بيانات",
        "sample.spine_leaf_dc.description": (
            "مبدلا عمود فقري وأربعة مبدلات أوراق في نسيج كامل الوصل مع شبكتي VLAN."
        ),
        "sample.summary": "{devices} جهازاً | {links} رابطاً | {demands} طلب",
        "dashboard.empty.message": (
            "لا يوجد توأم رقمي محمل. أنشئه في مصمم الشبكة أو أنشئ طوبولوجيا "
            "أو استوردها في محرر الطوبولوجيا."
        ),
        "dashboard.empty.title": "التوأم الرقمي مطلوب",
        "dashboard.empty.hint": (
            "تعرض اللوحة البيانات المخزنة في الجلسة فقط. لا تنشئ تصميماً "
            "ولا تشغّل محركاً."
        ),
        "dashboard.metric.devices": "الأجهزة",
        "dashboard.metric.links": "الروابط",
        "dashboard.metric.demands": "الطلبات",
        "dashboard.metric.snapshots": "اللقطات",
        "dashboard.metric.scenario_runs": "تشغيلات السيناريو",
        "dashboard.metric.optimization_runs": "تشغيلات التحسين",
        "dashboard.twin_caption": (
            "التوأم: {name} | إصدار المخطط: {schema} | التاريخ: {created} | "
            "الشبكات الفرعية: {subnets} | خطط VLAN: {vlans} | نطاقات DHCP: {dhcp}"
        ),
        "dashboard.design_health": "صحة التصميم",
        "dashboard.retained_runs": "التشغيلات المحفوظة",
        "dashboard.runs_empty": (
            "لا توجد تشغيلات سيناريو أو تحسين محفوظة في هذه الجلسة. "
            "شغّل واحدة من مختبر المحاكاة أو مركز التحسين."
        ),
        "dashboard.recovery": "التعافي متاح",
        "dashboard.not_recovered": "لم يتم استرداد كل الطلبات الأساسية",
        "dashboard.latest_scenario": "الطلب المخدوم في آخر سيناريو",
        "dashboard.scenario_help": "السيناريو: {name}. الحالة: {status}.",
        "dashboard.scenario_caption": (
            "{name} | {type} | {status} | {count} طلب غير مخدوم حديثاً"
        ),
        "dashboard.no_scenarios": "لا توجد تشغيلات سيناريو محفوظة.",
        "dashboard.latest_optimization": "تقييمات آخر تحسين",
        "dashboard.optimization_help": "{algorithm}؛ توقف بسبب {reason}.",
        "dashboard.optimization_caption": (
            "{algorithm} | {reason} | {count} مرشح Pareto | {best}"
        ),
        "dashboard.feasible_best": "أفضل حل ممكن",
        "dashboard.no_feasible_best": "لا يوجد أفضل حل ممكن",
        "dashboard.no_optimizations": "لا توجد تشغيلات تحسين محفوظة.",
        # Simulation lab - routing modes, shared risks, and bounded sweeps
        "simulation.routing_mode": "وضع التوجيه",
        "simulation.routing_mode.help": (
            "نمذجة قاعدة وضع الطلبات على التوأم: المسار المفرد الافتراضي "
            "القديم، أو ECMP، أو التوزيع حسب السعة. القاعدة نموذجية ولا "
            "تغيّر إعدادات الأجهزة."
        ),
        "simulation.routing_mode.single_path": "المسار المفرد (القديم)",
        "simulation.routing_mode.ecmp": "ECMP",
        "simulation.routing_mode.capacity_aware": "حسب السعة",
        "simulation.shared_risk.title": "مجموعات المخاطر المشتركة",
        "simulation.shared_risk.caption": (
            "نطاقات أعطال نموذجية: أجهزة أو روابط تفشل معاً. تُطبق المجموعات "
            "على هذا التحليل فقط ولا تغيّر إعدادات الأجهزة."
        ),
        "simulation.shared_risk.id": "المعرّف",
        "simulation.shared_risk.name": "الاسم",
        "simulation.shared_risk.devices": "الأجهزة",
        "simulation.shared_risk.links": "الروابط",
        "simulation.shared_risk.add": "إضافة مجموعة",
        "simulation.shared_risk.apply": "تطبيق المجموعات",
        "simulation.shared_risk.clear": "مسح المجموعات",
        "simulation.mode_compare.title": "مقارنة أوضاع التوجيه",
        "simulation.mode_compare.caption": (
            "مقارنة الأعطال نفسها تحت كل قاعدة لوضع الطلبات. النتائج نموذجية "
            "ومشتقة من التوأم الحالي."
        ),
        "simulation.mode_compare.run": "مقارنة الأوضاع",
        "simulation.mode_compare.download": "تنزيل المقارنة",
        "simulation.sweep.title": "فحص الأعطال",
        "simulation.sweep.caption": (
            "تقييم تركيبات الأعطال حتى العمق المختار مقابل التوأم الحالي."
        ),
        "simulation.sweep.depth": "عمق الفشل",
        "simulation.sweep.depth.n1": "N-1",
        "simulation.sweep.depth.n2": "N-2",
        "simulation.sweep.subset_links": "مجموعة الروابط",
        "simulation.sweep.subset_devices": "مجموعة الأجهزة",
        "simulation.sweep.max_pairs": "أقصى عدد للأزواج",
        "simulation.sweep.slice": "شريحة النتائج",
        "simulation.sweep.run": "تشغيل الفحص",
        "simulation.sweep.cancel": "إلغاء الفحص",
        "simulation.sweep.progress": "تقدم الفحص",
        "simulation.sweep.showing": "النتائج المعروضة",
        "simulation.sweep.download_json": "تنزيل JSON",
        "simulation.sweep.download_csv": "تنزيل CSV",
        "simulation.sweep.stop_reason": "سبب التوقف",
        "simulation.sweep.no_result": "لا توجد نتيجة فحص محفوظة لهذا التوأم.",
        "simulation.sweep.srgs": "مجموعات المخاطر المشتركة (SRGs)",
        # Optimization center - seeded SA, sensitivity, and re-ranking
        "optimization.algorithm.simulated_annealing": "التبريد المحاكى (بذرة ثابتة)",
        "optimization.sa.hybrid_start": "بداية مختلطة",
        "optimization.sa.hybrid_start.help": (
            "تغذية التبريد المحاكى بنتيجة جشية محفوظة قبل بحث محلي محدود. "
            "النتيجة حتمية عند ثبات البذرة والتوأم."
        ),
        "optimization.sensitivity.title": "تحليل الحساسية",
        "optimization.sensitivity.caption": (
            "إعادة تقييم التصميم المختار تحت تغييرات محدودة في المعاملات "
            "لتوضيح الافتراضات المؤثرة على النتيجة."
        ),
        "optimization.sensitivity.run": "تشغيل تحليل الحساسية",
        "optimization.sensitivity.download": "تنزيل نتائج الحساسية",
        "optimization.sensitivity.robust": "متين",
        "optimization.sensitivity.no_robust": "غير متين",
        "optimization.sensitivity.complete": "اكتمل التحليل",
        "optimization.sensitivity.incomplete": "لم يكتمل التحليل",
        "optimization.rerank.title": "إعادة ترتيب Pareto",
        "optimization.rerank.caption": (
            "إعادة ترتيب جبهة Pareto المحفوظة بأوزان صريحة. هذا يغيّر العرض "
            "فقط دون تغيير المرشحين المحسوبين."
        ),
        "optimization.rerank.apply": "تطبيق الأوزان",
        "optimization.rerank.download": "تنزيل الجبهة المُعاد ترتيبها",
        "optimization.rerank.no_front": "لا توجد جبهة Pareto محفوظة في هذه الجلسة.",
        "optimization.rerank.weights_note": (
            "الأوزان تؤثر على الترتيب فقط؛ لا تُعيد حساب درجات الهندسة."
        ),
        # Report source selectors
        "reports.failure_sweep_source": "نتيجة فحص الأعطال",
        "reports.mode_compare_source": "نتيجة مقارنة الأوضاع",
        "reports.sensitivity_source": "نتيجة تحليل الحساسية",
        "reports.rerank_source": "جبهة Pareto المُعاد ترتيبها",
        # Settings
        "settings.language.label": "اللغة",
        "settings.language.help": (
            "تغيير اللغة يخص واجهة هذه الجلسة فقط. المصطلحات الهندسية "
            "والمعرفات والملفات المصدرة تبقى لاتينية."
        ),
        "settings.provider": "مزود الذكاء الاصطناعي (اختياري)",
        "settings.key_configured": "مفتاح API مضبط",
        "settings.key_source": "مصدر المفتاح",
        "settings.model": "الطراز",
        "settings.key_source_session": "الجلسة (هذا التبويب فقط)",
        "settings.key_source_environment": "متغيرات البيئة أو أسرار Streamlit",
        "settings.key_source_none": "غير مضبط",
        "settings.key_privacy": (
            "لا يتم عرض المفتاح أو تسجيله أو تتبعه أو حفظه على القرص. "
            "مفتاح الجلسة موجود في هذا التبويب فقط ويزول بانتهاء الجلسة."
        ),
        "settings.key_entry": "مفتاح الجلسة (اختياري)",
        "settings.key_entry_help": (
            "يستخدم لهذه الجلسة فقط. يفضل متغيرات البيئة أو أسرار Streamlit "
            "في النشر."
        ),
        "settings.key_save": "استخدام المفتاح لهذه الجلسة",
        "settings.key_clear": "مسح مفتاح الجلسة",
        "settings.budget": "ميزانية طلبات الجلسة",
        "settings.requests_used": "الطلبات المستخدمة",
        "settings.tokens_used": "الرموز المستخدمة",
        "settings.requests_remaining": "الطلبات المتبقية",
        "settings.tokens_remaining": "الرموز المتبقية",
        "settings.request_budget_used": "ميزانية الطلبات المستخدمة",
        "settings.token_budget_used": "ميزانية الرموز المستخدمة",
        "settings.budget_reset": "إعادة ضبط ميزانية الجلسة",
        "settings.cache_title": "ذاكرة استجابات المساعد",
        "settings.cache_caption": (
            "ذاكرة محدودة في الجلسة مفتاحها الطراز وإصدار المخطط وإصدار التوجيه "
            "وتجزئة الإدخال المضبوط. إصابة الذاكرة لا تستدعي المزود ولا تستهلك "
            "ميزانية الجلسة."
        ),
        "settings.cache_hits": "إصابات الذاكرة",
        "settings.cache_misses": "إخفاقات الذاكرة",
        "settings.cache_entries": "المدخلات المخزنة",
        "settings.cache_reset": "مسح ذاكرة الاستجابات",
        "settings.trace_title": "سجل التوجيهات",
        "settings.trace_caption": (
            "معرفات التوجيهات وإصداراتها والمخططات والطرازات ونتيجة الذاكرة فقط. "
            "لا يتم تسجيل مفتاح API أو جملة المستخدم أو الاستجابة الخام."
        ),
        "settings.trace_empty": "لم يتم تقديم أي طلب لغوي إلى المساعد بعد.",
        "settings.connection": "اختبار الاتصال",
        "settings.connection_caption": (
            "اختبار محدود: طلب واحد ومهلة {seconds} ثانية دون إعادة محاولة لتحديد "
            "المعدل ودون إصلاح المخرجات المنظمة. الطلب محسوب على ميزانية الجلسة."
        ),
        "settings.connection_add_key": "أضف مفتاحاً لهذه الجلسة أو اضبط مفتاحاً لتمكين الاختبار.",
        "settings.connection_button": "اختبار الاتصال",
        "settings.connection_success": (
            "تم الاتصال. أبلغ المزود عن الطراز {model}؛ استخدم {tokens} رمزاً."
        ),
        "settings.needs_key": "ما الذي يحتاج إلى مفتاح API",
        "settings.needs_key_list": (
            "- تفسير المتطلبات اللغوية وتوضيحها.\n"
            "- الشروحات بلغة بسيطة للخطط والتوصيات.\n"
            "- نصوص التقارير وسرد الوكلاء.\n"
        ),
        "settings.never_required": (
            "**غير مطلوب أبداً:** تصميم الطوبولوجيا وتخطيط IP/VLAN والتوجيه "
            "والتحليل والتوأم الرقمي والمحاكاة والتحسين والخطة المنظمة أدناه. "
            "هذه محركات هندسية بحتة لا تستورد طبقة المزود."
        ),
        "settings.limits": "حدود للقراءة فقط",
        "settings.limits_caption": (
            "هذه الحدود مترجمة داخل التطبيق. غيّرها في `config/limits.py`؛ "
            "لا يتجاوزها هذا الصفح."
        ),
        "settings.limit.llm_calls": "استدعاءات LLM للجلسة",
        "settings.limit.llm_tokens": "رموز LLM للجلسة",
        "settings.limit.llm_repairs": "محاولات إصلاح LLM",
        "settings.limit.llm_retries": "إعادة محاولة تحديد معدل LLM",
        "settings.limit.llm_timeout": "مهلة طلب LLM (ث)",
        "settings.limit.llm_backoff": "سقف تأخير LLM (ث)",
        "settings.limit.llm_response_tokens": "رموز استجابة LLM",
        "settings.limit.agent_attempts": "محاولات الوكيل لكل مهمة",
        "settings.limit.workflow_steps": "خطوات سير العمل",
        "settings.limit.workflow_runtime": "مدة سير العمل (ث)",
        "settings.limit.workflow_replans": "إعادة تخطيط سير العمل",
        "settings.deployment": "إعداد النشر",
        "settings.deployment_body": (
            "تُقرأ الأسرار ومتغيرات البيئة مرة واحدة عبر "
            "`config.settings.get_settings()`. الترتيب: أسرار Streamlit ثم "
            "متغيرات البيئة ثم القيم الافتراضية الموثقة."
        ),
        "settings.deployment_caption": (
            "متغيرات البيئة المكافئة: GROQ_API_KEY و GROQ_MODEL و "
            "GROQ_BASE_URL. اسم الطراز الموثق افتراضي فقط؛ قد تُوقف Groq "
            "الطرازات، لذا اضبط GROQ_MODEL صراحةً عند النشر."
        ),
        "settings.deployment_warning": (
            "المفاتيح الملصقة في هذا الصفح موجودة في حالة جلسة Streamlit "
            "لهذا التبويب فقط. لا تكتب إلى اللقطات أو الآثار أو السجلات "
            "أو التنزيلات أو المستودع."
        ),
        "settings.limitations": "قيود الإصدار",
        "settings.limitations_warning": (
            "نتكاركيت أيه بيئة هندسية للتصميم فقط. لا تتصل بالأجهزة ولا تفحص "
            "الشبكات ولا تنفذ اختبارات اختراق ولا تطبق إعدادات. القوالب مجرد "
            "نيّة تصميم غير فعّالة."
        ),
        "settings.limitations_body": (
            "- **مشمول بالنمذجة وليس بالقياس:** نتائج المحاكاة والتوقع والسعة "
            "والأمان مشتقة من التوأم الحالي والافتراضات المذكورة. ليست قياسات "
            "أو ضمانات.\n"
            "- **حالة الجلسة فقط:** التوائم والتشغيلات والآثار ومفاتيح الجلسة "
            "موجودة في جلسة هذا المتصفح فقط. نزّل ما تحتاجه قبل الإغلاق.\n"
            "- **الذكاء الاصطناعي اختياري:** المحركات الحتمية تعمل دون مفتاح API. "
            "قد يفسر المزود المتطلبات أو يكتب نصوصاً توضيحية، لكنه لا يغير "
            "القيم المحسوبة ولا يستدعي أدوات غير مدرجة.\n"
            "- **حدود الخطة المجانية:** الحدود المترجمة ظاهرة في جدول الحدود "
            "أعلاه وموثقة في `docs/RUNTIME_LIMITS.md`.\n"
            "- **نطاق التحقق:** فحوص الإصدار داخل العملية ودون متصفح. لم يتم "
            "التحقق من العرض في متصفح حقيقي أو نسخة منشورة على الخطة المجانية "
            "أو استجابات المزود المباشرة أو تخطيط PDF البصري."
        ),
        # Layered topology view
        "topology.diagram": "المخطط",
        "topology.diagram.description": (
            "مستويات حتمية من اليسار إلى اليمين. شكل العلامة يدل على نوع "
            "الجهاز واللون يدل على البعد المختار. اضغط على جهاز أو منتصف رابط "
            "لفحصه."
        ),
        "topology.empty": "لا توجد أجهزة لعرضها في الطوبولوجيا.",
        "topology.color_by": "اللون حسب",
        "topology.color.role": "الدور",
        "topology.color.zone": "المنطقة",
        "topology.color.utilization": "الاستخدام",
        "topology.role.core": "أساسي",
        "topology.role.distribution": "توزيع",
        "topology.role.aggregation": "تجميع",
        "topology.role.access": "وصول",
        "topology.role.border": "حدودي",
        "topology.role.edge": "طرفي",
        "topology.role.wan": "WAN",
        "topology.role.dmz": "DMZ",
        "topology.zone": "المنطقة {number}",
        "topology.inspector": "الفاحص",
        "topology.clear_selection": "مسح التحديد",
        "topology.none_option": "(لا شيء)",
        "topology.inspect_entity": "فحص كيان",
        "topology.inspect_help": "بديل يمكن الوصول إليه بلوحة المفاتيح بدلاً من النقر.",
        "topology.inspect_empty": (
            "اضغط على جهاز أو منتصف رابط لفحصه. القائمة أعلاه توفر التحديد "
            "نفسه دون استخدام المؤشر."
        ),
        "topology.queue_node_failure": "جدولة فشل عقدة",
        "topology.queue_link_failure": "جدولة فشل رابط",
        "topology.legend.type": "النوع",
        "topology.legend.link": "الرابط",
        "topology.legend.undirected": "رابط غير موجه",
        "topology.legend.directed": "رابط موجه",
        "topology.hover.endpoints": "الطرفان",
        "topology.hover.site": "الموقع",
        "topology.hover.color": "اللون",
        "topology.hover.max_utilization": "أقصى استخدام للرابط",
        "topology.utilization.none": "لا توجد بيانات",
        "topology.utilization.low": "منخفض (<70%)",
        "topology.utilization.medium": "متوسط (70-89%)",
        "topology.utilization.high": "مرتفع (90-100%)",
        "topology.utilization.overload": "تحميل زائد (>100%)",
        "topology.alt": "مخطط طوبولوجيا بـ {devices} جهازاً و {links} رابطاً",
    }
)

_LATIN_TOKEN = re.compile(
    r"(?<![\w])(?:[A-Za-z][A-Za-z0-9_.-]*|\d+(?:[.:/-]\d+)*(?:[A-Za-z][A-Za-z0-9_-]*)?)(?![\w])"
)


def normalize_language(value: object) -> str:
    """Map a stored or submitted language value to a supported code."""
    if not isinstance(value, str):
        return DEFAULT_LANGUAGE
    normalized = value.strip().lower()
    if normalized in LANGUAGES:
        return normalized
    if normalized in {"arabic", "العربية"}:
        return "ar"
    if normalized in {"english", "en-us", "en_gb"}:
        return "en"
    return DEFAULT_LANGUAGE


def current_language() -> str:
    """Return the language selected for this browser session."""
    value = st.session_state.get(LANGUAGE_KEY, DEFAULT_LANGUAGE)
    return normalize_language(value)


def set_language(language: str) -> None:
    """Set the session UI language without touching any other session data."""
    st.session_state[LANGUAGE_KEY] = normalize_language(language)


def is_rtl() -> bool:
    """Return whether the active interface uses right-to-left direction."""
    return current_language() == "ar"


def direction() -> str:
    """Return the CSS direction for the active language."""
    return DIRECTIONS[current_language()]


def protect_latin_tokens(text: str) -> str:
    """Isolate Latin terms and numeric literals inside Arabic text."""
    if not text or _FSI in text or _PDI in text:
        return text
    return _LATIN_TOKEN.sub(lambda match: f"{_FSI}{match.group(0)}{_PDI}", text)


def ltr(value: object) -> str:
    """Render one value left-to-right in Arabic without changing English text."""
    text = "" if value is None else str(value)
    if not text or current_language() != "ar":
        return text
    return f"{_FSI}{text}{_PDI}"


def _catalog(language: str) -> MappingProxyType[str, str] | dict[str, str]:
    return AR if language == "ar" else EN


def translate(
    key: str,
    values: MappingProxyType[str, Any] | dict[str, Any] | None = None,
    *,
    language: str | None = None,
    default: str | None = None,
) -> str:
    """Translate one catalog key with English fallback and safe formatting."""
    selected = normalize_language(language) if language is not None else current_language()
    catalog = _catalog(selected)
    template = catalog.get(key)
    if template is None:
        template = EN.get(key, key if default is None else default)
    if values:
        try:
            template = template.format(**values)
        except (KeyError, IndexError, ValueError):
            fallback = EN.get(key, template)
            if fallback != template:
                try:
                    template = fallback.format(**values)
                except (KeyError, IndexError, ValueError):
                    pass
    return protect_latin_tokens(template) if selected == "ar" else template


def t(key: str, **values: object) -> str:
    """Translate one catalog key for the active session language."""
    return translate(key, values)


def tx(text: str) -> str:
    """Translate a known English UI string by reverse lookup; isolate unknown text."""
    if not isinstance(text, str):
        return text  # type: ignore[return-value]
    if current_language() != "ar":
        return text
    for key, english in EN.items():
        if english == text:
            return t(key)
    return protect_latin_tokens(text)


def status_label(status: str) -> str:
    """Return the visible text for a semantic status code."""
    normalized = status.strip().lower()
    return t(f"status.{normalized}", default=status.replace("_", " ").capitalize())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def page_label(title: str) -> str:
    """Return the localized navigation label for a canonical page title."""
    return t(f"nav.label.{_slug(title)}", default=title)


def page_help(title: str) -> str:
    """Return the localized navigation help for a canonical page title."""
    return t(f"nav.help.{_slug(title)}", default="")


def group_label(group: str) -> str:
    """Return the localized navigation group name."""
    if not group:
        return ""
    return t(f"nav.group.{_slug(group)}", default=group)


def sample_name(key: str, default: str) -> str:
    """Return the localized display name for a sample project."""
    return t(f"sample.{_slug(key)}.name", default=default)


def sample_description(key: str, default: str) -> str:
    """Return the localized description for a sample project."""
    return t(f"sample.{_slug(key)}.description", default=default)


def render_rtl_css() -> None:
    """Inject the scoped direction stylesheet only for Arabic sessions."""
    if is_rtl():
        st.html(_RTL_CSS)


def missing_translation_keys() -> tuple[str, ...]:
    """Return catalog keys absent from Arabic; the parity test must see none."""
    return tuple(sorted(set(EN) - set(AR)))


def catalog_parity() -> bool:
    """Return whether both catalogs declare the same keys and placeholders."""
    if set(EN) != set(AR):
        return False
    pattern = re.compile(r"\{(\w+)\}")
    return all(
        set(pattern.findall(EN[key])) == set(pattern.findall(AR[key])) for key in EN
    )


__all__ = [
    "AR",
    "DEFAULT_LANGUAGE",
    "DIRECTIONS",
    "EN",
    "LANGUAGES",
    "LANGUAGE_KEY",
    "catalog_parity",
    "current_language",
    "direction",
    "group_label",
    "is_rtl",
    "ltr",
    "missing_translation_keys",
    "normalize_language",
    "page_help",
    "page_label",
    "protect_latin_tokens",
    "render_rtl_css",
    "sample_description",
    "sample_name",
    "set_language",
    "status_label",
    "t",
    "translate",
    "tx",
]
