"""OSPF area design model: modeled design rules only.

This is a *design model*. It derives area membership, router roles, link costs,
and inert summarization suggestions from a typed topology; it does not run
OSPF, exchange link-state advertisements, or simulate packets.

Derivation rules
----------------
* Area membership comes from ``device_ids`` and from the endpoints of each
  area's ``link_ids``. A device in two or more areas is an ``ABR``; a device in
  one area is ``internal``. A device explicitly listed in ``external_device_ids``
  or whose topology role is ``border`` or ``wan`` is an ``ASBR``. When both
  apply, the documented precedence is ``ASBR`` > ``ABR`` > ``internal``.
* Link costs reuse the existing routing engine semantics: ``Link.cost`` is the
  weight and capacity is metadata only. If the designer supplies
  ``reference_bandwidth_mbps``, an *optional modeled* cost is instead
  ``ceil(reference_bandwidth_mbps / link.capacity_mbps)`` (the classic OSPF
  formula, with bandwidth in Mbps). Both the base and effective cost are
  reported; no other cost semantic is introduced.
* Every non-backbone area should have at least one ABR also in area 0. When it
  does not, the model flags ``virtual-link-needed``; it does not model the
  virtual link itself or claim reachability through it.
* The area device threshold is a configurable heuristic and explicitly NOT a
  protocol limit.
* A single ABR per area is flagged only when the existing SPOF engine also
  reports that device as an articulation point.
* Summaries come from :func:`ipaddress.collapse_addresses` and are inert
  suggestions. Nothing is injected into a routing table.
"""

from __future__ import annotations

import ipaddress
import math
from collections import defaultdict
from enum import Enum

from pydantic import BaseModel, Field

from config.limits import (
    DEFAULT_OSPF_AREA_DEVICE_THRESHOLD,
    MAX_OSPF_AREAS,
    MAX_OSPF_SUMMARY_SUGGESTIONS,
)
from core.exceptions import LimitsExceededError
from core.schemas.addressing import NetworkType
from core.schemas.network import DeviceRole, Topology
from core.schemas.validation import Finding, Severity
from network.analysis import spof_report
from network.routing.paths import component_summary

BACKBONE_AREA_ID = 0
_ASBR_ROLES = frozenset({DeviceRole.border, DeviceRole.wan})


class OspfArea(BaseModel):
    """One modeled OSPF area."""

    area_id: int = Field(ge=0, description="Numeric area id; 0 is the backbone.")
    name: str = Field(min_length=1, description="Human-readable area label.")
    device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Devices with interfaces in this area.",
    )
    link_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Topology links inside this area; endpoints join device_ids.",
    )
    subnets: tuple[NetworkType, ...] = Field(
        default_factory=tuple,
        description="Area subnets used only for inert summarization suggestions.",
    )


class OspfDesign(BaseModel):
    """A designer-supplied OSPF area design and the derivation parameters."""

    areas: tuple[OspfArea, ...] = Field(default_factory=tuple)
    declared_abr_device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="ABRs the designer expects; checked against derived membership.",
    )
    external_device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Extra devices modeled as ASBRs in addition to border/wan roles.",
    )
    reference_bandwidth_mbps: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Optional modeled reference bandwidth. When set, effective link cost "
            "is ceil(reference/capacity_mbps); otherwise Link.cost is used."
        ),
    )
    area_size_threshold: int = Field(
        default=DEFAULT_OSPF_AREA_DEVICE_THRESHOLD,
        gt=0,
        description="Configurable heuristic device count; NOT a protocol limit.",
    )


class OspfRouterRole(str, Enum):
    """Derived role of one router in the area design."""

    internal = "internal"
    abr = "abr"
    asbr = "asbr"


class OspfRouter(BaseModel):
    """One device with its derived area membership and role."""

    device_id: str
    area_ids: tuple[int, ...]
    role: OspfRouterRole


class OspfLinkCost(BaseModel):
    """Base and effective modeled cost for one topology link."""

    link_id: str
    capacity_mbps: float = Field(gt=0)
    base_cost: float = Field(ge=0)
    effective_cost: float = Field(ge=0)
    formula: str


class OspfSummary(BaseModel):
    """An inert CIDR summary suggestion for one area."""

    area_id: int
    summary: str
    covered_subnets: tuple[str, ...]
    inert: bool = True


class OspfAnalysis(BaseModel):
    """The complete deterministic result of one OSPF design review."""

    routers: tuple[OspfRouter, ...] = Field(default_factory=tuple)
    link_costs: tuple[OspfLinkCost, ...] = Field(default_factory=tuple)
    summaries: tuple[OspfSummary, ...] = Field(default_factory=tuple)
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    assumptions: tuple[str, ...] = Field(default_factory=tuple)


def _finding(
    severity: Severity,
    code: str,
    explanation: str,
    remediation: str,
    entities: list[str],
) -> Finding:
    return Finding(
        severity=severity,
        code=code,
        affected_entities=entities,
        explanation=explanation,
        remediation=remediation,
    )


