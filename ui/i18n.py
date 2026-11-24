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
        "error.llm.authentication": (
            "The LLM provider rejected the API key (HTTP {status}). "
            "Check the configured key."
        ),
        "error.llm.forbidden": (
            "The LLM provider blocked the request (HTTP {status}). "
            "Check the configured key or provider permissions."
        ),
        "error.llm.not_found": (
            "The LLM provider could not find the requested model or endpoint "
            "(HTTP {status}). Check GROQ_MODEL and GROQ_BASE_URL."
        ),
        "nav.group.design": "Design",
        "nav.group.analyze": "Analyze",
        "nav.group.operate": "Operate",
        "nav.group.output": "Output",
        "nav.label.dashboard": "Dashboard",
        "nav.label.ai_network_designer": "AI Designer",
        "nav.label.topology_editor": "Topology",
        "nav.label.ip_addressing_subnetting": "IP",
        "nav.label.vlan_dhcp_planner": "VLAN/DHCP",
        "nav.label.l3_design": "L3 Design",
        "nav.label.l2_design": "L2 Design",
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
        "nav.help.l3_design": (
            "Model dual-stack, NAT/PAT, OSPF areas, and gateway redundancy rules."
        ),
        "nav.help.l2_design": (
            "Model switching, WAN, wireless, and QoS design rules from the current twin."
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
        "page.l3_design": "L3 Design",
        "page.l3_design.description": (
            "Deterministic dual-stack, NAT/PAT, OSPF area, and gateway redundancy "
            "models derived from the current twin."
        ),
        "page.l2_design": "L2 Design",
        "page.l2_design.description": (
            "Deterministic Layer-2, WAN, wireless, and QoS design models derived "
            "from the current twin."
        ),
        "l3.scope": (
            "Modeled design rules only; no device access or packet behavior."
        ),
        "l3.tab.ipv6": "IPv6 dual-stack",
        "l3.tab.nat": "NAT/PAT",
        "l3.tab.ospf": "OSPF areas",
        "l3.tab.ha": "Gateway redundancy",
        "l3.tab.findings": "Findings",
        # W5 modeled L2/WAN/wireless/QoS design workspace
        "l2.scope": (
            "Design models only; no live protocol, RF propagation, or queue "
            "simulation is included."
        ),
        "l2.model_notes": (
            "All counts and estimates are hand-checkable from the stated twin "
            "facts and assumptions."
        ),
        "l2.tab.l2": "L2 switching",
        "l2.tab.wan": "WAN design",
        "l2.tab.wireless": "Wireless planning",
        "l2.tab.qos": "QoS admission",
        "l2.tab.findings": "Findings",
        "l2.tab.l2.description": (
            "Modeled VLAN, trunk, loop, and parallel-link bundle rules."
        ),
        "l2.tab.wan.description": (
            "Modeled sites, inter-site links, cost proxies, and reachability."
        ),
        "l2.tab.wireless.description": (
            "Abstract AP counts from stated area and capacity assumptions."
        ),
        "l2.tab.qos.description": (
            "Modeled strict-priority admission order and per-link class caps."
        ),
        "l2.tab.findings.description": (
            "Deterministic findings from the active design models."
        ),
        "l2.l2.title": "Modeled Layer-2 switching",
        "l2.wan.title": "Modeled WAN design",
        "l2.wireless.title": "Modeled wireless planning",
        "l2.qos.title": "Modeled QoS admission",
        "l2.findings.title": "Design findings",
        "l2.l2.scope": "Modeled switching rules only; no STP or LACP protocol state.",
        "l2.wan.scope": (
            "Modeled sites and links only; no carrier circuit or live protocol."
        ),
        "l2.wireless.scope": (
            "Modeled AP estimates only; no RF propagation or site survey."
        ),
        "l2.qos.scope": (
            "Modeled admission order only; no queue simulation or scheduler state."
        ),
        "l2.editor.gateways": "Gateway by VLAN",
        "l2.editor.root_priorities": "Root priority by switch",
        "l2.editor.vlan_spread_threshold": "VLAN spread threshold",
        "l2.editor.bundles": "EtherChannel bundles",
        "l2.editor.site_types": "Site type by site",
        "l2.editor.hq_sites": "HQ target sites",
        "l2.editor.areas": "Wireless areas",
        "l2.editor.default_class": "Default traffic class",
        "l2.editor.class_caps": "Class share caps",
        "l2.l2.editor": "Edit Layer-2 design",
        "l2.wan.editor": "Edit WAN design",
        "l2.wireless.editor": "Edit wireless design",
        "l2.qos.editor": "Edit QoS design",
        "l2.button.apply_design": "Apply design to twin",
        "l2.button.clear_design": "Clear stored design",
        "l2.button.add_bundle": "Add bundle",
        "l2.button.add_area": "Add area",
        "l2.button.add_cap": "Add class cap",
        "l2.button.remove_selected": "Remove selected",
        "l2.l2.apply": "Apply L2 design",
        "l2.wan.apply": "Apply WAN design",
        "l2.wireless.apply": "Apply wireless design",
        "l2.qos.apply": "Apply QoS design",
        "l2.l2.clear": "Clear L2 design",
        "l2.wan.clear": "Clear WAN design",
        "l2.wireless.clear": "Clear wireless design",
        "l2.qos.clear": "Clear QoS design",
        "l2.notice.no_twin": "Load a digital twin before reviewing design models.",
        "l2.notice.no_design": "No design of this type is stored on the twin.",
        "l2.notice.design_saved": "Design saved to the current twin.",
        "l2.notice.design_cleared": "Design removed from the current twin.",
        "l2.notice.no_findings": "No design findings were produced.",
        "l2.notice.model_only": (
            "Modeled design values only; nothing was applied to a device."
        ),
        "l2.notice.no_live_protocol": (
            "No live protocol, adjacency, or packet behavior is simulated."
        ),
        "l2.notice.no_rf": "No RF propagation or signal-strength model is used.",
        "l2.notice.no_queue": "No queueing, drop, or scheduler behavior is simulated.",
        "l2.why.l2": "Why this L2 design?",
        "l2.why.wan": "Why this WAN design?",
        "l2.why.wireless": "Why this wireless plan?",
        "l2.why.qos": "Why this QoS admission?",
        "l2.why.findings": "Why these findings?",
        "l2.why.button": "Why this result?",
        "l2.l2.why": "Why this L2 design?",
        "l2.wan.why": "Why this WAN design?",
        "l2.wireless.why": "Why this wireless plan?",
        "l2.qos.why": "Why this QoS admission?",
        "l2.field.vlan_id": "VLAN id",
        "l2.field.gateway_device": "Gateway device",
        "l2.field.switch_id": "Switch id",
        "l2.field.priority": "Priority",
        "l2.field.link_ids": "Link ids (comma separated)",
        "l2.field.site_id": "Site id",
        "l2.field.site_type": "Site type",
        "l2.field.area_id": "Area id",
        "l2.field.area_m2": "Area (m2)",
        "l2.field.clients": "Modeled clients",
        "l2.field.client_mbps": "Mbps per client",
        "l2.field.ap_capacity_mbps": "AP capacity (Mbps)",
        "l2.field.coverage_radius_m": "Coverage radius (m)",
        "l2.field.utilization_target": "Utilization target",
        "l2.field.overlap_factor": "Overlap factor",
        "l2.field.link_id": "Link id",
        "l2.field.traffic_class": "Traffic class",
        "l2.field.share_cap": "Share cap (0-1)",
        "l2.field.default_class": "Default class",
        "l2.empty.no_bundles": "No EtherChannel bundles are modeled.",
        "l2.empty.no_areas": "No wireless areas are modeled.",
        "l2.empty.no_caps": "No modeled class share caps are stored.",
        "l2.empty.no_findings": "No findings are retained for this model.",
        "l2.review.run": "Run bounded design review",
        "l2.review.cancel": "Cancel review",
        "l2.review.clear": "Clear review result",
        "l2.review.running": "Bounded design review is running.",
        "l2.review.empty": "No bounded design review result is retained.",
        "l2.review.done": "Bounded design review complete.",
        "l2.section.layer2": "Layer-2 switching",
        "l2.section.wan": "WAN and multi-site",
        "l2.section.wireless": "Abstract wireless",
        "l2.section.qos": "QoS admission",
        "l2.section.findings": "Bounded design review",
        "ip.tab.dual_stack": "Dual-stack planner",
        "ip.tab.nat": "NAT/PAT planner",
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
        # B4 executive summary
        "reports.executive.title": "Executive summary (two pages)",
        "reports.executive.caption": (
            "A compact summary computed from the selected sources. The report "
            "language follows the interface language set on Settings."
        ),
        "reports.executive.language": "Report language: {language}.",
        "reports.executive.language_switch": "Switch language on Settings.",
        "reports.executive.not_run": "Sections not run: {count}.",
        "reports.executive.consistent": (
            "Numeric consistency: OK ({count} sourced values checked)."
        ),
        "reports.executive.inconsistent": (
            "Numeric consistency: {count} finding(s); see the full report."
        ),
        "reports.executive.pdf_ready": "PDF: {pages} page(s), {bytes} bytes.",
        "reports.executive.download_pdf": "Download executive PDF",
        "reports.executive.download_markdown": "Download executive Markdown",
        "reports.executive.empty_sources": (
            "No optional sources are selected; missing sections are marked "
            "not run with the page that produces them."
        ),
        # B2 project bundles (Save / Open)
        "bundle.title": "Project bundle",
        "bundle.save.title": "Save project bundle",
        "bundle.save.caption": (
            "Build one deterministic archive in memory from this session: the "
            "twin, snapshots, retained runs with their fingerprints, decisions, "
            "modeled flows, and non-secret settings. Nothing is written to disk."
        ),
        "bundle.save.prepare": "Prepare bundle",
        "bundle.save.ready": "Bundle ready: {bytes} bytes.",
        "bundle.save.download": "Download project bundle",
        "bundle.save.requires_twin": "Load a digital twin before preparing a bundle.",
        "bundle.open.title": "Open project bundle",
        "bundle.open.caption": (
            "Import a previously saved bundle. The archive is checked for path "
            "traversal, size, checksums, and schema before anything is shown."
        ),
        "bundle.open.upload": "Bundle file (.zip)",
        "bundle.open.preview_title": "Bundle preview",
        "bundle.open.preview": (
            "Twin: {name} | Schema: {schema} | Devices: {devices} | Links: "
            "{links} | Fingerprint: {fingerprint} | Format: v{version}"
        ),
        "bundle.open.counts": (
            "Snapshots: {snapshots} | Simulations: {simulations} | "
            "Optimizations: {optimizations} | Decisions: {decisions} | "
            "Flows: {flows}"
        ),
        "bundle.open.mode": "Import mode",
        "bundle.open.mode.replace": "Replace current twin",
        "bundle.open.mode.snapshot": "Import as new snapshot",
        "bundle.open.mode.help": (
            "Import as new snapshot keeps the current twin untouched and stores "
            "the imported twin as one additional bounded snapshot."
        ),
        "bundle.open.confirm": "Confirm import",
        "bundle.open.cancel": "Cancel import",
        "bundle.open.imported": "Bundle imported: {name}.",
        "bundle.open.invalid": "The bundle could not be imported.",
        "bundle.open.processed": (
            "This upload has already been imported or cancelled. Choose another "
            "file to stage a new import."
        ),
        "bundle.unsaved": (
            "The current design has unsaved changes. Prepare a project bundle "
            "on the Digital Twin page before replacing it."
        ),
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
        "settings.base_url": "Base URL",
        "settings.base_url_default": "default",
        "settings.base_url_custom": "custom",
        "settings.key_source_secrets": "Streamlit secrets",
        "settings.key_source_environment": "environment variable",
        "settings.key_source_none": "not configured",
        "settings.key_privacy": (
            "The key itself is never displayed, logged, traced, or stored on disk. "
            "It is read only from Streamlit secrets or environment variables."
        ),
        "settings.budget": "Session request budget",
        "settings.app_safeguard": "App safeguard",
        "settings.app_safeguard_caption": (
            "Local per-session caps only. These caps are unchanged and are not "
            "provider rate limits."
        ),
        "settings.requests_used": "Requests used",
        "settings.tokens_used": "Tokens used",
        "settings.requests_remaining": "Requests remaining",
        "settings.tokens_remaining": "Tokens remaining",
        "settings.request_budget_used": "Request budget used",
        "settings.token_budget_used": "Token budget used",
        "settings.budget_reset": "Reset session budget",
        "settings.provider_limits_title": "Provider rate limits (from last response)",
        "settings.provider_limits_caption": (
            "These are rate-limit values reported by the provider for the last "
            "request, not account billing or monthly usage."
        ),
        "settings.provider_limits_empty": (
            "No provider response has been recorded yet. Use the Connection test "
            "button above to refresh this snapshot."
        ),
        "settings.not_reported": "not reported",
        "settings.provider_remaining_requests": "Provider remaining Requests",
        "settings.provider_remaining_tokens": "Provider remaining tokens",
        "settings.provider_reset_requests": "Provider reset (Requests)",
        "settings.provider_reset_tokens": "Provider reset (tokens)",
        "settings.provider_retry_after": "Provider Retry-After",
        "settings.real_tokens_used": "Real tokens used this session",
        "settings.estimated_tokens_used": "Estimated tokens used this session",
        "settings.last_call_time": "Last call time",
        "settings.last_usage_source": "Last usage source",
        "settings.usage_reported": "provider-reported",
        "settings.usage_estimated": "estimated",
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
            "budget below."
        ),
        "settings.connection_add_key": (
            "Configure a key in Streamlit secrets or environment variables to "
            "enable the test."
        ),
        "settings.connection_button": "Test connection",
        "settings.connection_success": (
            "Connected. Provider reported model {model}; {tokens} token(s) used "
            "({usage_source})."
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
            "The API key is read only from Streamlit secrets or environment "
            "variables. It is never entered in this UI and is not written to "
            "snapshots, traces, logs, downloads, or the repository."
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
            "- **Session-only state:** twins, runs, and traces live in this browser "
            "session only. Download what you need before closing it. The API key "
            "is read only from Streamlit secrets or environment variables and is "
            "never entered in the UI.\n"
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
        # S6 design-time security tabs
        "security.page.title": "Security Analysis",
        "security.page.intro": (
            "Model trust zones, policy, and flow checks against the current "
            "digital twin. This page does not scan, probe, contact a device, or "
            "look up a vulnerability."
        ),
        "security.scope": "Model scope",
        "security.empty.message": (
            "No digital twin with a topology is loaded. Open the Topology "
            "Editor to create, generate, or import one, then return here."
        ),
        "security.empty.title": "Digital twin required",
        "security.empty.hint": (
            "Security results are modeled only from a stored twin revision."
        ),
        "security.tab.zones": "Zones",
        "security.tab.policy": "Policy",
        "security.tab.flow": "Flow check",
        "security.tab.reachability": "Reachability",
        "security.tab.segmentation": "Segmentation",
        "security.tab.optimizer": "Optimizer",
        "security.tab.zero_trust": "Zero-trust",
        "security.tab.findings": "Findings",
        "security.tab.checklist": "Checklist",
        "security.tab.templates": "Templates",
        "security.reachability.title": "Modeled policy reachability",
        "security.reachability.caption": (
            "The full zone x service grid is a design-time policy model. It is "
            "not an attack path, exploit chain, or a scan of a live network."
        ),
        "security.reachability.blast_radius": "Bounded blast radius",
        "security.reachability.why": "Why this reachability?",
        "security.segmentation.title": "Modeled segmentation score",
        "security.segmentation.caption": (
            "Every weighted input is shown so the integer score can be checked "
            "by hand. Criticality is a designer-set assumption, not a CVSS value."
        ),
        "security.segmentation.why": "Why this score?",
        "security.optimizer.title": "Inert policy optimizations",
        "security.optimizer.caption": (
            "Each proposal carries a finite decision-table proof. Selection "
            "creates a new twin; no device configuration is generated."
        ),
        "security.optimizer.select": "Optimizations to apply",
        "security.optimizer.apply": "Apply selected optimizations",
        "security.optimizer.empty": "No optimization proposals were produced.",
        "security.optimizer.applied": "Applied {count} optimization(s) to a new twin.",
        "security.zero_trust.title": "Zero-trust microsegmentation",
        "security.zero_trust.caption": (
            "Suggestions align with common practice at design level only. Allow "
            "rules come from modeled needs; denies cover lower-trust pairs with "
            "no modeled need."
        ),
        "security.zero_trust.select": "Suggestions to apply",
        "security.zero_trust.apply": "Apply selected suggestions",
        "security.zero_trust.empty": "No microsegmentation suggestions were produced.",
        "security.zero_trust.applied": "Applied {count} suggestion(s) to a new twin.",
        "security.checklist.title": "Design checklist",
        "security.checklist.caption": (
            "Design checklist aligned with common practice (design-level). No "
            "compliance or certification is claimed."
        ),
        "security.checklist.version": "Checklist version",
        "security.checklist.health": "Basic design health",
        "status.pass": "Pass",
        "status.fail": "Fail",
        "status.not-modeled": "Not modeled",
        "status.exposed": "Exposed",
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
        "error.llm.authentication": (
            "رفض مزود LLM مفتاح API (HTTP {status}). تحقق من المفتاح المضبط."
        ),
        "error.llm.forbidden": (
            "حظر مزود LLM الطلب (HTTP {status}). "
            "تحقق من المفتاح المضبط أو أذونات المزود."
        ),
        "error.llm.not_found": (
            "تعذّر على مزوّد LLM العثور على الطراز أو نقطة النهاية المطلوبة "
            "(HTTP {status}). تحقق من GROQ_MODEL و GROQ_BASE_URL."
        ),
        "nav.group.design": "التصميم",
        "nav.group.analyze": "التحليل",
        "nav.group.operate": "التشغيل",
        "nav.group.output": "المخرجات",
        "nav.label.dashboard": "لوحة التحكم",
        "nav.label.ai_network_designer": "مصمم الشبكة",
        "nav.label.topology_editor": "الطوبولوجيا",
        "nav.label.ip_addressing_subnetting": "عناوين IP",
        "nav.label.vlan_dhcp_planner": "VLAN/DHCP",
        "nav.label.l3_design": "تصميم الطبقة الثالثة",
        "nav.label.l2_design": "تصميم الطبقة الثانية (L2)",
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
        "nav.help.l3_design": "نمذجة قواعد IPv6 وNAT/PAT وOSPF وتكرار البوابة.",
        "nav.help.l2_design": (
            "نمذجة قواعد التبديل وشبكة WAN واللاسلكي وجودة الخدمة من التوأم الحالي."
        ),
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
        "page.l3_design": "تصميم الطبقة الثالثة",
        "page.l3_design.description": (
            "نماذج حتمية لـ IPv6 وNAT/PAT ومناطق OSPF وتكرار البوابة مستمدة من "
            "التوأم الرقمي الحالي."
        ),
        "page.l2_design": "تصميم الطبقة الثانية",
        "page.l2_design.description": (
            "نماذج حتمية لتبديل الطبقة الثانية وشبكة WAN واللاسلكي وجودة الخدمة "
            "مستمدة من التوأم الرقمي الحالي."
        ),
        "l3.scope": "قواعد تصميم ممذجة فقط؛ لا وصول إلى الأجهزة ولا سلوك حزم.",
        "l3.tab.ipv6": "IPv6 مزدوج",
        "l3.tab.nat": "NAT/PAT",
        "l3.tab.ospf": "مناطق OSPF",
        "l3.tab.ha": "تكرار البوابة",
        "l3.tab.findings": "النتائج",
        # W5 modeled L2/WAN/wireless/QoS design workspace
        "l2.scope": (
            "نماذج تصميم فقط؛ لا يتضمن ذلك بروتوكلاً مباشراً أو انتشاراً "
            "لاسلكياً أو محاكاة قوائم انتظار."
        ),
        "l2.model_notes": (
            "كل الأعداد والتقديرات قابلة للتحقق يدوياً من حقائق التوأم "
            "والافتراضات المذكورة."
        ),
        "l2.tab.l2": "تبديل الطبقة الثانية",
        "l2.tab.wan": "تصميم WAN",
        "l2.tab.wireless": "التخطيط اللاسلكي",
        "l2.tab.qos": "قبول جودة الخدمة",
        "l2.tab.findings": "النتائج",
        "l2.tab.l2.description": (
            "قواعد VLAN والروابط الجذعية والحلقات والمجموعات المتوازية المُنمذجة."
        ),
        "l2.tab.wan.description": (
            "مواقع وروابط بين المواقع وتكاليف تقديرية وقابلية وصول مُنمذجة."
        ),
        "l2.tab.wireless.description": (
            "عدد نقاط الوصول المُقدَّر من مساحة وافتراضات سعة مذكورة."
        ),
        "l2.tab.qos.description": (
            "ترتيب قبول صارم حسب الأولوية وحدود حصة لكل رابط."
        ),
        "l2.tab.findings.description": (
            "نتائج حتمية من نماذج التصميم النشطة."
        ),
        "l2.l2.title": "تبديل الطبقة الثانية المُنمذج",
        "l2.wan.title": "تصميم WAN المُنمذج",
        "l2.wireless.title": "التخطيط اللاسلكي المُنمذج",
        "l2.qos.title": "قبول جودة الخدمة المُنمذج",
        "l2.findings.title": "نتائج التصميم",
        "l2.l2.scope": (
            "قواعد تبديل مُنمذجة فقط؛ لا توجد حالة بروتوكول STP أو LACP."
        ),
        "l2.wan.scope": (
            "مواقع وروابط مُنمذجة فقط؛ لا توجد دائرة ناقل أو بروتوكول مباشر."
        ),
        "l2.wireless.scope": (
            "تقديرات نقاط وصول مُنمذجة فقط؛ لا انتشار لاسلكي ولا مسح موقع."
        ),
        "l2.qos.scope": (
            "ترتيب قبول مُنمذج فقط؛ لا محاكاة قوائم انتظار ولا حالة مجدول."
        ),
        "l2.editor.gateways": "البوابة حسب VLAN",
        "l2.editor.root_priorities": "أولوية الجذر حسب المبدل",
        "l2.editor.vlan_spread_threshold": "حد انتشار VLAN",
        "l2.editor.bundles": "مجموعات EtherChannel",
        "l2.editor.site_types": "نوع الموقع حسب الموقع",
        "l2.editor.hq_sites": "مواقع الهدف الرئيسية",
        "l2.editor.areas": "المناطق اللاسلكية",
        "l2.editor.default_class": "فئة الحركة الافتراضية",
        "l2.editor.class_caps": "حدود حصة الفئة",
        "l2.l2.editor": "تعديل تصميم الطبقة الثانية",
        "l2.wan.editor": "تعديل تصميم WAN",
        "l2.wireless.editor": "تعديل التخطيط اللاسلكي",
        "l2.qos.editor": "تعديل قبول جودة الخدمة",
        "l2.button.apply_design": "تطبيق التصميم على التوأم",
        "l2.button.clear_design": "مسح التصميم المخزن",
        "l2.button.add_bundle": "إضافة مجموعة",
        "l2.button.add_area": "إضافة منطقة",
        "l2.button.add_cap": "إضافة حد فئة",
        "l2.button.remove_selected": "إزالة المحدد",
        "l2.l2.apply": "تطبيق تصميم الطبقة الثانية",
        "l2.wan.apply": "تطبيق تصميم WAN",
        "l2.wireless.apply": "تطبيق التخطيط اللاسلكي",
        "l2.qos.apply": "تطبيق قبول جودة الخدمة",
        "l2.l2.clear": "مسح تصميم الطبقة الثانية",
        "l2.wan.clear": "مسح تصميم WAN",
        "l2.wireless.clear": "مسح التخطيط اللاسلكي",
        "l2.qos.clear": "مسح قبول جودة الخدمة",
        "l2.notice.no_twin": "حمّل توأماً رقمياً قبل مراجعة نماذج التصميم.",
        "l2.notice.no_design": "لا يوجد تصميم من هذا النوع مخزن على التوأم.",
        "l2.notice.design_saved": "تم حفظ التصميم في التوأم الحالي.",
        "l2.notice.design_cleared": "تمت إزالة التصميم من التوأم الحالي.",
        "l2.notice.no_findings": "لم يتم إنتاج نتائج تصميم.",
        "l2.notice.model_only": (
            "قيم تصميم مُنمذجة فقط؛ لم يُطبّق شيء على أي جهاز."
        ),
        "l2.notice.no_live_protocol": (
            "لا يتم محاكاة أي بروتوكول مباشر أو تجاور أو سلوك حزم."
        ),
        "l2.notice.no_rf": "لا يُستخدم نموذج انتشار لاسلكي أو قوة إشارة.",
        "l2.notice.no_queue": (
            "لا يتم محاكاة قوائم الانتظار أو الإسقاط أو المجدول."
        ),
        "l2.why.l2": "لماذا تصميم الطبقة الثانية هذا؟",
        "l2.why.wan": "لماذا تصميم WAN هذا؟",
        "l2.why.wireless": "لماذا هذا التخطيط اللاسلكي؟",
        "l2.why.qos": "لماذا قبول جودة الخدمة هذا؟",
        "l2.why.findings": "لماذا هذه النتائج؟",
        "l2.why.button": "لماذا هذه النتيجة؟",
        "l2.l2.why": "لماذا تصميم الطبقة الثانية هذا؟",
        "l2.wan.why": "لماذا تصميم WAN هذا؟",
        "l2.wireless.why": "لماذا هذا التخطيط اللاسلكي؟",
        "l2.qos.why": "لماذا قبول جودة الخدمة هذا؟",
        "l2.field.vlan_id": "معرّف VLAN",
        "l2.field.gateway_device": "جهاز البوابة",
        "l2.field.switch_id": "معرّف المبدل",
        "l2.field.priority": "الأولوية",
        "l2.field.link_ids": "معرّفات الروابط (مفصولة بفواصل)",
        "l2.field.site_id": "معرّف الموقع",
        "l2.field.site_type": "نوع الموقع",
        "l2.field.area_id": "معرّف المنطقة",
        "l2.field.area_m2": "المساحة (م2)",
        "l2.field.clients": "العملاء المُنمذجون",
        "l2.field.client_mbps": "ميجابت في الثانية لكل عميل",
        "l2.field.ap_capacity_mbps": "سعة نقطة الوصول (ميجابت/ث)",
        "l2.field.coverage_radius_m": "نطاق التغطية (م)",
        "l2.field.utilization_target": "هدف الاستخدام",
        "l2.field.overlap_factor": "معامل التداخل",
        "l2.field.link_id": "معرّف الرابط",
        "l2.field.traffic_class": "فئة الحركة",
        "l2.field.share_cap": "حد الحصة (0-1)",
        "l2.field.default_class": "الفئة الافتراضية",
        "l2.empty.no_bundles": "لا توجد مجموعات EtherChannel مُنمذجة.",
        "l2.empty.no_areas": "لا توجد مناطق لاسلكية مُنمذجة.",
        "l2.empty.no_caps": "لا توجد حدود حصة مُنمذجة مخزنة.",
        "l2.empty.no_findings": "لا توجد نتائج محفوظة لهذا النموذج.",
        "l2.review.run": "تشغيل مراجعة تصميم محدودة",
        "l2.review.cancel": "إلغاء المراجعة",
        "l2.review.clear": "مسح نتيجة المراجعة",
        "l2.review.running": "مراجعة التصميم المحدودة قيد التشغيل.",
        "l2.review.empty": "لا توجد نتيجة مراجعة تصميم محدودة محفوظة.",
        "l2.review.done": "اكتملت مراجعة التصميم المحدودة.",
        "l2.section.layer2": "تبديل الطبقة الثانية",
        "l2.section.wan": "شبكة WAN والمواقع المتعددة",
        "l2.section.wireless": "اللاسلكي المجرد",
        "l2.section.qos": "قبول جودة الخدمة",
        "l2.section.findings": "مراجعة تصميم محدودة",
        "ip.tab.dual_stack": "مخطط IPv6 مزدوج",
        "ip.tab.nat": "مخطط NAT/PAT",
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
        # B4 executive summary
        "reports.executive.title": "الملخص التنفيذي (صفحتان)",
        "reports.executive.caption": (
            "ملخص مختصر يُحسب من المصادر المختارة. لغة التقرير تتبع لغة "
            "الواجهة المضبوطة في صفحة الإعدادات."
        ),
        "reports.executive.language": "لغة التقرير: {language}.",
        "reports.executive.language_switch": "غيّر اللغة من صفحة الإعدادات.",
        "reports.executive.not_run": "أقسام لم تُشغّل: {count}.",
        "reports.executive.consistent": (
            "الاتساق الرقمي: سليم (تم فحص {count} قيمة بمصدر)."
        ),
        "reports.executive.inconsistent": (
            "الاتساق الرقمي: {count} ملاحظة؛ راجع التقرير الكامل."
        ),
        "reports.executive.pdf_ready": "PDF: {pages} صفحة، {bytes} بايت.",
        "reports.executive.download_pdf": "تنزيل الملخص التنفيذي PDF",
        "reports.executive.download_markdown": "تنزيل الملخص التنفيذي Markdown",
        "reports.executive.empty_sources": (
            "لم يتم اختيار مصادر اختيارية؛ الأقسام الناقصة موضحة كـ«لم يُشغّل» "
            "مع الصفحة التي تنتجها."
        ),
        # B2 project bundles (Save / Open)
        "bundle.title": "حزمة المشروع",
        "bundle.save.title": "حفظ حزمة المشروع",
        "bundle.save.caption": (
            "أنشئ أرشيفاً حتمياً واحداً في الذاكرة من هذه الجلسة: التوأم "
            "واللقطة والتشغيلات المحفوظة بصماتها والقرارات والتدفقات المُنمذجة "
            "والإعدادات غير السرية. لا يُكتب أي شيء إلى القرص."
        ),
        "bundle.save.prepare": "تجهيز الحزمة",
        "bundle.save.ready": "الحزمة جاهزة: {bytes} بايت.",
        "bundle.save.download": "تنزيل حزمة المشروع",
        "bundle.save.requires_twin": "حمّل توأماً رقمياً قبل تجهيز حزمة.",
        "bundle.open.title": "فتح حزمة مشروع",
        "bundle.open.caption": (
            "استورد حزمة محفوظة سابقاً. يُفحص الأرشيف من حيث مسارات الملفات "
            "والحجم والمجموع الاختباري والمخطط قبل عرض أي شيء."
        ),
        "bundle.open.upload": "ملف الحزمة (.zip)",
        "bundle.open.preview_title": "معاينة الحزمة",
        "bundle.open.preview": (
            "التوأم: {name} | المخطط: {schema} | الأجهزة: {devices} | "
            "الروابط: {links} | البصمة: {fingerprint} | الصيغة: v{version}"
        ),
        "bundle.open.counts": (
            "اللقطات: {snapshots} | المحاكاة: {simulations} | "
            "التحسين: {optimizations} | القرارات: {decisions} | "
            "التدفقات: {flows}"
        ),
        "bundle.open.mode": "وضع الاستيراد",
        "bundle.open.mode.replace": "استبدال التوأم الحالي",
        "bundle.open.mode.snapshot": "الاستيراد كلقطة جديدة",
        "bundle.open.mode.help": (
            "الاستيراد كلقطة جديدة يُبقي التوأم الحالي دون تغيير ويخزّن "
            "التوأم المستورد كلقطة إضافية محدودة."
        ),
        "bundle.open.confirm": "تأكيد الاستيراد",
        "bundle.open.cancel": "إلغاء الاستيراد",
        "bundle.open.imported": "تم استيراد الحزمة: {name}.",
        "bundle.open.invalid": "تعذّر استيراد الحزمة.",
        "bundle.open.processed": (
            "تم استيراد هذا الملف أو إلغاؤه سابقاً. اختر ملفاً آخر لتجهيز استيراد جديد."
        ),
        "bundle.unsaved": (
            "التصميم الحالي يحتوي على تغييرات غير محفوظة. جهّز حزمة مشروع "
            "من صفحة التوأم الرقمي قبل استبداله."
        ),
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
        "settings.base_url": "عنوان URL الأساسي",
        "settings.base_url_default": "افتراضي",
        "settings.base_url_custom": "مخصص",
        "settings.key_source_secrets": "أسرار Streamlit",
        "settings.key_source_environment": "متغير البيئة",
        "settings.key_source_none": "غير مضبط",
        "settings.key_privacy": (
            "لا يتم عرض المفتاح أو تسجيله أو تتبعه أو حفظه على القرص. "
            "يُقرأ فقط من أسرار Streamlit أو متغيرات البيئة."
        ),
        "settings.budget": "ميزانية طلبات الجلسة",
        "settings.app_safeguard": "حماية التطبيق",
        "settings.app_safeguard_caption": (
            "حدود محلية للجلسة فقط. هذه الحدود لم تتغير وليست حدود معدل المزود."
        ),
        "settings.requests_used": "الطلبات المستخدمة",
        "settings.tokens_used": "الرموز المستخدمة",
        "settings.requests_remaining": "الطلبات المتبقية",
        "settings.tokens_remaining": "الرموز المتبقية",
        "settings.request_budget_used": "ميزانية الطلبات المستخدمة",
        "settings.token_budget_used": "ميزانية الرموز المستخدمة",
        "settings.budget_reset": "إعادة ضبط ميزانية الجلسة",
        "settings.provider_limits_title": "حدود معدل المزود (من آخر استجابة)",
        "settings.provider_limits_caption": (
            "هذه قيم حدود معدل أبلغ عنها المزود لأخر طلب، وليست فوترة الحساب "
            "أو الاستخدام الشهري."
        ),
        "settings.provider_limits_empty": (
            "لم يتم تسجيل أي استجابة من المزود بعد. استخدم زر اختبار الاتصال "
            "أعلاه لتحديث هذه اللقطة."
        ),
        "settings.not_reported": "غير مُبلَّغ عنه",
        "settings.provider_remaining_requests": "الطلبات المتبقية لدى المزود",
        "settings.provider_remaining_tokens": "الرموز المتبقية لدى المزود",
        "settings.provider_reset_requests": "إعادة تعيين المزود (الطلبات)",
        "settings.provider_reset_tokens": "إعادة تعيين المزود (الرموز)",
        "settings.provider_retry_after": "إعادة المحاولة بعد (المزود)",
        "settings.real_tokens_used": "الرموز الحقيقية المستخدمة هذه الجلسة",
        "settings.estimated_tokens_used": "الرموز المقدّرة المستخدمة هذه الجلسة",
        "settings.last_call_time": "وقت آخر اتصال",
        "settings.last_usage_source": "مصدر الاستخدام الأخير",
        "settings.usage_reported": "مُبلَّغ من المزود",
        "settings.usage_estimated": "تقديري",
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
        "settings.connection_add_key": (
            "اضبط مفتاحاً في أسرار Streamlit أو متغيرات البيئة لتمكين الاختبار."
        ),
        "settings.connection_button": "اختبار الاتصال",
        "settings.connection_success": (
            "تم الاتصال. أبلغ المزود عن الطراز {model}؛ استخدم {tokens} رمزاً "
            "({usage_source})."
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
            "يُقرأ مفتاح API فقط من أسرار Streamlit أو متغيرات البيئة. "
            "لا يُدخل في هذه الواجهة ولا يُكتب إلى اللقطات أو الآثار "
            "أو السجلات أو التنزيلات أو المستودع."
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
            "- **حالة الجلسة فقط:** التوائم والتشغيلات والآثار موجودة في جلسة "
            "هذا المتصفح فقط. نزّل ما تحتاجه قبل الإغلاق. يُقرأ مفتاح API فقط "
            "من أسرار Streamlit أو متغيرات البيئة ولا يُدخل في الواجهة.\n"
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
        # S6 design-time security tabs
        "security.page.title": "تحليل الأمان",
        "security.page.intro": (
            "نمذجة مناطق الثقة والسياسات وفحوص التدفق مقابل التوأم الرقمي "
            "الحالي. لا تقوم هذه الصفحة بفحص أو استقصاء أو الاتصال بأي جهاز "
            "أو البحث عن ثغرات."
        ),
        "security.scope": "نطاق النموذج",
        "security.empty.message": (
            "لا يوجد توأم رقمي مع طوبولوجيا محمّل. افتح محرر الطوبولوجيا "
            "لإنشاء تصميم أو توليده أو استيراده، ثم عد إلى هنا."
        ),
        "security.empty.title": "التوأم الرقمي مطلوب",
        "security.empty.hint": (
            "نتائج الأمان تُنمذج من مراجعة توأم رقمي مخزّنة فقط."
        ),
        "security.tab.zones": "المناطق",
        "security.tab.policy": "السياسة",
        "security.tab.flow": "فحص التدفق",
        "security.tab.reachability": "قابلية الوصول",
        "security.tab.segmentation": "التجزئة",
        "security.tab.optimizer": "المحسِّن",
        "security.tab.zero_trust": "الثقة المعدومة",
        "security.tab.findings": "النتائج",
        "security.tab.checklist": "قائمة التحقق",
        "security.tab.templates": "القوالب",
        "security.reachability.title": "قابلية الوصول للسياسة المُنمذجة",
        "security.reachability.caption": (
            "شبكة المناطق × الخدمات الكاملة هي نموذج سياسة وقت التصميم. "
            "ليست مسار هجوم أو سلسلة استغلال أو فحصاً لشبكة مباشرة."
        ),
        "security.reachability.blast_radius": "نطاق التأثير المحدود",
        "security.reachability.why": "لماذا قابلية الوصول هذه؟",
        "security.segmentation.title": "درجة التجزئة المُنمذجة",
        "security.segmentation.caption": (
            "كل مُدخل مرجّح ظاهر حتى يمكن التحقق من الدرجة الصحيحة يدوياً. "
            "الأهمية قراءة تصميمية وليست قيمة CVSS."
        ),
        "security.segmentation.why": "لماذا هذه الدرجة؟",
        "security.optimizer.title": "تحسينات سياسة غير مُطبَّقة",
        "security.optimizer.caption": (
            "كل اقتراح مصحوب بإثبات جدول قرارات محدود. الاختيار ينشئ توأماً "
            "جديداً؛ لا يتم توليد أي إعداد جهاز."
        ),
        "security.optimizer.select": "التحسينات المطلوب تطبيقها",
        "security.optimizer.apply": "تطبيق التحسينات المحددة",
        "security.optimizer.empty": "لم يتم إنتاج اقتراحات تحسين.",
        "security.optimizer.applied": "تم تطبيق {count} تحسين على توأم جديد.",
        "security.zero_trust.title": "التجزئة الدقيقة للثقة المعدومة",
        "security.zero_trust.caption": (
            "الاقتراحات متوافقة مع الممارسة الشائعة على مستوى التصميم فقط. "
            "قواعد السماح مستمدة من احتياجات مُنمذجة، وقواعد المنع تغطي "
            "الأزواج الأقل ثقة دون حاجة مُنمذجة."
        ),
        "security.zero_trust.select": "الاقتراحات المطلوب تطبيقها",
        "security.zero_trust.apply": "تطبيق الاقتراحات المحددة",
        "security.zero_trust.empty": "لم يتم إنتاج اقتراحات تجزئة دقيقة.",
        "security.zero_trust.applied": "تم تطبيق {count} اقتراح على توأم جديد.",
        "security.checklist.title": "قائمة تحقق التصميم",
        "security.checklist.caption": (
            "قائمة تحقق تصميم متوافقة مع الممارسة الشائعة (على مستوى "
            "التصميم). لا يُدّعى أي امتثال أو شهادة."
        ),
        "security.checklist.version": "إصدار قائمة التحقق",
        "security.checklist.health": "صحة التصميم الأساسية",
        "status.pass": "ناجح",
        "status.fail": "فاشل",
        "status.not-modeled": "غير مُنمذج",
        "status.exposed": "مُعرّض",
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
