"""Deterministic, assumption-driven wireless AP planning.

This module deliberately has NO RF propagation model. It converts stated area
and capacity assumptions into AP counts and uplink requirements. Every output
is a modeled estimate: clients are never enumerated and no site survey is
performed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.schemas.validation import Finding, Severity

from .models import WirelessArea, WirelessDesign

CAPACITY_FORMULA = "ceil(clients * client_mbps / (ap_capacity_mbps * utilization_target))"
COVERAGE_FORMULA = "ceil(area_m2 / (pi * coverage_radius_m^2 * overlap_factor))"
UPLINK_FORMULA = "recommended_ap_count * ap_capacity_mbps * utilization_target"
NO_RF_NOTE = (
    "Modeled estimate from stated area/capacity assumptions; "
    "no RF propagation or signal modeling."
)

_CAPACITY = "capacity"
_COVERAGE = "coverage"
_NONE = "none"

FORMULAS: tuple[str, ...] = (
    f"Capacity AP count (modeled estimate): {CAPACITY_FORMULA}",
    f"Coverage AP count (modeled estimate): {COVERAGE_FORMULA}",
    f"Uplink requirement in Mbps (modeled estimate): {UPLINK_FORMULA}",
)

ASSUMPTIONS: tuple[str, ...] = (
    NO_RF_NOTE,
    (
        "modeled estimate uses the stated client count or stated density times "
        "stated floor area; clients are never enumerated."
    ),
    (
        "modeled estimate uses only stated per-client demand, AP capacity, "
        "utilization target, circular coverage radius, and overlap factor."
    ),
)


@dataclass(frozen=True)
class WirelessAreaPlan:
    """Modeled AP estimate for one abstract wireless area."""

    area_id: str
    area_name: str
    effective_clients: int
    capacity_ap_count: int
    coverage_ap_count: int
    recommended_ap_count: int
    binding_constraint: str
    uplink_required_mbps: float
    formulas: tuple[str, ...]
    assumptions: tuple[str, ...]
    uplink_switch_id: str | None


@dataclass(frozen=True)
class WirelessAnalysis:
    """Deterministic aggregate over the areas of a wireless design."""

    plans: tuple[WirelessAreaPlan, ...]
    findings: tuple[Finding, ...]
    total_recommended_aps: int
    total_uplink_required_mbps: float


def _effective_clients(area: WirelessArea) -> int:
    if area.clients > 0:
        return area.clients
    if area.area_m2 <= 0 or area.client_density_per_100m2 <= 0:
        return 0
    return math.ceil(area.area_m2 / 100 * area.client_density_per_100m2)


def _capacity_ap_count(area: WirelessArea, effective_clients: int) -> int:
    denominator = area.ap_capacity_mbps * area.utilization_target
    if effective_clients <= 0 or denominator <= 0:
        return 0
    return math.ceil(effective_clients * area.client_mbps / denominator)


def _coverage_ap_count(area: WirelessArea) -> int:
    if area.area_m2 <= 0:
        return 0
    denominator = math.pi * area.coverage_radius_m**2 * area.overlap_factor
    if denominator <= 0:
        return 0
    return math.ceil(area.area_m2 / denominator)


def plan_wireless_area(area: WirelessArea) -> WirelessAreaPlan:
    """Return the modeled AP and uplink estimate for one abstract area."""

    effective_clients = _effective_clients(area)
    capacity_ap_count = _capacity_ap_count(area, effective_clients)
    coverage_ap_count = _coverage_ap_count(area)
    recommended_ap_count = max(capacity_ap_count, coverage_ap_count)

    if capacity_ap_count > coverage_ap_count:
        binding_constraint = _CAPACITY
    elif coverage_ap_count > capacity_ap_count:
        binding_constraint = _COVERAGE
    else:
        binding_constraint = _NONE

    uplink_required_mbps = round(
        recommended_ap_count * area.ap_capacity_mbps * area.utilization_target,
        6,
    )

    return WirelessAreaPlan(
        area_id=area.id,
        area_name=area.name,
        effective_clients=effective_clients,
        capacity_ap_count=capacity_ap_count,
        coverage_ap_count=coverage_ap_count,
        recommended_ap_count=recommended_ap_count,
        binding_constraint=binding_constraint,
        uplink_required_mbps=uplink_required_mbps,
        formulas=FORMULAS,
        assumptions=ASSUMPTIONS,
        uplink_switch_id=area.uplink_switch_id,
    )


def _info(
    code: str,
    explanation: str,
    remediation: str,
    affected_entities: list[str],
) -> Finding:
    return Finding(
        severity=Severity.info,
        code=code,
        affected_entities=sorted(set(affected_entities)),
        explanation=explanation,
        remediation=remediation,
    )


def analyze_wireless_design(design: WirelessDesign | None) -> WirelessAnalysis:
    """Aggregate modeled AP counts and informational findings for a design."""

    areas = design.areas if design is not None else ()
    plans = tuple(plan_wireless_area(area) for area in areas)

    findings: list[Finding] = []
    if not plans:
        findings.append(
            _info(
                "wireless_no_modeled_demand",
                "No wireless areas are modeled; this modeled estimate reports "
                "zero AP demand and zero uplink requirement.",
                "Add an abstract wireless area with stated area or client "
                "assumptions if a modeled estimate is needed.",
                [],
            )
        )

    for area, plan in zip(areas, plans, strict=True):
        if plan.effective_clients == 0 and area.area_m2 == 0:
            findings.append(
                _info(
                    "wireless_no_modeled_demand",
                    f"Area {plan.area_id!r} has neither stated clients nor stated "
                    "floor area; this modeled estimate reports zero AP demand.",
                    "Supply an explicit client count or a stated floor area and "
                    "client density if a modeled estimate is needed.",
                    [plan.area_id],
                )
            )
        if plan.binding_constraint == _CAPACITY:
            findings.append(
                _info(
                    "wireless_capacity_binding",
                    f"Area {plan.area_id!r} is capacity-bound in this modeled "
                    f"estimate: {plan.capacity_ap_count} capacity AP(s) versus "
                    f"{plan.coverage_ap_count} coverage AP(s); recommendation is "
                    f"{plan.recommended_ap_count} AP(s).",
                    "Review the stated per-client demand, AP capacity, and "
                    "utilization target assumptions.",
                    [plan.area_id],
                )
            )
        elif plan.binding_constraint == _COVERAGE:
            findings.append(
                _info(
                    "wireless_coverage_binding",
                    f"Area {plan.area_id!r} is coverage-bound in this modeled "
                    f"estimate: {plan.coverage_ap_count} coverage AP(s) versus "
                    f"{plan.capacity_ap_count} capacity AP(s); recommendation is "
                    f"{plan.recommended_ap_count} AP(s).",
                    "Review the stated floor area, circular radius, and overlap "
                    "factor assumptions.",
                    [plan.area_id],
                )
            )

    return WirelessAnalysis(
        plans=plans,
        findings=tuple(findings),
        total_recommended_aps=sum(plan.recommended_ap_count for plan in plans),
        total_uplink_required_mbps=round(
            sum(plan.uplink_required_mbps for plan in plans),
            6,
        ),
    )


__all__ = [
    "ASSUMPTIONS",
    "CAPACITY_FORMULA",
    "COVERAGE_FORMULA",
    "FORMULAS",
    "NO_RF_NOTE",
    "UPLINK_FORMULA",
    "WirelessAnalysis",
    "WirelessAreaPlan",
    "analyze_wireless_design",
    "plan_wireless_area",
]