def _summaries(
    areas: tuple[OspfArea, ...],
) -> tuple[list[OspfSummary], list[Finding]]:
    suggestions: list[OspfSummary] = []
    findings: list[Finding] = []
    for area in areas:
        by_version: dict[
            int, list[ipaddress.IPv4Network | ipaddress.IPv6Network]
        ] = defaultdict(list)
        for subnet in area.subnets:
            by_version[subnet.version].append(subnet)
        for version, networks in sorted(by_version.items()):
            if len(networks) < 2:
                continue
            for collapsed in sorted(
                ipaddress.collapse_addresses(networks),
                key=lambda item: (int(item.network_address), item.prefixlen),
            ):
                covered = tuple(
                    str(network)
                    for network in networks
                    if network.subnet_of(collapsed)
                )
                if len(covered) < 2 or len(suggestions) >= MAX_OSPF_SUMMARY_SUGGESTIONS:
                    continue
                suggestions.append(
                    OspfSummary(
                        area_id=area.area_id,
                        summary=str(collapsed),
                        covered_subnets=covered,
                    )
                )
                findings.append(
                    _finding(
                        Severity.info,
                        "ospf_summarization_opportunity",
                        (
                            f"Area {area.area_id} subnets {', '.join(covered)} collapse "
                            f"to inert summary {collapsed}. This is a modeled "
                            "suggestion only; no route is installed."
                        ),
                        "Review the suggestion before planning an ABR summary route.",
                        [str(area.area_id), str(collapsed)],
                    )
                )
    return suggestions, findings


