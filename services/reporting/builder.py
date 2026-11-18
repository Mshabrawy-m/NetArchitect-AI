"""Assemble a report document from validated application data (Phase 11a).

The builder is a pure function of its inputs: the digital twin, optionally a
completed agent workflow, a scenario run, and an optimization run. It never
calls a language model and never invents a value. Numbers are copied from the
engines, formatted through :func:`~services.reporting.formatting.format_number`,
and recorded in the document's ``values`` appendix with step, tool, and twin
fingerprint.

Sections whose inputs are absent are kept with ``status="not_run"`` and a
pointer to the page that produces the data. The report never substitutes a
placeholder number for missing data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from config.limits import MAX_REPORT_TABLE_ROWS
from digital_twin import DigitalTwin, failed_entities
from network.analysis import METRIC_DEFINITIONS, AnalysisReport, analyze_topology
from network.routing import reachability_matrix, routing_table
from simulation import MODEL_NOTE, twin_reference

from . import templates
from .formatting import format_number, numeric_tokens
from .models import (
    REPORT_SCHEMA_VERSION,
    KeyValueBlock,
    KeyValueItem,
    NoteBlock,
    ParagraphBlock,
    Provenance,
    ReportDocument,
    ReportSection,
    ReportTwin,
    SectionStatus,
    TableBlock,
    ValueRecord,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agents.models import WorkflowState
    from capacity.models import CapacityRun
    from optimization.models import OptimizationRun
    from simulation.scenarios import ScenarioRun

REPORT_TITLE_PREFIX = "Network design report"
_REPORT_STEP = "report"
_REPORT_TOOL = "services.reporting.builder"


@dataclass(frozen=True)
class ReportSources:
    """Validated inputs the report may draw from."""

    twin: DigitalTwin
    title: str = ""
    workflow: WorkflowState | None = None
    scenario_run: ScenarioRun | None = None
    optimization_run: OptimizationRun | None = None
    capacity_run: CapacityRun | None = None
    # OptimizationRun has no persisted twin fingerprint. The UI records the
    # fingerprint of its source twin when the run is created and passes it here.
    optimization_source_fingerprint: str | None = None
    generated_at: datetime | None = None


class _Collector:
    """Record every printed value once, with provenance."""

    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint
        self.records: dict[str, ValueRecord] = {}

    def number(
        self,
        key: str,
        label: str,
        value: float,
        *,
        step: str,
        tool: str,
        unit: str = "",
        digits: int = 2,
        twin_version: str | None = None,
    ) -> str:
        """Format one number, record it, and return the printed text."""
        display = format_number(value, digits=digits)
        self.records[key] = ValueRecord(
            key=key,
            label=label,
            display=display,
            numeric=float(value),
            unit=unit,
            provenance=Provenance(
                step=step,
                tool=tool,
                twin_version=twin_version or self.fingerprint,
            ),
        )
        return display

    def text(
        self,
        key: str,
        label: str,
        value: str,
        *,
        step: str,
        tool: str,
        twin_version: str | None = None,
    ) -> str:
        """Record one non-numeric fact and return it unchanged."""
        self.records[key] = ValueRecord(
            key=key,
            label=label,
            display=value,
            numeric=None,
            provenance=Provenance(
                step=step,
                tool=tool,
                twin_version=twin_version or self.fingerprint,
            ),
        )
        return value

    def scan(
        self,
        key_prefix: str,
        label: str,
        text: str,
        *,
        step: str,
        tool: str,
        twin_version: str | None = None,
    ) -> str:
        """Record numbers inside copied engine text so they stay traceable.

        Used only for text the engines already produced (finding explanations,
        run notes, path descriptions). The text is reproduced verbatim; the
        helper never edits it.
        """
        seen: set[str] = set()
        for index, token in enumerate(numeric_tokens(text), start=1):
            if token in seen:
                continue
            seen.add(token)
            self.records[f"{key_prefix}.token.{index}"] = ValueRecord(
                key=f"{key_prefix}.token.{index}",
                label=f"{label} (copied token)",
                display=token,
                numeric=float(token),
                provenance=Provenance(
                    step=step,
                    tool=tool,
                    twin_version=twin_version or self.fingerprint,
                ),
            )
        return text


class _Builder:
    """Build all report sections from one set of validated sources."""

    def __init__(self, sources: ReportSources, fingerprint: str) -> None:
        self.twin = sources.twin
        self.workflow = sources.workflow
        self.scenario_run = sources.scenario_run
        self.optimization_run = sources.optimization_run
        self.optimization_source_fingerprint = sources.optimization_source_fingerprint
        self.capacity_run = sources.capacity_run
        self.fingerprint = fingerprint
        self.numbers = _Collector(fingerprint)
        self._analysis_report: AnalysisReport | None = None

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def prov(
        self,
        step: str,
        tool: str,
        twin_version: str | None = None,
    ) -> Provenance:
        return Provenance(
            step=step,
            tool=tool,
            twin_version=twin_version or self.fingerprint,
        )

    def table(
        self,
        table_id: str,
        title: str,
        columns: tuple[str, ...],
        rows: list[tuple[str, ...]],
        *,
        step: str,
        tool: str,
        twin_version: str | None = None,
        total_rows: int | None = None,
    ) -> TableBlock:
        total = len(rows) if total_rows is None else total_rows
        bounded = rows[:MAX_REPORT_TABLE_ROWS]
        return TableBlock(
            id=table_id,
            title=title,
            columns=columns,
            rows=tuple(bounded),
            total_rows=total,
            provenance=self.prov(step, tool, twin_version),
        )

    def analysis(self) -> AnalysisReport:
        if self._analysis_report is None:
            self._analysis_report = analyze_topology(
                self.twin.topology,
                **failed_entities(self.twin).as_kwargs(),
            )
        return self._analysis_report

    def not_run(
        self,
        section_id: str,
        title: str,
        reason: str,
        producer_page: str,
    ) -> ReportSection:
        return ReportSection(
            id=section_id,
            title=title,
            status=SectionStatus.not_run,
            unavailable_reason=reason,
            producer_page=producer_page,
        )

    def stale_source_note(
        self,
        key_prefix: str,
        label: str,
        source_fingerprint: str,
        *,
        step: str,
        tool: str,
    ) -> NoteBlock | None:
        """Return a visible warning when a run has a different source twin."""
        if source_fingerprint == self.fingerprint:
            return None
        if source_fingerprint:
            text = (
                f"Source twin mismatch: this {label} run used fingerprint "
                f"{source_fingerprint}, while the current twin fingerprint is "
                f"{self.fingerprint}. Re-run it before relying on these values."
            )
        else:
            text = (
                f"Source twin unavailable: the selected {label} run has no "
                "recorded source fingerprint, so freshness against the current "
                "twin cannot be verified."
            )
        return NoteBlock(
            text=self.numbers.text(
                f"{key_prefix}.source_warning",
                f"{label} source warning",
                text,
                step=step,
                tool=tool,
                twin_version=source_fingerprint or None,
            ),
            severity="warning",
            provenance=self.prov(step, tool, source_fingerprint or None),
        )

    # ------------------------------------------------------------------
    # 1. Architecture summary
    # ------------------------------------------------------------------
    def architecture_summary(self) -> ReportSection:
        section_id = "architecture_summary"
        title = "Architecture summary"
        devices = self.twin.topology.devices
        if not devices:
            return self.not_run(
                section_id,
                title,
                "The twin contains no devices, so there is nothing to summarize.",
                "Topology Editor",
            )
        analysis = self.analysis()
        values = self.numbers
        device_count = values.number(
            "architecture.device_count",
            "Devices",
            len(devices),
            step="topology",
            tool="digital_twin.topology",
        )
        link_count = values.number(
            "architecture.link_count",
            "Links",
            len(self.twin.topology.links),
            step="topology",
            tool="digital_twin.topology",
        )
        site_count = values.number(
            "architecture.site_count",
            "Sites",
            len({device.site for device in devices}),
            step="topology",
            tool="digital_twin.topology",
            digits=0,
        )
        demand_count = values.number(
            "architecture.demand_count",
            "Traffic demands",
            len(self.twin.demands),
            step="simulation",
            tool="digital_twin.demands",
            digits=0,
        )
        spof_count = values.number(
            "architecture.spof_count",
            "Single points of failure",
            len(analysis.spof.entries),
            step="analysis",
            tool="network.analysis.spof_report",
            digits=0,
        )
        paragraph = ParagraphBlock(
            text=templates.architecture_summary(
                twin_name=self.twin.metadata.name,
                device_count=device_count,
                link_count=link_count,
                site_count=site_count,
                demand_count=demand_count,
                connected=analysis.components.is_connected,
                spof_count=spof_count,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        created_at = values.scan(
            "architecture.created_at",
            "Twin created at",
            self.twin.metadata.created_at.isoformat(),
            step="twin",
            tool="digital_twin.TwinMetadata",
        )
        kv = KeyValueBlock(
            title="Twin reference",
            items=(
                KeyValueItem(
                    key="name",
                    value=self.twin.metadata.name,
                    provenance=self.prov("twin", "digital_twin.TwinMetadata"),
                ),
                KeyValueItem(
                    key="created_at",
                    value=created_at,
                    provenance=self.prov("twin", "digital_twin.TwinMetadata"),
                ),
                KeyValueItem(
                    key="schema_version",
                    value=values.number(
                        "architecture.schema_version",
                        "Twin schema version",
                        self.twin.metadata.schema_version,
                        step="twin",
                        tool="digital_twin.TwinMetadata",
                        digits=0,
                    ),
                    provenance=self.prov("twin", "digital_twin.TwinMetadata"),
                ),
                KeyValueItem(
                    key="fingerprint",
                    value=self.fingerprint,
                    provenance=self.prov("twin", "simulation.twin_fingerprint"),
                ),
            ),
        )
        note = NoteBlock(
            text=(
                "The twin is a software model. It is not a connection to, or a "
                "live copy of, real networking equipment."
            ),
            severity="info",
            provenance=self.prov("report", "services.reporting.builder"),
        )
        return ReportSection(
            id=section_id,
            title=title,
            blocks=(paragraph, kv, note),
        )

    # ------------------------------------------------------------------
    # 2. Topology and selection rationale
    # ------------------------------------------------------------------
    def topology(self) -> ReportSection:
        section_id = "topology"
        title = "Topology and selection rationale"
        devices = self.twin.topology.devices
        if not devices:
            return self.not_run(
                section_id,
                title,
                "The twin contains no devices; open the Topology Editor to build one.",
                "Topology Editor",
            )
        analysis = self.analysis()
        values = self.numbers
        device_count = values.number(
            "topology.device_count",
            "Devices",
            len(devices),
            step="topology",
            tool="digital_twin.topology",
            digits=0,
        )
        link_count = values.number(
            "topology.link_count",
            "Links",
            len(self.twin.topology.links),
            step="topology",
            tool="digital_twin.topology",
            digits=0,
        )
        site_count = values.number(
            "topology.site_count",
            "Sites",
            len({device.site for device in devices}),
            step="topology",
            tool="digital_twin.topology",
            digits=0,
        )
        directed_count = values.number(
            "topology.directed_link_count",
            "Directed links",
            sum(1 for link in self.twin.topology.links if link.directed),
            step="topology",
            tool="digital_twin.topology",
            digits=0,
        )
        total_capacity = values.number(
            "topology.total_capacity_mbps",
            "Total modeled link capacity",
            sum(link.capacity_mbps for link in self.twin.topology.links),
            step="topology",
            tool="digital_twin.topology",
            unit="Mbps",
            digits=2,
        )
        demand_count = values.number(
            "topology.demand_count",
            "Traffic demands",
            len(self.twin.demands),
            step="simulation",
            tool="digital_twin.demands",
            digits=0,
        )
        workflow_steps = ""
        if self.workflow is not None:
            workflow_steps = values.number(
                "topology.workflow_steps",
                "Completed workflow steps",
                self.workflow.steps,
                step="workflow",
                tool="agents.models.WorkflowState",
                digits=0,
            )
        paragraph = ParagraphBlock(
            text=templates.topology_rationale(
                device_count=device_count,
                link_count=link_count,
                site_count=site_count,
                connected=analysis.components.is_connected,
                workflow_steps=workflow_steps,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Topology totals",
            items=(
                KeyValueItem(
                    key="devices",
                    value=device_count,
                    provenance=self.prov("topology", "digital_twin.topology"),
                ),
                KeyValueItem(
                    key="links",
                    value=link_count,
                    provenance=self.prov("topology", "digital_twin.topology"),
                ),
                KeyValueItem(
                    key="directed_links",
                    value=directed_count,
                    provenance=self.prov("topology", "digital_twin.topology"),
                ),
                KeyValueItem(
                    key="sites",
                    value=site_count,
                    provenance=self.prov("topology", "digital_twin.topology"),
                ),
                KeyValueItem(
                    key="total_capacity",
                    value=total_capacity,
                    unit="Mbps",
                    provenance=self.prov("topology", "digital_twin.topology"),
                ),
                KeyValueItem(
                    key="demands",
                    value=demand_count,
                    provenance=self.prov("simulation", "digital_twin.demands"),
                ),
            ),
        )

        type_counter = Counter(device.type.value for device in devices)
        type_rows: list[tuple[str, ...]] = []
        for index, (device_type, count) in enumerate(sorted(type_counter.items())):
            type_rows.append(
                (
                    device_type,
                    values.number(
                        f"topology.type.{index}.count",
                        f"Devices of type {device_type}",
                        count,
                        step="topology",
                        tool="digital_twin.topology",
                        digits=0,
                    ),
                )
            )
        type_table = self.table(
            "devices_by_type",
            "Devices by type",
            ("Device type", "Count"),
            type_rows,
            step="topology",
            tool="digital_twin.topology",
        )

        site_counter = Counter(device.site for device in devices)
        site_rows: list[tuple[str, ...]] = []
        for index, (site, count) in enumerate(sorted(site_counter.items())):
            site_rows.append(
                (
                    site,
                    values.number(
                        f"topology.site.{index}.count",
                        f"Devices at site {site}",
                        count,
                        step="topology",
                        tool="digital_twin.topology",
                        digits=0,
                    ),
                )
            )
        site_table = self.table(
            "devices_by_site",
            "Devices by site",
            ("Site", "Devices"),
            site_rows,
            step="topology",
            tool="digital_twin.topology",
        )
        return ReportSection(
            id=section_id,
            title=title,
            blocks=(paragraph, kv, type_table, site_table),
        )

    # ------------------------------------------------------------------
    # 3. IP addressing
    # ------------------------------------------------------------------
    def addressing(self) -> ReportSection:
        section_id = "addressing"
        title = "IP addressing"
        plan = self.twin.addressing
        subnets: list[tuple[str, int | None, str]] = []
        if plan is not None:
            for vlan_plan in plan.vlan_plans:
                for subnet in vlan_plan.subnets:
                    subnets.append(
                        (subnet.name, subnet.vlan_id or vlan_plan.vlan_id, str(subnet.network))
                    )
            for subnet in plan.subnets:
                subnets.append((subnet.name, subnet.vlan_id, str(subnet.network)))
            descriptions = {
                subnet.name: subnet.description
                for vlan_plan in plan.vlan_plans
                for subnet in vlan_plan.subnets
            }
            descriptions.update(
                {subnet.name: subnet.description for subnet in plan.subnets}
            )
        else:
            descriptions = {}
        if not subnets:
            return self.not_run(
                section_id,
                title,
                "No addressing plan is stored in the twin.",
                "IP Addressing & Subnetting",
            )
        values = self.numbers
        rows: list[tuple[str, ...]] = []
        for index, (name, vlan_id, network) in enumerate(subnets):
            vlan_display = "-"
            if vlan_id is not None:
                vlan_display = values.number(
                    f"addressing.subnet.{index}.vlan",
                    f"VLAN id of subnet {name}",
                    vlan_id,
                    step="ip_vlan",
                    tool="network.vlan.plan_vlans",
                    digits=0,
                )
            rows.append(
                (
                    name,
                    network,
                    vlan_display,
                    descriptions.get(name, "") or "-",
                )
            )
        table = self.table(
            "ip_plan",
            "Subnet allocation",
            ("Subnet", "Network", "VLAN", "Description"),
            rows,
            step="ip_vlan",
            tool="network.vlan.plan_vlans",
        )
        total = values.number(
            "addressing.subnet_count",
            "Subnets",
            len(subnets),
            step="ip_vlan",
            tool="network.vlan.plan_vlans",
            digits=0,
        )
        tagged = values.number(
            "addressing.vlan_subnet_count",
            "VLAN-tagged subnets",
            sum(1 for _, vlan_id, _ in subnets if vlan_id is not None),
            step="ip_vlan",
            tool="network.vlan.plan_vlans",
            digits=0,
        )
        standalone = values.number(
            "addressing.standalone_subnet_count",
            "Standalone subnets",
            sum(1 for _, vlan_id, _ in subnets if vlan_id is None),
            step="ip_vlan",
            tool="network.vlan.plan_vlans",
            digits=0,
        )
        paragraph = ParagraphBlock(
            text=templates.addressing_summary(
                subnet_count=total,
                vlan_subnet_count=tagged,
                standalone_subnet_count=standalone,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Addressing totals",
            items=(
                KeyValueItem(
                    key="subnets",
                    value=total,
                    provenance=self.prov("ip_vlan", "network.vlan.plan_vlans"),
                ),
                KeyValueItem(
                    key="vlan_tagged",
                    value=tagged,
                    provenance=self.prov("ip_vlan", "network.vlan.plan_vlans"),
                ),
                KeyValueItem(
                    key="standalone",
                    value=standalone,
                    provenance=self.prov("ip_vlan", "network.vlan.plan_vlans"),
                ),
            ),
        )
        return ReportSection(id=section_id, title=title, blocks=(paragraph, kv, table))

    # ------------------------------------------------------------------
    # 4. VLAN and DHCP
    # ------------------------------------------------------------------
    def vlan_dhcp(self) -> ReportSection:
        section_id = "vlan_dhcp"
        title = "VLAN and DHCP"
        assignments = (
            list(self.twin.vlan_plan.assignments)
            if self.twin.vlan_plan is not None
            else []
        )
        scopes = list(self.twin.dhcp_scopes)
        if not assignments and not scopes:
            return self.not_run(
                section_id,
                title,
                "No VLAN assignments or DHCP scopes are stored in the twin.",
                "VLAN & DHCP Planner",
            )
        values = self.numbers
        vlan_count = values.number(
            "vlan.assignment_count",
            "VLAN assignments",
            len(assignments),
            step="ip_vlan",
            tool="network.vlan.plan_vlans",
            digits=0,
        )
        dhcp_count = values.number(
            "dhcp.scope_count",
            "DHCP scopes",
            len(scopes),
            step="ip_vlan",
            tool="digital_twin.dhcp_scopes",
            digits=0,
        )
        blocks: list[Any] = [
            ParagraphBlock(
                text=templates.vlan_dhcp_summary(
                    vlan_count=vlan_count,
                    dhcp_count=dhcp_count,
                ),
                provenance=self.prov("report", "services.reporting.templates"),
            )
        ]
        if assignments:
            vlan_rows: list[tuple[str, ...]] = []
            for index, assignment in enumerate(assignments):
                vlan_rows.append(
                    (
                        assignment.department,
                        values.number(
                            f"vlan.assignment.{index}.vlan_id",
                            f"VLAN id for {assignment.department}",
                            assignment.vlan_id,
                            step="ip_vlan",
                            tool="network.vlan.plan_vlans",
                            digits=0,
                        ),
                        assignment.vlan_name,
                        assignment.subnet_name,
                        str(assignment.network),
                    )
                )
            blocks.append(
                self.table(
                    "vlan_assignments",
                    "VLAN assignments",
                    ("Department", "VLAN", "VLAN name", "Subnet", "Network"),
                    vlan_rows,
                    step="ip_vlan",
                    tool="network.vlan.plan_vlans",
                )
            )
        if scopes:
            dhcp_rows: list[tuple[str, ...]] = []
            for index, scope in enumerate(scopes):
                dhcp_rows.append(
                    (
                        scope.name,
                        str(scope.network),
                        str(scope.gateway) if scope.gateway is not None else "-",
                        str(scope.start_address)
                        if scope.start_address is not None
                        else "-",
                        str(scope.end_address)
                        if scope.end_address is not None
                        else "-",
                        values.number(
                            f"dhcp.scope.{index}.lease_minutes",
                            f"Lease minutes for {scope.name}",
                            scope.lease_minutes,
                            step="ip_vlan",
                            tool="digital_twin.dhcp_scopes",
                            digits=0,
                        ),
                        "; ".join(
                            f"{start} - {end}" for start, end in scope.excluded_ranges
                        )
                        or "-",
                    )
                )
            blocks.append(
                self.table(
                    "dhcp_scopes",
                    "DHCP scopes",
                    (
                        "Scope",
                        "Network",
                        "Gateway",
                        "Start",
                        "End",
                        "Lease (min)",
                        "Excluded ranges",
                    ),
                    dhcp_rows,
                    step="ip_vlan",
                    tool="digital_twin.dhcp_scopes",
                )
            )
        blocks.append(
            NoteBlock(
                text=(
                    "Lease durations are in minutes. Identifiers and addresses "
                    "are copied from the validated plan; no DHCP server or "
                    "device is configured."
                ),
                severity="info",
                provenance=self.prov("ip_vlan", "digital_twin.dhcp_scopes"),
            )
        )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # 5. Routing and reachability
    # ------------------------------------------------------------------
    def routing(self) -> ReportSection:
        section_id = "routing"
        title = "Routing and reachability"
        topology = self.twin.topology
        if not topology.devices:
            return self.not_run(
                section_id,
                title,
                "The twin contains no devices to route between.",
                "Routing Analysis",
            )
        selection = failed_entities(self.twin)
        kwargs = selection.as_kwargs()
        failed_devices = set(selection.devices)
        surviving = sorted(
            device.id for device in topology.devices if device.id not in failed_devices
        )
        if not surviving:
            return self.not_run(
                section_id,
                title,
                "Every device is modeled as down, so no route can be computed.",
                "Routing Analysis",
            )
        demand_sources = [
            demand.source for demand in self.twin.demands if demand.source in surviving
        ]
        source = demand_sources[0] if demand_sources else surviving[0]
        matrix = reachability_matrix(topology, **kwargs)
        table_result = routing_table(topology, source, **kwargs)
        values = self.numbers
        device_count = values.number(
            "routing.device_count",
            "Devices on the routing graph",
            len(surviving),
            step="routing",
            tool="network.routing.reachability_matrix",
            digits=0,
        )
        unreachable = values.number(
            "routing.unreachable_pairs",
            "Unreachable ordered pairs",
            matrix.unreachable_pairs,
            step="routing",
            tool="network.routing.reachability_matrix",
            digits=0,
        )
        entry_count = values.number(
            "routing.entry_count",
            "Routing table entries",
            len(table_result.entries),
            step="routing",
            tool="network.routing.routing_table",
            digits=0,
        )
        failed_device_count = values.number(
            "routing.failed_device_count",
            "Failed devices",
            len(selection.devices),
            step="twin",
            tool="digital_twin.failed_entities",
            digits=0,
        )
        failed_link_count = values.number(
            "routing.failed_link_count",
            "Failed links",
            len(selection.links),
            step="twin",
            tool="digital_twin.failed_entities",
            digits=0,
        )
        paragraph = ParagraphBlock(
            text=templates.routing_summary(
                source=source,
                device_count=device_count,
                unreachable_pairs=unreachable,
                entry_count=entry_count,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Routing summary",
            items=(
                KeyValueItem(
                    key="source",
                    value=source,
                    provenance=self.prov("routing", "network.routing.core"),
                ),
                KeyValueItem(
                    key="devices",
                    value=device_count,
                    provenance=self.prov("routing", "network.routing.core"),
                ),
                KeyValueItem(
                    key="unreachable_pairs",
                    value=unreachable,
                    provenance=self.prov("routing", "network.routing.core"),
                ),
                KeyValueItem(
                    key="failed_devices",
                    value=failed_device_count,
                    provenance=self.prov("twin", "digital_twin.failed_entities"),
                ),
                KeyValueItem(
                    key="failed_links",
                    value=failed_link_count,
                    provenance=self.prov("twin", "digital_twin.failed_entities"),
                ),
            ),
        )
        route_rows: list[tuple[str, ...]] = []
        for index, entry in enumerate(table_result.entries):
            route_rows.append(
                (
                    entry.destination,
                    entry.next_hop,
                    entry.link_id,
                    values.number(
                        f"routing.entry.{index}.cost",
                        f"Route cost to {entry.destination}",
                        entry.total_cost,
                        step="routing",
                        tool="network.routing.routing_table",
                        digits=2,
                    ),
                    values.number(
                        f"routing.entry.{index}.hops",
                        f"Route hops to {entry.destination}",
                        entry.hop_count,
                        step="routing",
                        tool="network.routing.routing_table",
                        digits=0,
                    ),
                )
            )
        route_table = self.table(
            "routing_table",
            f"Routing table from {source}",
            ("Destination", "Next hop", "Link", "Total cost", "Hops"),
            route_rows,
            step="routing",
            tool="network.routing.routing_table",
        )

        ids = matrix.device_ids
        unreachable_rows: list[tuple[str, ...]] = []
        for first_index, first in enumerate(ids):
            for second_index, second in enumerate(ids):
                if first_index == second_index:
                    continue
                if matrix.matrix[first_index][second_index]:
                    continue
                unreachable_rows.append((first, second))
        unreachable_table = self.table(
            "unreachable_pairs",
            "Unreachable device pairs",
            ("Source", "Destination"),
            unreachable_rows,
            step="routing",
            tool="network.routing.reachability_matrix",
        )
        blocks: list[Any] = [paragraph, kv, route_table]
        if unreachable_rows:
            blocks.append(unreachable_table)
        else:
            blocks.append(
                NoteBlock(
                    text=(
                        "Every ordered device pair has a directed path on the "
                        "modeled graph."
                    ),
                    severity="info",
                    provenance=self.prov("routing", "network.routing"),
                )
            )
        if table_result.reason and not table_result.entries:
            blocks.append(
                NoteBlock(
                    text=f"Routing table note: {table_result.reason}",
                    severity="warning",
                    provenance=self.prov("routing", "network.routing.routing_table"),
                )
            )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # 6. Graph analysis and critical components
    # ------------------------------------------------------------------
    def graph_analysis(self) -> ReportSection:
        section_id = "graph_analysis"
        title = "Graph analysis and critical components"
        analysis = self.analysis()
        if not self.twin.topology.devices:
            return self.not_run(
                section_id,
                title,
                "The twin contains no devices to analyze.",
                "Network Analytics",
            )
        values = self.numbers
        component_count = values.number(
            "graph.component_count",
            "Connected components",
            analysis.components.component_count,
            step="analysis",
            tool="network.analysis.component_analysis",
            digits=0,
        )
        largest = values.number(
            "graph.largest_component_size",
            "Largest component size",
            analysis.components.largest_component_size,
            step="analysis",
            tool="network.analysis.component_analysis",
            digits=0,
        )
        critical_devices = values.number(
            "graph.critical_device_count",
            "Critical devices",
            len(analysis.critical_nodes.nodes),
            step="analysis",
            tool="network.analysis.critical_nodes",
            digits=0,
        )
        critical_links = values.number(
            "graph.critical_link_count",
            "Critical links",
            len(analysis.critical_links.links),
            step="analysis",
            tool="network.analysis.critical_links",
            digits=0,
        )
        spof_count = values.number(
            "graph.spof_count",
            "Single points of failure",
            len(analysis.spof.entries),
            step="analysis",
            tool="network.analysis.spof_report",
            digits=0,
        )
        paragraph = ParagraphBlock(
            text=templates.graph_summary(
                component_count=component_count,
                critical_device_count=critical_devices,
                critical_link_count=critical_links,
                connected=analysis.components.is_connected,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Structural summary",
            items=(
                KeyValueItem(
                    key="components",
                    value=component_count,
                    provenance=self.prov("analysis", "network.analysis"),
                ),
                KeyValueItem(
                    key="largest_component",
                    value=largest,
                    provenance=self.prov("analysis", "network.analysis"),
                ),
                KeyValueItem(
                    key="critical_devices",
                    value=critical_devices,
                    provenance=self.prov("analysis", "network.analysis"),
                ),
                KeyValueItem(
                    key="critical_links",
                    value=critical_links,
                    provenance=self.prov("analysis", "network.analysis"),
                ),
                KeyValueItem(
                    key="spof",
                    value=spof_count,
                    provenance=self.prov("analysis", "network.analysis"),
                ),
            ),
        )
        device_rows: list[tuple[str, ...]] = []
        for index, node in enumerate(analysis.critical_nodes.nodes):
            device_rows.append(
                (
                    node.device_id,
                    values.number(
                        f"graph.critical_device.{index}.components",
                        f"Components after removing {node.device_id}",
                        node.components_after_removal,
                        step="analysis",
                        tool="network.analysis.critical_nodes",
                        digits=0,
                    ),
                    ", ".join(node.isolated_device_ids) or "-",
                )
            )
        device_table = self.table(
            "critical_devices",
            "Critical devices",
            ("Device", "Components after removal", "Isolated devices"),
            device_rows,
            step="analysis",
            tool="network.analysis.critical_nodes",
        )
        link_rows: list[tuple[str, ...]] = []
        for index, link in enumerate(analysis.critical_links.links):
            link_rows.append(
                (
                    link.link_id,
                    " - ".join(link.endpoints),
                    values.number(
                        f"graph.critical_link.{index}.components",
                        f"Components after removing {link.link_id}",
                        link.components_after_removal,
                        step="analysis",
                        tool="network.analysis.critical_links",
                        digits=0,
                    ),
                    ", ".join(link.isolated_device_ids) or "-",
                )
            )
        link_table = self.table(
            "critical_links",
            "Critical links",
            ("Link", "Endpoints", "Components after removal", "Isolated devices"),
            link_rows,
            step="analysis",
            tool="network.analysis.critical_links",
        )

        ordered_metrics = sorted(
            analysis.centrality.metrics,
            key=lambda metric: (-metric.betweenness_centrality, metric.device_id),
        )[:10]
        centrality_rows: list[tuple[str, ...]] = []
        for index, metric in enumerate(ordered_metrics):
            centrality_rows.append(
                (
                    metric.device_id,
                    values.number(
                        f"graph.centrality.{index}.degree",
                        f"Degree of {metric.device_id}",
                        metric.degree,
                        step="analysis",
                        tool="network.analysis.centrality_metrics",
                        digits=0,
                    ),
                    values.number(
                        f"graph.centrality.{index}.degree_centrality",
                        f"Degree centrality of {metric.device_id}",
                        metric.degree_centrality,
                        step="analysis",
                        tool="network.analysis.centrality_metrics",
                        digits=4,
                    ),
                    values.number(
                        f"graph.centrality.{index}.betweenness",
                        f"Betweenness centrality of {metric.device_id}",
                        metric.betweenness_centrality,
                        step="analysis",
                        tool="network.analysis.centrality_metrics",
                        digits=4,
                    ),
                )
            )
        centrality_table = self.table(
            "centrality",
            "Highest betweenness centrality",
            ("Device", "Degree", "Degree centrality", "Betweenness centrality"),
            centrality_rows,
            step="analysis",
            tool="network.analysis.centrality_metrics",
        )

        finding_rows: list[tuple[str, ...]] = []
        for index, finding in enumerate(analysis.findings):
            finding_rows.append(
                (
                    finding.severity.value,
                    finding.code,
                    ", ".join(finding.affected_entities) or "-",
                    values.scan(
                        f"graph.finding.{index}",
                        f"Finding {finding.code}",
                        finding.explanation,
                        step="analysis",
                        tool="network.analysis.findings",
                    ),
                )
            )
        findings_table = self.table(
            "findings",
            "Analysis findings",
            ("Severity", "Code", "Entities", "Explanation"),
            finding_rows,
            step="analysis",
            tool="network.analysis.findings",
        )
        note = NoteBlock(
            text=METRIC_DEFINITIONS["betweenness_centrality"],
            severity="info",
            provenance=self.prov("analysis", "network.analysis.METRIC_DEFINITIONS"),
        )
        return ReportSection(
            id=section_id,
            title=title,
            blocks=(
                paragraph,
                kv,
                device_table,
                link_table,
                centrality_table,
                findings_table,
                note,
            ),
        )

    # ------------------------------------------------------------------
    # 7. Simulation before/after
    # ------------------------------------------------------------------
    def simulation(self) -> ReportSection:
        section_id = "simulation"
        title = "Simulation before and after"
        run = self.scenario_run
        if run is None:
            return self.not_run(
                section_id,
                title,
                "No simulation run is selected for this report.",
                "Simulation Lab",
            )
        values = self.numbers
        base_version = run.baseline_twin.fingerprint
        scenario_version = run.scenario_twin.fingerprint
        stale_note = self.stale_source_note(
            "simulation",
            "simulation",
            base_version,
            step="simulation",
            tool="simulation.run_scenario",
        )
        baseline = run.baseline_state
        scenario = run.scenario_state
        comparison = run.comparison

        scenario_name = values.text(
            "simulation.scenario_name",
            "Scenario name",
            run.scenario.name,
            step="simulation",
            tool="simulation.run_scenario",
            twin_version=base_version,
        )
        scenario_type = values.text(
            "simulation.scenario_type",
            "Scenario type",
            run.scenario.type.value,
            step="simulation",
            tool="simulation.run_scenario",
            twin_version=base_version,
        )
        delay_entries = values.number(
            "simulation.delay_entries",
            "Delay assumptions",
            len(run.assumptions.link_delay_ms),
            step="simulation",
            tool="simulation.models.SimulationAssumptions",
            digits=0,
            twin_version=base_version,
        )
        baseline_served = values.number(
            "simulation.baseline_served",
            "Baseline served demands",
            baseline.served_demand_count,
            step="simulation",
            tool="simulation.run_scenario",
            digits=0,
            twin_version=base_version,
        )
        scenario_served = values.number(
            "simulation.scenario_served",
            "Scenario served demands",
            scenario.served_demand_count,
            step="simulation",
            tool="simulation.run_scenario",
            digits=0,
            twin_version=scenario_version,
        )
        util_delta = values.number(
            "simulation.max_utilization_delta",
            "Maximum utilization delta",
            comparison.max_utilization_delta_percent,
            step="simulation",
            tool="simulation.scenarios.ScenarioComparison",
            unit="percentage points",
            digits=2,
            twin_version=scenario_version,
        )
        paragraph = ParagraphBlock(
            text=templates.simulation_summary(
                scenario_name=scenario_name,
                baseline_served=baseline_served,
                scenario_served=scenario_served,
                max_utilization_delta=util_delta,
                recovery_available=comparison.recovery_available,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Scenario",
            items=(
                KeyValueItem(
                    key="name",
                    value=scenario_name,
                    provenance=self.prov("simulation", "simulation.run_scenario", base_version),
                ),
                KeyValueItem(
                    key="type",
                    value=scenario_type,
                    provenance=self.prov("simulation", "simulation.run_scenario", base_version),
                ),
                KeyValueItem(
                    key="assumption_delays",
                    value=delay_entries,
                    provenance=self.prov("simulation", "simulation.run_scenario", base_version),
                ),
                KeyValueItem(
                    key="baseline_fingerprint",
                    value=base_version,
                    provenance=self.prov("simulation", "simulation.twin_fingerprint", base_version),
                ),
                KeyValueItem(
                    key="scenario_fingerprint",
                    value=scenario_version,
                    provenance=self.prov("simulation", "simulation.twin_fingerprint", scenario_version),
                ),
            ),
        )

        def delta(before: float, after: float, *, key: str, label: str, digits: int) -> str:
            return values.number(
                key,
                label,
                after - before,
                step="simulation",
                tool="simulation.scenarios.ScenarioComparison",
                digits=digits,
                twin_version=scenario_version,
            )

        comparison_rows = [
            (
                "Served demands",
                values.number(
                    "simulation.comparison.baseline_served",
                    "Baseline served demands",
                    baseline.served_demand_count,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=base_version,
                ),
                values.number(
                    "simulation.comparison.scenario_served",
                    "Scenario served demands",
                    scenario.served_demand_count,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=scenario_version,
                ),
                delta(
                    baseline.served_demand_count,
                    scenario.served_demand_count,
                    key="simulation.comparison.served_delta",
                    label="Served demand delta",
                    digits=0,
                ),
            ),
            (
                "Served demand ratio",
                values.number(
                    "simulation.comparison.baseline_ratio",
                    "Baseline served demand ratio",
                    baseline.served_demand_ratio,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=3,
                    twin_version=base_version,
                ),
                values.number(
                    "simulation.comparison.scenario_ratio",
                    "Scenario served demand ratio",
                    scenario.served_demand_ratio,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=3,
                    twin_version=scenario_version,
                ),
                delta(
                    baseline.served_demand_ratio,
                    scenario.served_demand_ratio,
                    key="simulation.comparison.ratio_delta",
                    label="Served demand ratio delta",
                    digits=3,
                ),
            ),
            (
                "Maximum utilization (%)",
                values.number(
                    "simulation.comparison.baseline_util",
                    "Baseline maximum utilization",
                    baseline.max_utilization_percent,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=2,
                    twin_version=base_version,
                ),
                values.number(
                    "simulation.comparison.scenario_util",
                    "Scenario maximum utilization",
                    scenario.max_utilization_percent,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=2,
                    twin_version=scenario_version,
                ),
                values.number(
                    "simulation.comparison.util_delta",
                    "Maximum utilization delta",
                    comparison.max_utilization_delta_percent,
                    step="simulation",
                    tool="simulation.scenarios.ScenarioComparison",
                    digits=2,
                    twin_version=scenario_version,
                ),
            ),
            (
                "Congested links",
                values.number(
                    "simulation.comparison.baseline_congested",
                    "Baseline congested links",
                    baseline.congested_link_count,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=base_version,
                ),
                values.number(
                    "simulation.comparison.scenario_congested",
                    "Scenario congested links",
                    scenario.congested_link_count,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=scenario_version,
                ),
                values.number(
                    "simulation.comparison.congested_delta",
                    "Congested link delta",
                    comparison.congested_link_delta,
                    step="simulation",
                    tool="simulation.scenarios.ScenarioComparison",
                    digits=0,
                    twin_version=scenario_version,
                ),
            ),
            (
                "Overloaded links",
                values.number(
                    "simulation.comparison.baseline_overloaded",
                    "Baseline overloaded links",
                    baseline.overloaded_link_count,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=base_version,
                ),
                values.number(
                    "simulation.comparison.scenario_overloaded",
                    "Scenario overloaded links",
                    scenario.overloaded_link_count,
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=scenario_version,
                ),
                values.number(
                    "simulation.comparison.overloaded_delta",
                    "Overloaded link delta",
                    comparison.overloaded_link_delta,
                    step="simulation",
                    tool="simulation.scenarios.ScenarioComparison",
                    digits=0,
                    twin_version=scenario_version,
                ),
            ),
            (
                "Disconnected devices",
                values.number(
                    "simulation.comparison.baseline_disconnected",
                    "Baseline disconnected devices",
                    len(baseline.disconnected_devices),
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=base_version,
                ),
                values.number(
                    "simulation.comparison.scenario_disconnected",
                    "Scenario disconnected devices",
                    len(scenario.disconnected_devices),
                    step="simulation",
                    tool="simulation.run_scenario",
                    digits=0,
                    twin_version=scenario_version,
                ),
                values.number(
                    "simulation.comparison.disconnected_delta",
                    "Disconnected device delta",
                    comparison.disconnected_device_delta,
                    step="simulation",
                    tool="simulation.scenarios.ScenarioComparison",
                    digits=0,
                    twin_version=scenario_version,
                ),
            ),
        ]
        comparison_table = self.table(
            "simulation_comparison",
            "Before and after",
            ("Metric", "Baseline", "Scenario", "Delta"),
            comparison_rows,
            step="simulation",
            tool="simulation.run_scenario",
            twin_version=scenario_version,
        )

        baseline_links = {link.link_id: link for link in baseline.links}
        scenario_links = {link.link_id: link for link in scenario.links}
        link_ids = sorted(set(baseline_links) | set(scenario_links))
        utilization_rows: list[tuple[str, ...]] = []
        for index, link_id in enumerate(link_ids[:MAX_REPORT_TABLE_ROWS]):
            base_link = baseline_links.get(link_id)
            scen_link = scenario_links.get(link_id)
            endpoints = (
                scen_link.endpoints if scen_link is not None else base_link.endpoints
            )
            utilization_rows.append(
                (
                    link_id,
                    " - ".join(endpoints),
                    values.number(
                        f"simulation.link.{index}.capacity",
                        f"Capacity of {link_id}",
                        (scen_link or base_link).capacity_mbps,
                        step="simulation",
                        tool="simulation.run_scenario",
                        unit="Mbps",
                        digits=2,
                        twin_version=scenario_version,
                    ),
                    values.number(
                        f"simulation.link.{index}.baseline_load",
                        f"Baseline load on {link_id}",
                        base_link.load_mbps,
                        step="simulation",
                        tool="simulation.run_scenario",
                        unit="Mbps",
                        digits=2,
                        twin_version=base_version,
                    )
                    if base_link is not None
                    else "n/a",
                    values.number(
                        f"simulation.link.{index}.baseline_util",
                        f"Baseline utilization of {link_id}",
                        base_link.utilization_percent,
                        step="simulation",
                        tool="simulation.run_scenario",
                        digits=2,
                        twin_version=base_version,
                    )
                    if base_link is not None
                    else "n/a",
                    values.number(
                        f"simulation.link.{index}.scenario_load",
                        f"Scenario load on {link_id}",
                        scen_link.load_mbps,
                        step="simulation",
                        tool="simulation.run_scenario",
                        unit="Mbps",
                        digits=2,
                        twin_version=scenario_version,
                    )
                    if scen_link is not None
                    else "n/a",
                    values.number(
                        f"simulation.link.{index}.scenario_util",
                        f"Scenario utilization of {link_id}",
                        scen_link.utilization_percent,
                        step="simulation",
                        tool="simulation.run_scenario",
                        digits=2,
                        twin_version=scenario_version,
                    )
                    if scen_link is not None
                    else "n/a",
                    scen_link.level.value if scen_link is not None else "n/a",
                )
            )
        utilization_table = self.table(
            "link_utilization",
            "Link utilization",
            (
                "Link",
                "Endpoints",
                "Capacity (Mbps)",
                "Baseline load (Mbps)",
                "Baseline utilization (%)",
                "Scenario load (Mbps)",
                "Scenario utilization (%)",
                "Scenario level",
            ),
            utilization_rows,
            step="simulation",
            tool="simulation.run_scenario",
            twin_version=scenario_version,
            total_rows=len(link_ids),
        )

        path_rows: list[tuple[str, ...]] = []
        for index, change in enumerate(comparison.path_changes):
            path_rows.append(
                (
                    change.name,
                    values.scan(
                        f"simulation.path_change.{index}.baseline",
                        f"Baseline path for {change.name}",
                        change.baseline_path,
                        step="simulation",
                        tool="simulation.scenarios.PathChange",
                        twin_version=base_version,
                    ),
                    values.scan(
                        f"simulation.path_change.{index}.scenario",
                        f"Scenario path for {change.name}",
                        change.scenario_path,
                        step="simulation",
                        tool="simulation.scenarios.PathChange",
                        twin_version=scenario_version,
                    ),
                )
            )
        path_table = self.table(
            "path_changes",
            "Path changes",
            ("Demand", "Baseline path", "Scenario path"),
            path_rows,
            step="simulation",
            tool="simulation.scenarios.ScenarioComparison",
            twin_version=scenario_version,
        )

        summary_note = NoteBlock(
            text=values.scan(
                "simulation.summary",
                "Comparison summary",
                comparison.summary,
                step="simulation",
                tool="simulation.scenarios.ScenarioComparison",
                twin_version=scenario_version,
            ),
            severity="info",
            provenance=self.prov(
                "simulation",
                "simulation.scenarios.ScenarioComparison",
                scenario_version,
            ),
        )
        model_note = NoteBlock(
            text=MODEL_NOTE,
            severity="limitation",
            provenance=self.prov("simulation", "simulation.models.MODEL_NOTE", base_version),
        )
        blocks: list[Any] = [
            paragraph,
            kv,
            comparison_table,
            utilization_table,
        ]
        if stale_note is not None:
            blocks.insert(0, stale_note)
        if path_rows:
            blocks.append(path_table)
        blocks.extend([summary_note, model_note])
        for index, warning in enumerate(run.warnings):
            blocks.append(
                NoteBlock(
                    text=values.scan(
                        f"simulation.warning.{index}",
                        "Simulation warning",
                        warning,
                        step="simulation",
                        tool="simulation.run_scenario",
                        twin_version=base_version,
                    ),
                    severity="warning",
                    provenance=self.prov(
                        "simulation", "simulation.run_scenario", base_version
                    ),
                )
            )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # 8. Capacity planning from modeled projections
    # ------------------------------------------------------------------
    def capacity(self) -> ReportSection:
        section_id = "capacity"
        title = "Capacity planning"
        run = self.capacity_run
        if run is None:
            return self.not_run(
                section_id,
                title,
                "No capacity analysis was selected. Run one on the Capacity Planning page.",
                "Capacity Planning",
            )

        values = self.numbers
        source_version = run.twin_fingerprint
        step_tool = "capacity.engine.evaluate_capacity"
        stale_note = self.stale_source_note(
            "capacity",
            "capacity",
            source_version,
            step="capacity",
            tool=step_tool,
        )
        data_labels = sorted(
            {demand.data_label for demand in run.projection.demands}
        )
        model_names = sorted({demand.model.value for demand in run.projection.demands})
        data_label = values.text(
            "capacity.data_label",
            "Forecast data label",
            ", ".join(data_labels) or "none",
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        model_text = values.text(
            "capacity.model",
            "Selected forecast models",
            ", ".join(model_names) or "none",
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        source_fingerprint = values.text(
            "capacity.source_fingerprint",
            "Capacity source twin fingerprint",
            source_version,
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        stop_reason = values.text(
            "capacity.stop_reason",
            "Capacity run stop reason",
            run.bounds.stop_reason.value,
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        projected_steps = values.number(
            "capacity.projected_steps",
            "Projected steps evaluated",
            len(run.steps),
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
            digits=0,
        )
        mapped_demands = values.number(
            "capacity.mapped_demands",
            "Mapped demands projected",
            len(run.projection.demands),
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
            digits=0,
        )
        baseline_utilization = max(
            (load.utilization_percent for load in run.baseline.links), default=0.0
        )
        horizon_links = run.steps[-1].state.links if run.steps else run.baseline.links
        horizon_utilization = max(
            (load.utilization_percent for load in horizon_links), default=0.0
        )
        baseline_text = values.number(
            "capacity.baseline_max_utilization",
            "Baseline maximum modeled utilization",
            baseline_utilization,
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        horizon_text = values.number(
            "capacity.horizon_max_utilization",
            "Horizon-end maximum modeled utilization",
            horizon_utilization,
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        crossing_text = values.number(
            "capacity.crossing_count",
            "Congestion-band crossings",
            len(run.crossings),
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
            digits=0,
        )
        bottleneck_text = values.number(
            "capacity.bottleneck_count",
            "Ranked bottlenecks",
            len(run.bottlenecks),
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
            digits=0,
        )
        recommendation_text = values.number(
            "capacity.recommendation_count",
            "Tier upgrade recommendations",
            len(run.recommendations),
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
            digits=0,
        )
        gap_text = values.number(
            "capacity.gap_count",
            "Capacity gaps without a sufficient tier",
            len(run.gaps),
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
            digits=0,
        )
        cost_text = values.number(
            "capacity.cost_delta",
            "Total modeled upgrade cost delta",
            run.total_cost_delta,
            step="capacity",
            tool=step_tool,
            twin_version=source_version,
        )
        summary = (
            f"Capacity planning evaluated {projected_steps} projected steps from "
            f"{mapped_demands} mapped demands using {data_label} data and "
            f"{model_text} forecasts. Baseline maximum modeled utilization was "
            f"{baseline_text} percent and the horizon-end maximum was "
            f"{horizon_text} percent. The run recorded {crossing_text} "
            f"congestion-band crossings, {bottleneck_text} ranked bottlenecks, "
            f"{recommendation_text} tier upgrades totaling {cost_text} modeled "
            f"cost units, and {gap_text} gaps without a sufficient tier. The run "
            f"stopped because of {stop_reason}."
        )
        blocks: list[Any] = [stale_note] if stale_note is not None else []
        blocks.extend(
            [
                ParagraphBlock(
                    text=summary,
                    provenance=self.prov("capacity", step_tool, source_version),
                ),
                KeyValueBlock(
                    title="Capacity source and scope",
                    items=(
                        KeyValueItem(
                            key="twin_fingerprint",
                            value=source_fingerprint,
                            provenance=self.prov("capacity", step_tool, source_version),
                        ),
                        KeyValueItem(
                            key="data_label",
                            value=data_label,
                            provenance=self.prov("capacity", step_tool, source_version),
                        ),
                        KeyValueItem(
                            key="forecast_models",
                            value=model_text,
                            provenance=self.prov("capacity", step_tool, source_version),
                        ),
                        KeyValueItem(
                            key="stop_reason",
                            value=stop_reason,
                            provenance=self.prov("capacity", step_tool, source_version),
                        ),
                    ),
                ),
                NoteBlock(
                    text=run.note,
                    severity="info",
                    provenance=self.prov("capacity", step_tool, source_version),
                ),
                NoteBlock(
                    text=run.method_note,
                    severity="limitation",
                    provenance=self.prov("capacity", step_tool, source_version),
                ),
            ]
        )

        bottleneck_rows: list[tuple[str, ...]] = []
        for index, item in enumerate(run.bottlenecks):
            peak = values.number(
                f"capacity.bottleneck.{index}.peak",
                f"Peak utilization on {item.link_id}",
                item.peak_utilization_percent,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
            headroom = values.number(
                f"capacity.bottleneck.{index}.headroom",
                f"Horizon-end headroom on {item.link_id}",
                item.headroom_mbps,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
            levels = ", ".join(sorted({crossing.level.value for crossing in item.crossings}))
            bottleneck_rows.append(
                (
                    item.link_id,
                    "-".join(item.endpoints),
                    peak,
                    headroom,
                    levels or "none",
                )
            )
        blocks.append(
            self.table(
                "capacity_bottlenecks",
                "Ranked projected bottlenecks",
                ("Link", "Endpoints", "Peak utilization (%)", "Horizon headroom (Mbps)", "Bands crossed"),
                bottleneck_rows,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
        )

        recommendation_rows: list[tuple[str, ...]] = []
        for index, item in enumerate(run.recommendations):
            target = values.number(
                f"capacity.recommendation.{index}.target",
                f"Recommended tier capacity on {item.link_id}",
                item.target_capacity_mbps,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
            projected = values.number(
                f"capacity.recommendation.{index}.utilization",
                f"Projected utilization after upgrade on {item.link_id}",
                item.projected_utilization_percent,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
            delta = values.number(
                f"capacity.recommendation.{index}.cost",
                f"Modeled cost delta on {item.link_id}",
                item.cost_delta,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
            recommendation_rows.append(
                (item.link_id, target, projected, delta, item.cost_unit)
            )
        blocks.append(
            self.table(
                "capacity_upgrades",
                "Smallest tier upgrades that clear the warning threshold",
                ("Link", "Tier capacity (Mbps)", "Projected utilization (%)", "Cost delta", "Cost unit"),
                recommendation_rows,
                step="capacity",
                tool=step_tool,
                twin_version=source_version,
            )
        )

        if run.gaps:
            gap_rows: list[tuple[str, ...]] = []
            for index, item in enumerate(run.gaps):
                required = values.number(
                    f"capacity.gap.{index}.required",
                    f"Required capacity on {item.link_id}",
                    item.required_capacity_mbps,
                    step="capacity",
                    tool=step_tool,
                    twin_version=source_version,
                )
                largest = values.number(
                    f"capacity.gap.{index}.largest",
                    f"Largest configured tier on {item.link_id}",
                    item.largest_available_capacity_mbps,
                    step="capacity",
                    tool=step_tool,
                    twin_version=source_version,
                )
                gap_rows.append((item.link_id, required, largest, item.note))
            blocks.append(
                self.table(
                    "capacity_gaps",
                    "Gaps referred to the Optimization Center",
                    ("Link", "Required capacity (Mbps)", "Largest tier (Mbps)", "Note"),
                    gap_rows,
                    step="capacity",
                    tool=step_tool,
                    twin_version=source_version,
                )
            )

        if run.projection.findings:
            for index, finding in enumerate(run.projection.findings):
                blocks.append(
                    NoteBlock(
                        text=values.scan(
                            f"capacity.finding.{index}",
                            "Capacity planning finding",
                            finding.message,
                            step="capacity",
                            tool="capacity.demand.project_demands",
                            twin_version=source_version,
                        ),
                        severity="warning",
                        provenance=self.prov(
                            "capacity", "capacity.demand.project_demands", source_version
                        ),
                    )
                )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # 9. Optimization against baseline
    # ------------------------------------------------------------------
    def optimization(self) -> ReportSection:
        section_id = "optimization"
        title = "Optimization against baseline"
        run = self.optimization_run
        if run is None:
            return self.not_run(
                section_id,
                title,
                "No optimization run is selected for this report.",
                "Optimization Center",
            )
        values = self.numbers
        source_version = self.optimization_source_fingerprint or ""
        stale_note = self.stale_source_note(
            "optimization",
            "optimization",
            source_version,
            step="optimization",
            tool="optimization.run_optimization",
        )
        best = run.best
        algorithm = values.text(
            "optimization.algorithm",
            "Algorithm",
            run.algorithm.value,
            step="optimization",
            tool="optimization.run_optimization",
        )
        seed = values.number(
            "optimization.seed",
            "Seed",
            run.seed,
            step="optimization",
            tool="optimization.run_optimization",
            digits=0,
        )
        evaluations = values.number(
            "optimization.evaluations",
            "Candidate evaluations",
            run.evaluations,
            step="optimization",
            tool="optimization.run_optimization",
            digits=0,
        )
        cache_hits = values.number(
            "optimization.cache_hits",
            "Cache hits",
            run.cache_hits,
            step="optimization",
            tool="optimization.run_optimization",
            digits=0,
        )
        candidate_count = values.number(
            "optimization.candidate_count",
            "Retained candidates",
            len(run.candidates),
            step="optimization",
            tool="optimization.run_optimization",
            digits=0,
        )
        pareto_count = values.number(
            "optimization.pareto_count",
            "Pareto front candidates",
            len(run.pareto_front),
            step="optimization",
            tool="optimization.run_optimization",
            digits=0,
        )
        stop_reason = values.text(
            "optimization.stop_reason",
            "Stop reason",
            run.stop_reason.value,
            step="optimization",
            tool="optimization.run_optimization",
        )
        best_score = (
            values.number(
                "optimization.best_score",
                "Best weighted score",
                best.evaluation.weighted_score,
                step="optimization",
                tool="optimization.run_optimization",
                digits=3,
            )
            if best is not None
            else "n/a"
        )
        paragraph = ParagraphBlock(
            text=templates.optimization_summary(
                algorithm=algorithm,
                seed=seed,
                evaluations=evaluations,
                best_available=best is not None,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Run",
            items=(
                KeyValueItem(
                    key="algorithm",
                    value=algorithm,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="seed",
                    value=seed,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="evaluations",
                    value=evaluations,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="cache_hits",
                    value=cache_hits,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="candidates",
                    value=candidate_count,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="pareto",
                    value=pareto_count,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="stop_reason",
                    value=stop_reason,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
                KeyValueItem(
                    key="best_score",
                    value=best_score,
                    provenance=self.prov("optimization", "optimization.run_optimization"),
                ),
            ),
        )
        settings_rows = [
            (
                "Population size",
                values.number(
                    "optimization.settings.population",
                    "Population size",
                    run.settings.population_size,
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                    digits=0,
                ),
            ),
            (
                "Maximum iterations",
                values.number(
                    "optimization.settings.max_iterations",
                    "Maximum iterations",
                    run.settings.max_iterations,
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                    digits=0,
                ),
            ),
            (
                "Maximum evaluations",
                values.number(
                    "optimization.settings.max_evaluations",
                    "Maximum evaluations",
                    run.settings.max_evaluations,
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                    digits=0,
                ),
            ),
            (
                "Maximum runtime (s)",
                values.number(
                    "optimization.settings.max_runtime",
                    "Maximum runtime seconds",
                    run.settings.max_runtime_seconds,
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                    digits=2,
                ),
            ),
            (
                "Objectives",
                values.number(
                    "optimization.settings.objectives",
                    "Objective count",
                    len(run.settings.objectives),
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                    digits=0,
                ),
            ),
            (
                "Candidate pool links",
                values.number(
                    "optimization.settings.candidate_pool",
                    "Candidate pool size",
                    len(run.settings.candidate_pool),
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                    digits=0,
                ),
            ),
            (
                "Cost multipliers",
                values.scan(
                    "optimization.settings.cost_multipliers",
                    "Cost multiplier options",
                    ", ".join(
                        format_number(option)
                        for option in run.settings.cost_multiplier_options
                    )
                    or "none",
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                ),
            ),
        ]
        settings_table = self.table(
            "optimization_settings",
            "Configured settings",
            ("Setting", "Value"),
            settings_rows,
            step="optimization",
            tool="optimization.models.OptimizationSettings",
        )

        metrics_specs = (
            ("Device count", "device_count", 0),
            ("Link count", "link_count", 0),
            ("Served demands", "served_demand_count", 0),
            ("Served demand ratio", "served_demand_ratio", 3),
            ("Maximum utilization (%)", "max_utilization_percent", 2),
            ("Congested links", "congested_link_count", 0),
            ("Overloaded links", "overloaded_link_count", 0),
            ("Disconnected devices", "disconnected_device_count", 0),
            ("Infrastructure cost proxy", "infrastructure_cost_proxy", 2),
            ("Single points of failure", "spof_count", 0),
        )
        comparison_rows: list[tuple[str, ...]] = []
        for index, (label, attribute, digits) in enumerate(metrics_specs):
            baseline_value = getattr(run.baseline.metrics, attribute)
            best_value = (
                getattr(best.evaluation.metrics, attribute)
                if best is not None
                else None
            )
            baseline_display = (
                values.number(
                    f"optimization.compare.{index}.baseline",
                    f"Baseline {label}",
                    baseline_value,
                    step="optimization",
                    tool="optimization.models.CandidateMetrics",
                    digits=digits,
                )
                if baseline_value is not None
                else "n/a"
            )
            best_display = (
                values.number(
                    f"optimization.compare.{index}.best",
                    f"Best {label}",
                    best_value,
                    step="optimization",
                    tool="optimization.models.CandidateMetrics",
                    digits=digits,
                )
                if best_value is not None
                else "n/a"
            )
            delta_display = (
                values.number(
                    f"optimization.compare.{index}.delta",
                    f"{label} delta",
                    best_value - baseline_value,
                    step="optimization",
                    tool="optimization.models.CandidateMetrics",
                    digits=digits,
                )
                if best_value is not None and baseline_value is not None
                else "n/a"
            )
            comparison_rows.append(
                (label, baseline_display, best_display, delta_display)
            )
        comparison_rows.append(
            (
                "Weighted score",
                values.number(
                    "optimization.compare.score.baseline",
                    "Baseline weighted score",
                    run.baseline.weighted_score,
                    step="optimization",
                    tool="optimization.models.CandidateEvaluation",
                    digits=3,
                ),
                values.number(
                    "optimization.compare.score.best",
                    "Best weighted score",
                    best.evaluation.weighted_score,
                    step="optimization",
                    tool="optimization.models.CandidateEvaluation",
                    digits=3,
                )
                if best is not None
                else "n/a",
                values.number(
                    "optimization.compare.score.delta",
                    "Weighted score delta",
                    best.evaluation.weighted_score - run.baseline.weighted_score,
                    step="optimization",
                    tool="optimization.models.CandidateEvaluation",
                    digits=3,
                )
                if best is not None
                else "n/a",
            )
        )
        comparison_table = self.table(
            "optimization_comparison",
            "Baseline versus best candidate",
            ("Metric", "Baseline", "Best", "Delta"),
            comparison_rows,
            step="optimization",
            tool="optimization.run_optimization",
        )

        candidate_rows: list[tuple[str, ...]] = []
        for index, record in enumerate(run.candidates[:MAX_REPORT_TABLE_ROWS]):
            evaluation = record.evaluation
            candidate_rows.append(
                (
                    values.number(
                        f"optimization.candidate.{index}.rank",
                        "Candidate rank",
                        record.rank if record.rank is not None else index + 1,
                        step="optimization",
                        tool="optimization.run_optimization",
                        digits=0,
                    ),
                    evaluation.candidate_hash[:12],
                    ", ".join(evaluation.candidate.selected_link_ids) or "-",
                    "yes" if evaluation.feasible else "no",
                    values.number(
                        f"optimization.candidate.{index}.score",
                        "Candidate weighted score",
                        evaluation.weighted_score,
                        step="optimization",
                        tool="optimization.models.CandidateEvaluation",
                        digits=3,
                    ),
                    values.number(
                        f"optimization.candidate.{index}.util",
                        "Candidate maximum utilization",
                        evaluation.metrics.max_utilization_percent,
                        step="optimization",
                        tool="optimization.models.CandidateMetrics",
                        digits=2,
                    ),
                    values.number(
                        f"optimization.candidate.{index}.cost",
                        "Candidate infrastructure cost proxy",
                        evaluation.metrics.infrastructure_cost_proxy,
                        step="optimization",
                        tool="optimization.models.CandidateMetrics",
                        digits=2,
                    ),
                )
            )
        candidate_table = self.table(
            "optimization_candidates",
            "Optimization candidates",
            (
                "Rank",
                "Hash",
                "Selected links",
                "Feasible",
                "Weighted score",
                "Max utilization (%)",
                "Infrastructure cost proxy",
            ),
            candidate_rows,
            step="optimization",
            tool="optimization.run_optimization",
            total_rows=len(run.candidates),
        )

        blocks: list[Any] = [paragraph, kv, settings_table, comparison_table]
        if stale_note is not None:
            blocks.insert(0, stale_note)
        if candidate_rows:
            blocks.append(candidate_table)
        blocks.append(
            NoteBlock(
                text=values.scan(
                    "optimization.search_note",
                    "Search note",
                    run.search_note,
                    step="optimization",
                    tool="optimization.models.SEARCH_NOTE",
                ),
                severity="limitation",
                provenance=self.prov("optimization", "optimization.models.SEARCH_NOTE"),
            )
        )
        blocks.append(
            NoteBlock(
                text=values.scan(
                    "optimization.cost_note",
                    "Cost note",
                    run.cost_note,
                    step="optimization",
                    tool="optimization.models.COST_NOTE",
                ),
                severity="limitation",
                provenance=self.prov("optimization", "optimization.models.COST_NOTE"),
            )
        )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # 9. Assumptions
    # ------------------------------------------------------------------
    def assumptions(self) -> ReportSection:
        section_id = "assumptions"
        title = "Assumptions"
        values = self.numbers
        recorded = list(self.twin.assumptions)
        assumption_entries = (
            len(recorded)
            + (1 if self.scenario_run is not None else 0)
            + (1 if self.optimization_run is not None else 0)
        )
        count = values.number(
            "assumptions.count",
            "Recorded assumption entries",
            assumption_entries,
            step="requirements",
            tool="core.schemas.requirements.Assumption",
            digits=0,
        )
        blocks: list[Any] = [
            ParagraphBlock(
                text=templates.assumptions_summary(count=count),
                provenance=self.prov("report", "services.reporting.templates"),
            )
        ]
        if recorded:
            rows: list[tuple[str, ...]] = []
            for index, assumption in enumerate(recorded):
                rows.append(
                    (
                        assumption.category,
                        values.scan(
                            f"assumptions.{index}.description",
                            "Assumption description",
                            assumption.description,
                            step="requirements",
                            tool="core.schemas.requirements.Assumption",
                        ),
                        values.scan(
                            f"assumptions.{index}.rationale",
                            "Assumption rationale",
                            assumption.rationale or "-",
                            step="requirements",
                            tool="core.schemas.requirements.Assumption",
                        ),
                        assumption.id,
                    )
                )
            blocks.append(
                self.table(
                    "twin_assumptions",
                    "Assumptions stored in the twin",
                    ("Category", "Description", "Rationale", "Id"),
                    rows,
                    step="requirements",
                    tool="core.schemas.requirements.Assumption",
                )
            )
        else:
            blocks.append(
                NoteBlock(
                    text="No assumptions are recorded in the twin.",
                    severity="info",
                    provenance=self.prov(
                        "requirements", "core.schemas.requirements.Assumption"
                    ),
                )
            )
        if self.scenario_run is not None:
            assumptions = self.scenario_run.assumptions
            version = self.scenario_run.baseline_twin.fingerprint
            rows = [
                (
                    "Warning threshold (%)",
                    values.number(
                        "assumptions.simulation.warning",
                        "Simulation warning threshold",
                        assumptions.thresholds.warning_percent,
                        step="simulation",
                        tool="simulation.models.CongestionThresholds",
                        digits=2,
                        twin_version=version,
                    ),
                ),
                (
                    "Critical threshold (%)",
                    values.number(
                        "assumptions.simulation.critical",
                        "Simulation critical threshold",
                        assumptions.thresholds.critical_percent,
                        step="simulation",
                        tool="simulation.models.CongestionThresholds",
                        digits=2,
                        twin_version=version,
                    ),
                ),
                (
                    "Overload threshold (%)",
                    values.number(
                        "assumptions.simulation.overload",
                        "Simulation overload threshold",
                        assumptions.thresholds.overload_percent,
                        step="simulation",
                        tool="simulation.models.CongestionThresholds",
                        digits=2,
                        twin_version=version,
                    ),
                ),
                (
                    "Links with delay assumptions",
                    values.number(
                        "assumptions.simulation.delay_links",
                        "Links with delay assumptions",
                        len(assumptions.link_delay_ms),
                        step="simulation",
                        tool="simulation.models.SimulationAssumptions",
                        digits=0,
                        twin_version=version,
                    ),
                ),
            ]
            blocks.append(
                self.table(
                    "simulation_assumptions",
                    "Simulation assumptions (selected run)",
                    ("Setting", "Value"),
                    rows,
                    step="simulation",
                    tool="simulation.models.SimulationAssumptions",
                    twin_version=version,
                )
            )
        if self.optimization_run is not None:
            run = self.optimization_run
            assumptions = run.settings.assumptions
            rows = [
                (
                    "Seed",
                    values.number(
                        "assumptions.optimization.seed",
                        "Optimization seed",
                        run.seed,
                        step="optimization",
                        tool="optimization.models.OptimizationSettings",
                        digits=0,
                    ),
                ),
                (
                    "Warning threshold (%)",
                    values.number(
                        "assumptions.optimization.warning",
                        "Optimization warning threshold",
                        assumptions.thresholds.warning_percent,
                        step="optimization",
                        tool="optimization.models.OptimizationSettings",
                        digits=2,
                    ),
                ),
                (
                    "Critical threshold (%)",
                    values.number(
                        "assumptions.optimization.critical",
                        "Optimization critical threshold",
                        assumptions.thresholds.critical_percent,
                        step="optimization",
                        tool="optimization.models.OptimizationSettings",
                        digits=2,
                    ),
                ),
                (
                    "Cost model",
                    values.scan(
                        "assumptions.optimization.cost_note",
                        "Cost model note",
                        run.settings.cost_model.note,
                        step="optimization",
                        tool="optimization.models.CostModel",
                    ),
                ),
            ]
            blocks.append(
                self.table(
                    "optimization_assumptions",
                    "Optimization assumptions (selected run)",
                    ("Setting", "Value"),
                    rows,
                    step="optimization",
                    tool="optimization.models.OptimizationSettings",
                )
            )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # 10. Limitations
    # ------------------------------------------------------------------
    def limitations(self) -> ReportSection:
        blocks = tuple(
            ParagraphBlock(
                text=text,
                provenance=self.prov("report", "services.reporting.templates"),
            )
            for text in templates.LIMITATIONS
        )
        return ReportSection(id="limitations", title="Limitations", blocks=blocks)

    # ------------------------------------------------------------------
    # 11. Agent execution trace
    # ------------------------------------------------------------------
    def agent_trace(self) -> ReportSection:
        section_id = "agent_trace"
        title = "Agent execution trace"
        workflow = self.workflow
        if workflow is None:
            return self.not_run(
                section_id,
                title,
                "No agent workflow is attached to this report.",
                "AI Network Designer",
            )
        ordered = workflow.ordered_task_ids()
        if not ordered:
            return self.not_run(
                section_id,
                title,
                "The attached workflow contains no tasks.",
                "AI Network Designer",
            )
        values = self.numbers
        stop_reason = (
            workflow.stop_reason.value
            if workflow.stop_reason is not None
            else "not recorded"
        )
        steps = values.number(
            "agent.steps",
            "Workflow steps",
            workflow.steps,
            step="workflow",
            tool="agents.models.WorkflowState",
            digits=0,
        )
        replans = values.number(
            "agent.replans",
            "Workflow re-plans",
            workflow.replans,
            step="workflow",
            tool="agents.models.WorkflowState",
            digits=0,
        )
        task_count = values.number(
            "agent.task_count",
            "Workflow tasks",
            len(ordered),
            step="workflow",
            tool="agents.models.WorkflowState",
            digits=0,
        )
        trace_count = values.number(
            "agent.trace_count",
            "Trace events",
            len(workflow.trace.entries),
            step="workflow",
            tool="agents.models.ExecutionTrace",
            digits=0,
        )
        paragraph = ParagraphBlock(
            text=templates.trace_summary(
                task_count=task_count,
                trace_count=trace_count,
                stop_reason=stop_reason,
            ),
            provenance=self.prov("report", "services.reporting.templates"),
        )
        kv = KeyValueBlock(
            title="Workflow",
            items=(
                KeyValueItem(
                    key="plan",
                    value=workflow.plan.name,
                    provenance=self.prov("workflow", "agents.models.WorkflowPlan"),
                ),
                KeyValueItem(
                    key="stop_reason",
                    value=stop_reason,
                    provenance=self.prov("workflow", "agents.models.WorkflowState"),
                ),
                KeyValueItem(
                    key="steps",
                    value=steps,
                    provenance=self.prov("workflow", "agents.models.WorkflowState"),
                ),
                KeyValueItem(
                    key="replans",
                    value=replans,
                    provenance=self.prov("workflow", "agents.models.WorkflowState"),
                ),
                KeyValueItem(
                    key="tasks",
                    value=task_count,
                    provenance=self.prov("workflow", "agents.models.WorkflowState"),
                ),
            ),
        )
        task_rows: list[tuple[str, ...]] = []
        for index, task_id in enumerate(ordered):
            task = workflow.tasks[task_id]
            definition = workflow.plan.task(task_id)
            task_rows.append(
                (
                    task_id,
                    definition.agent,
                    task.status.value,
                    values.number(
                        f"agent.task.{index}.attempts",
                        f"Attempts for task {task_id}",
                        task.attempts,
                        step="workflow",
                        tool="agents.models.TaskState",
                        digits=0,
                    ),
                    values.number(
                        f"agent.task.{index}.replans",
                        f"Re-plans for task {task_id}",
                        task.replans,
                        step="workflow",
                        tool="agents.models.TaskState",
                        digits=0,
                    ),
                    ", ".join(definition.dependencies) or "-",
                    values.scan(
                        f"agent.task.{index}.skipped",
                        "Skipped reason",
                        task.skipped_reason or "-",
                        step="workflow",
                        tool="agents.models.TaskState",
                    ),
                    values.scan(
                        f"agent.task.{index}.error",
                        "Task error",
                        task.error or "-",
                        step="workflow",
                        tool="agents.models.TaskState",
                    ),
                )
            )
        task_table = self.table(
            "workflow_tasks",
            "Workflow tasks",
            (
                "Task",
                "Agent",
                "Status",
                "Attempts",
                "Re-plans",
                "Dependencies",
                "Skipped reason",
                "Error",
            ),
            task_rows,
            step="workflow",
            tool="agents.models.WorkflowState",
        )

        trace_rows: list[tuple[str, ...]] = []
        for index, entry in enumerate(workflow.trace.entries):
            trace_rows.append(
                (
                    values.number(
                        f"agent.trace.{index}.step",
                        "Trace step",
                        entry.step,
                        step="workflow",
                        tool="agents.models.TraceEntry",
                        digits=0,
                    ),
                    entry.agent,
                    entry.task_id,
                    entry.action,
                    entry.status,
                    entry.tool or "-",
                    values.number(
                        f"agent.trace.{index}.attempt",
                        "Trace attempt",
                        entry.attempt,
                        step="workflow",
                        tool="agents.models.TraceEntry",
                        digits=0,
                    ),
                    values.number(
                        f"agent.trace.{index}.duration",
                        "Trace duration seconds",
                        entry.duration_seconds,
                        step="workflow",
                        tool="agents.models.TraceEntry",
                        digits=3,
                    ),
                )
            )
        trace_table = self.table(
            "execution_trace",
            "Execution trace",
            (
                "Step",
                "Agent",
                "Task",
                "Action",
                "Status",
                "Tool",
                "Attempt",
                "Duration (s)",
            ),
            trace_rows,
            step="workflow",
            tool="agents.models.ExecutionTrace",
        )
        blocks: list[Any] = [paragraph, kv, task_table, trace_table]
        if workflow.error:
            blocks.append(
                NoteBlock(
                    text=values.scan(
                        "agent.error",
                        "Workflow error",
                        workflow.error,
                        step="workflow",
                        tool="agents.models.WorkflowState",
                    ),
                    severity="warning",
                    provenance=self.prov("workflow", "agents.models.WorkflowState"),
                )
            )
        return ReportSection(id=section_id, title=title, blocks=tuple(blocks))

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    def build(self, *, title: str, generated_at: datetime) -> ReportDocument:
        sections = (
            self.architecture_summary(),
            self.topology(),
            self.addressing(),
            self.vlan_dhcp(),
            self.routing(),
            self.graph_analysis(),
            self.simulation(),
            self.capacity(),
            self.optimization(),
            self.assumptions(),
            self.limitations(),
            self.agent_trace(),
        )
        return ReportDocument(
            schema_version=REPORT_SCHEMA_VERSION,
            title=title,
            subtitle=(
                "Generated from validated application data. "
                "No value is taken from free-form model prose."
            ),
            generated_at=generated_at,
            twin=ReportTwin(
                name=self.twin.metadata.name,
                created_at=self.twin.metadata.created_at,
                schema_version=self.twin.metadata.schema_version,
                fingerprint=self.fingerprint,
            ),
            sections=sections,
            values=tuple(self.numbers.records.values()),
        )


def build_report(sources: ReportSources) -> ReportDocument:
    """Build one report document from validated inputs."""
    reference = twin_reference(sources.twin)
    generated_at = sources.generated_at or datetime.now(UTC)
    title = sources.title or f"{REPORT_TITLE_PREFIX} - {sources.twin.metadata.name}"
    builder = _Builder(sources, reference.fingerprint)
    return builder.build(title=title, generated_at=generated_at)


def filter_sections(
    document: ReportDocument,
    section_ids: tuple[str, ...] | list[str] | None,
) -> ReportDocument:
    """Return a copy containing only the requested sections, in document order."""
    if section_ids is None:
        return document
    selected = set(section_ids)
    sections = tuple(
        section for section in document.sections if section.id in selected
    )
    return document.model_copy(update={"sections": sections})


__all__ = [
    "REPORT_TITLE_PREFIX",
    "ReportSources",
    "build_report",
    "filter_sections",
]
