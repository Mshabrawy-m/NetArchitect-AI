"""Deterministic, design-only analysis of the modeled WAN.

The WAN package reads designer-supplied site facts and optional WAN attributes
on topology links. It never talks to a device, runs a protocol, or measures a
circuit. Costs and latencies are explicit modeling assumptions, and every
finding is derived only from the digital twin (plus an optional, explicitly
supplied design or evaluation result).

Cheap checks use the active inter-site WAN links directly. The capacity-aware
check is opt-in because it runs the existing flow evaluator.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.schemas.enums import OperationalState
from core.schemas.network import Device, DeviceRole, Link
from core.schemas.validation import Finding, Severity

from .models import SiteType, WanDesign, WanLinkType

if TYPE_CHECKING:
    from digital_twin.models import DigitalTwin

MONTHLY_COST_NOTE = (
    "Modeled monthly cost proxy; not a vendor quote or measured charge."
)
LATENCY_NOTE = "Assumed one-way latency from the modeled WAN design, not a measurement."


@dataclass(frozen=True)
class WanLinkInfo:
    """One active inter-site link carrying modeled WAN design attributes."""

    link_id: str
    source_site: str
    target_site: str
    wan_type: WanLinkType | None
    capacity_mbps: float
    monthly_cost_proxy: float
    latency_ms: float
    srg_tag: str | None


@dataclass(frozen=True)
class WanAnalysis:
    """Findings and normalized WAN link facts for one twin revision."""

    findings: tuple[Finding, ...]
    links: tuple[WanLinkInfo, ...]
    total_monthly_cost_proxy: float
    site_ids: tuple[str, ...]
    evaluated_demand_count: int


def _device_index(twin: DigitalTwin) -> dict[str, Device]:
    return {device.id: device for device in twin.topology.devices}


def _wan_marked(link: Link, roles: set[DeviceRole]) -> bool:
    """Whether a link is intentionally part of the modeled WAN design."""
    return bool(
        link.wan_type is not None
        or link.wan_srg_tag is not None
        or link.wan_capacity_mbps is not None
        or link.wan_monthly_cost_proxy is not None
        or link.wan_latency_ms is not None
        or DeviceRole.wan in roles
        or DeviceRole.border in roles
    )


def inter_site_wan_links(twin: DigitalTwin) -> tuple[WanLinkInfo, ...]:
    """Return active inter-site links that carry modeled WAN intent.

    A link qualifies when its endpoints are in different sites and it has any
    WAN attribute or a ``wan``/``border`` endpoint role. Links explicitly
    modeled as ``down`` in ``twin.link_states`` are excluded. The result is
    sorted by link id so it never depends on topology list order.
    """
    devices = _device_index(twin)
    down_links = {
        state.link_id
        for state in twin.link_states
        if state.state is OperationalState.down
    }
    infos: list[WanLinkInfo] = []
    for link in twin.topology.links:
        if link.id in down_links:
            continue
        first = devices.get(link.endpoints[0])
        second = devices.get(link.endpoints[1])
        if first is None or second is None:
            continue
        if first.site == second.site:
            continue
        if not _wan_marked(link, {first.role, second.role}):
            continue
        infos.append(
            WanLinkInfo(
                link_id=link.id,
                source_site=first.site,
                target_site=second.site,
                wan_type=link.wan_type,
                capacity_mbps=float(link.wan_capacity_mbps or link.capacity_mbps),
                monthly_cost_proxy=float(link.wan_monthly_cost_proxy or 0.0),
                latency_ms=float(link.wan_latency_ms or 0.0),
                srg_tag=link.wan_srg_tag,
            )
        )
    return tuple(sorted(infos, key=lambda info: info.link_id))


def wan_cost_proxy_total(twin: DigitalTwin) -> float:
    """Sum the modeled monthly cost proxies of active inter-site WAN links."""
    return float(
        sum(info.monthly_cost_proxy for info in inter_site_wan_links(twin))
    )


def _infer_site_type(site_id: str, roles: set[DeviceRole]) -> SiteType:
    """Infer a conservative design type from site id and device roles only."""
    lowered = site_id.lower()
    if roles & {DeviceRole.core, DeviceRole.border} and (
        "hq" in lowered or "dc" in lowered
    ):
        return SiteType.hq if "hq" in lowered else SiteType.dc
    if "cloud" in lowered:
        return SiteType.cloud
    return SiteType.branch


def _site_types(twin: DigitalTwin, design: WanDesign | None) -> dict[str, SiteType]:
    """Resolve modeled site types, preferring designer-supplied facts."""
    roles_by_site: dict[str, set[DeviceRole]] = defaultdict(set)
    for device in twin.topology.devices:
        roles_by_site[device.site].add(device.role)
    types: dict[str, SiteType] = {}
    for site_id in sorted(roles_by_site):
        explicit = design.site_types.get(site_id) if design is not None else None
        types[site_id] = explicit or _infer_site_type(site_id, roles_by_site[site_id])
    return types


def _hq_dc_targets(
    types: dict[str, SiteType],
    design: WanDesign | None,
) -> frozenset[str]:
    """Modeled sites that branches are expected to reach."""
    targets = {
        site_id
        for site_id, site_type in types.items()
        if site_type in {SiteType.hq, SiteType.dc}
    }
    if design is not None:
        targets.update(design.hq_site_ids)
    return frozenset(targets)


def _cheap_findings(
    links: tuple[WanLinkInfo, ...],
    types: dict[str, SiteType],
    targets: frozenset[str],
    total: float,
) -> tuple[Finding, ...]:
    """Build the always-on structural and cost findings."""
    link_ids_by_site: dict[str, set[str]] = defaultdict(set)
    srg_by_link = {info.link_id: info.srg_tag for info in links}
    for info in links:
        link_ids_by_site[info.source_site].add(info.link_id)
        link_ids_by_site[info.target_site].add(info.link_id)

    findings: list[Finding] = []
    for site_id in sorted(link_ids_by_site):
        link_ids = sorted(link_ids_by_site[site_id])
        if len(link_ids) == 1:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="wan_site_single_link_spof",
                    affected_entities=sorted([site_id, *link_ids]),
                    explanation=(
                        f"Modeled site {site_id} has exactly one active "
                        "inter-site WAN link; that link is a single point of "
                        f"failure in the modeled WAN: {', '.join(link_ids)}."
                    ),
                    remediation=(
                        "Add a second modeled inter-site WAN link through an "
                        "independent shared-risk group."
                    ),
                )
            )
        if len(link_ids) >= 2:
            tags = {
                tag
                for link_id in link_ids
                if (tag := srg_by_link.get(link_id))
            }
            if len(tags) == 1:
                tag = next(iter(tags))
                findings.append(
                    Finding(
                        severity=Severity.error,
                        code="wan_site_links_same_srg",
                        affected_entities=sorted([site_id, *link_ids]),
                        explanation=(
                            f"All {len(link_ids)} modeled inter-site WAN links "
                            f"at site {site_id} share non-empty shared-risk "
                            f"group {tag!r}: {', '.join(link_ids)}."
                        ),
                        remediation=(
                            "Model at least one WAN link in a different "
                            "shared-risk group."
                        ),
                    )
                )

    if targets:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for info in links:
            adjacency[info.source_site].add(info.target_site)
            adjacency[info.target_site].add(info.source_site)
        for site_id in sorted(
            site for site, site_type in types.items() if site_type is SiteType.branch
        ):
            seen = {site_id}
            queue = deque([site_id])
            while queue:
                current = queue.popleft()
                for neighbor in sorted(adjacency.get(current, ())):
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append(neighbor)
            if not seen & targets:
                findings.append(
                    Finding(
                        severity=Severity.critical,
                        code="wan_branch_no_path_to_hq_dc",
                        affected_entities=[site_id],
                        explanation=(
                            f"Modeled branch site {site_id} has no modeled "
                            "path of active inter-site WAN links to any "
                            "modeled hq/dc site "
                            f"({', '.join(sorted(targets))})."
                        ),
                        remediation=(
                            "Add a modeled WAN path to a hq/dc site or "
                            "correct the modeled site type."
                        ),
                    )
                )

    findings.append(
        Finding(
            severity=Severity.info,
            code="wan_cost_proxy_total",
            affected_entities=[],
            explanation=(
                "Modeled WAN design has "
                f"{len(links)} active inter-site link(s) with a total monthly "
                f"cost proxy of {total:g}. {MONTHLY_COST_NOTE} {LATENCY_NOTE}"
            ),
        )
    )
    return tuple(findings)


def _evaluated_demand_count(state: object) -> int:
    """Count demands covered by a real NetworkState or a supplied fake."""
    demands = getattr(state, "demands", None)
    if demands is not None:
        return len(demands)
    return int(getattr(state, "demand_count", 0) or 0)


def _capacity_finding(
    twin: DigitalTwin,
    state: object,
) -> Finding | None:
    """Report unserved inter-site demands from a capacity-aware evaluation."""
    device_site = {device.id: device.site for device in twin.topology.devices}
    unserved = []
    for demand in getattr(state, "unserved_demands", ()) or ():
        source_site = device_site.get(getattr(demand, "source", ""))
        target_site = device_site.get(getattr(demand, "destination", ""))
        if source_site is None or target_site is None or source_site == target_site:
            continue
        unserved.append(demand)
    if not unserved:
        return None

    details = sorted(
        (
            str(getattr(demand, "name", "")),
            str(getattr(demand, "bottleneck_link_id", "") or ""),
        )
        for demand in unserved
    )
    names = sorted({name for name, _ in details})
    bottlenecks = sorted({link_id for _, link_id in details if link_id})
    affected = sorted(set(names) | set(bottlenecks))
    summary = ", ".join(
        f"{name} (bottleneck: {bottleneck or 'none'})"
        for name, bottleneck in details
    )
    return Finding(
        severity=Severity.error,
        code="wan_capacity_shortfall",
        affected_entities=affected,
        explanation=(
            f"Modeled capacity-aware evaluation left {len(unserved)} "
            "inter-site demand(s) unserved using modeled topology capacity: "
            f"{summary}."
        ),
        remediation=(
            "Revise the modeled WAN capacity or demand assumptions and "
            "re-run the capacity-aware evaluation."
        ),
    )


def analyze_wan_design(
    twin: DigitalTwin,
    *,
    design: WanDesign | None = None,
    include_expensive: bool = False,
    evaluation: object | None = None,
) -> WanAnalysis:
    """Run deterministic WAN design checks over one digital twin.

    ``design`` supplies authoritative site facts when available; without it,
    site types are inferred conservatively from device roles and site ids.
    ``include_expensive`` opts in to the existing capacity-aware evaluator;
    ``evaluation`` may supply an already-computed equivalent result instead.
    Nothing in this function contacts a device or infers types from live state.
    """
    links = inter_site_wan_links(twin)
    types = _site_types(twin, design)
    total = float(sum(info.monthly_cost_proxy for info in links))
    findings = list(
        _cheap_findings(links, types, _hq_dc_targets(types, design), total)
    )
    evaluated_demand_count = 0
    if include_expensive:
        if evaluation is None:
            # Local import keeps the WAN design layer independent of simulation
            # import order and avoids a module-level dependency cycle.
            from simulation.evaluator import evaluate
            from simulation.models import RoutingMode, SimulationAssumptions

            state = evaluate(
                twin,
                SimulationAssumptions(routing_mode=RoutingMode.capacity_aware),
            )
        else:
            state = evaluation
        evaluated_demand_count = _evaluated_demand_count(state)
        capacity_finding = _capacity_finding(twin, state)
        if capacity_finding is not None:
            findings.append(capacity_finding)

    return WanAnalysis(
        findings=tuple(findings),
        links=links,
        total_monthly_cost_proxy=total,
        site_ids=tuple(sorted(types)),
        evaluated_demand_count=evaluated_demand_count,
    )


__all__ = [
    "LATENCY_NOTE",
    "MONTHLY_COST_NOTE",
    "WanAnalysis",
    "WanLinkInfo",
    "analyze_wan_design",
    "inter_site_wan_links",
    "wan_cost_proxy_total",
]