def analyze_ospf_design(
    design: OspfDesign,
    topology: Topology,
) -> OspfAnalysis:
    """Derive roles, costs, rule findings, and inert summaries for ``design``."""
    if len(design.areas) > MAX_OSPF_AREAS:
        raise LimitsExceededError(
            f"OSPF design has {len(design.areas)} areas; the limit is {MAX_OSPF_AREAS}"
        )

    findings: list[Finding] = []
    device_lookup = {device.id: device for device in topology.devices}
    link_lookup = {link.id: link for link in topology.links}
    membership: dict[str, set[int]] = defaultdict(set)

    seen_ids: set[int] = set()
    for area in design.areas:
        if area.area_id in seen_ids:
            findings.append(
                _finding(
                    Severity.error,
                    "ospf_duplicate_area_id",
                    f"Area id {area.area_id} is declared more than once.",
                    "Give every area a unique id.",
                    [str(area.area_id)],
                )
            )
        seen_ids.add(area.area_id)
        for device_id in area.device_ids:
            if device_id not in device_lookup:
                findings.append(
                    _finding(
                        Severity.error,
                        "ospf_unknown_device",
                        (
                            f"Area {area.area_id} references unknown device "
                            f"{device_id!r}."
                        ),
                        "Remove the stale reference or add the device to the topology.",
                        [str(area.area_id), device_id],
                    )
                )
                continue
            membership[device_id].add(area.area_id)
        for link_id in area.link_ids:
            link = link_lookup.get(link_id)
            if link is None:
                findings.append(
                    _finding(
                        Severity.error,
                        "ospf_unknown_link",
                        (
                            f"Area {area.area_id} references unknown link "
                            f"{link_id!r}."
                        ),
                        "Remove the stale reference or add the link to the topology.",
                        [str(area.area_id), link_id],
                    )
                )
                continue
            for endpoint in link.endpoints:
                membership[endpoint].add(area.area_id)

    external = set(design.external_device_ids)
    external.update(
        device.id
        for device in topology.devices
        if device.role in _ASBR_ROLES and device.id in membership
    )
    routers = tuple(
        OspfRouter(
            device_id=device_id,
            area_ids=tuple(sorted(areas)),
            role=(
                OspfRouterRole.asbr
                if device_id in external
                else (
                    OspfRouterRole.abr
                    if len(areas) >= 2
                    else OspfRouterRole.internal
                )
            ),
        )
        for device_id, areas in sorted(membership.items())
    )
    roles = {router.device_id: router.role for router in routers}

    if BACKBONE_AREA_ID not in seen_ids:
        findings.append(
            _finding(
                Severity.error,
                "ospf_no_backbone",
                "The design declares no backbone area 0.",
                "Add area 0 or explicitly model a virtual-link design.",
                ["0"],
            )
        )

    for area in design.areas:
        attached = [
            device_id
            for device_id, areas in membership.items()
            if area.area_id in areas
            and BACKBONE_AREA_ID in areas
            and roles[device_id] is OspfRouterRole.abr
        ]
        if area.area_id != BACKBONE_AREA_ID and not attached:
            findings.append(
                _finding(
                    Severity.warning,
                    "ospf_virtual_link_needed",
                    (
                        f"Area {area.area_id} has no ABR also attached to area 0; "
                        "the modeled design flags virtual-link-needed. No virtual "
                        "link behavior is simulated."
                    ),
                    "Attach an ABR to both areas or document a virtual-link design.",
                    [str(area.area_id)],
                )
            )

    for device_id in sorted(set(design.declared_abr_device_ids)):
        areas = membership.get(device_id, set())
        if len(areas) < 2:
            findings.append(
                _finding(
                    Severity.error,
                    "ospf_abr_not_multi_area",
                    (
                        f"Declared ABR {device_id!r} has interfaces in "
                        f"{len(areas)} area(s); an ABR requires interfaces in 2+."
                    ),
                    "Add the device to a second area or change its declared role.",
                    [device_id],
                )
            )

    for area in design.areas:
        device_count = len(set(area.device_ids) | {
            endpoint
            for link_id in area.link_ids
            if link_id in link_lookup
            for endpoint in link_lookup[link_id].endpoints
        })
        if device_count > design.area_size_threshold:
            findings.append(
                _finding(
                    Severity.warning,
                    "ospf_area_too_large",
                    (
                        f"Area {area.area_id} has {device_count} device(s), above the "
                        f"configured heuristic of {design.area_size_threshold}. This "
                        "is a planning guideline, NOT an OSPF protocol limit."
                    ),
                    "Split the area or raise the documented heuristic if intentional.",
                    [str(area.area_id)],
                )
            )

    backbone_devices = {
        device_id
        for device_id, areas in membership.items()
        if BACKBONE_AREA_ID in areas
    }
    if backbone_devices:
        filtered = Topology(
            name=f"{topology.name}-backbone",
            devices=[
                device
                for device in topology.devices
                if device.id in backbone_devices
            ],
            links=[
                link
                for link in topology.links
                if all(endpoint in backbone_devices for endpoint in link.endpoints)
            ],
        )
        components = component_summary(filtered).weak_components
        if len(components) > 1:
            findings.append(
                _finding(
                    Severity.error,
                    "ospf_backbone_discontiguous",
                    (
                        "Backbone area 0 resolves to "
                        f"{len(components)} disconnected component(s): "
                        + "; ".join(
                            ", ".join(sorted(component)) for component in components
                        )
                        + "."
                    ),
                    "Connect the backbone components with area-0 links.",
                    ["0"],
                )
            )

    if backbone_devices and topology.devices:
        spof_ids = {
            entry.entity_id
            for entry in spof_report(topology).entries
            if entry.kind == "device"
        }
        for area in design.areas:
            if area.area_id == BACKBONE_AREA_ID:
                continue
            attached = [
                device_id
                for device_id, areas in membership.items()
                if area.area_id in areas
                and BACKBONE_AREA_ID in areas
                and roles[device_id] is OspfRouterRole.abr
            ]
            if len(attached) == 1 and attached[0] in spof_ids:
                findings.append(
                    _finding(
                        Severity.warning,
                        "ospf_single_abr_spof",
                        (
                            f"Area {area.area_id} reaches the backbone through a "
                            f"single ABR {attached[0]!r}, which the existing SPOF "
                            "engine also reports as an articulation point."
                        ),
                        "Add a second ABR or a documented alternate area-0 path.",
                        [str(area.area_id), attached[0]],
                    )
                )

    link_costs: list[OspfLinkCost] = []
    for link in topology.links:
        if design.reference_bandwidth_mbps is None:
            effective = float(link.cost)
            formula = "Link.cost (existing routing-engine cost semantics)"
        else:
            effective = float(
                math.ceil(design.reference_bandwidth_mbps / link.capacity_mbps)
            )
            formula = (
                f"ceil({design.reference_bandwidth_mbps:g} / "
                f"{link.capacity_mbps:g}) = {effective:g}"
            )
        link_costs.append(
            OspfLinkCost(
                link_id=link.id,
                capacity_mbps=link.capacity_mbps,
                base_cost=link.cost,
                effective_cost=effective,
                formula=formula,
            )
        )

    summaries, summary_findings = _summaries(design.areas)
    findings.extend(summary_findings)
    findings.sort(key=lambda item: (item.code, tuple(item.affected_entities)))
    assumptions = (
        "Modeled design rules only: no OSPF packets or protocol behavior are simulated.",
        (
            "ABR = interfaces in 2+ areas; ASBR = external_device_ids or "
            "border/wan role; precedence ASBR > ABR > internal."
        ),
        (
            "Non-backbone areas need an ABR also in area 0; otherwise "
            "virtual-link-needed is flagged but not modeled."
        ),
        "Area device threshold is a configurable heuristic, NOT a protocol limit.",
        (
            "Cost uses Link.cost unless reference_bandwidth_mbps is set, then "
            "ceil(reference/capacity_mbps) with Mbps."
        ),
        "Summaries are inert ipaddress.collapse_addresses suggestions, not routes.",
    )
    return OspfAnalysis(
        routers=routers,
        link_costs=tuple(link_costs),
        summaries=tuple(summaries),
        findings=tuple(findings),
        assumptions=assumptions,
    )


__all__ = [
    "BACKBONE_AREA_ID",
    "OspfAnalysis",
    "OspfArea",
    "OspfDesign",
    "OspfLinkCost",
    "OspfRouter",
    "OspfRouterRole",
    "OspfSummary",
    "analyze_ospf_design",
]
