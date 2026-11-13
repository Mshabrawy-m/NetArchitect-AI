"""Objective math, proxy cost arithmetic, and min-max normalization.

Every objective is defined in :data:`optimization.models.OBJECTIVE_DEFINITIONS`.
This module only computes values and normalized contributions; it does not
route traffic or mutate a twin.
"""

from __future__ import annotations

from digital_twin import DigitalTwin

from .models import (
    Candidate,
    ObjectiveDirection,
    ObjectiveSpec,
    ObjectiveValue,
    OptimizationSettings,
)
from .space import baseline_link_index, pool_index, tier_for_link


def infrastructure_cost_proxy(
    baseline_twin: DigitalTwin,
    candidate: Candidate,
    settings: OptimizationSettings,
) -> float:
    """Return the modeled infrastructure cost proxy for one candidate.

    Arithmetic:
    ``device_cost * device_count
      + sum(tier_cost for selected links)
      + sum(max(0, new_tier_cost - old_tier_cost) for baseline upgrades)``

    A baseline link whose capacity exactly matches a configured tier has that
    tier's cost as its sunk value; an unmatched capacity has zero modeled sunk
    value. Routing-cost multipliers do not change the infrastructure cost proxy.
    """
    cost_model = settings.cost_model
    baseline_links = baseline_link_index(baseline_twin)
    pool = pool_index(settings)
    total = cost_model.device_cost_proxy * len(baseline_twin.topology.devices)

    for link_id in candidate.selected_link_ids:
        if link_id not in pool:
            raise ValueError(f"Selected link {link_id!r} is not in the pool")
        total += tier_for_link(link_id, candidate, cost_model).link_cost_proxy

    for link_id, _ in candidate.tier_assignments:
        baseline = baseline_links.get(link_id)
        if baseline is None:
            continue
        new_tier = tier_for_link(link_id, candidate, cost_model)
        old_tier = cost_model.tier_for_capacity(baseline.capacity_mbps)
        old_cost = old_tier.link_cost_proxy if old_tier is not None else 0.0
        total += max(0.0, new_tier.link_cost_proxy - old_cost)

    return float(total)


def normalize_value(value: float, spec: ObjectiveSpec) -> float:
    """Return a min-max normalized value in ``[0, 1]``.

    Minimization maps the lower bound to 0 and the upper bound to 1. Maximization
    maps the upper bound to 0 and the lower bound to 1. Values outside the stated
    bounds are clamped rather than allowed to dominate the weighted score.
    """
    span = spec.upper_bound - spec.lower_bound
    clamped = min(max(float(value), spec.lower_bound), spec.upper_bound)
    if spec.direction is ObjectiveDirection.minimize:
        return (clamped - spec.lower_bound) / span
    return (spec.upper_bound - clamped) / span


def objective_value(spec: ObjectiveSpec, raw_value: float) -> ObjectiveValue:
    """Build one typed objective value from a raw metric."""
    normalized = normalize_value(raw_value, spec)
    return ObjectiveValue(
        kind=spec.kind,
        label=spec.label,
        unit=spec.unit,
        direction=spec.direction,
        raw_value=float(raw_value),
        normalized_value=normalized,
        weight=spec.weight,
        contribution=normalized * spec.weight,
    )


def weighted_score(values: tuple[ObjectiveValue, ...]) -> float:
    """Return the weighted sum of normalized objectives (lower is better)."""
    return float(sum(value.contribution for value in values))


__all__ = [
    "infrastructure_cost_proxy",
    "normalize_value",
    "objective_value",
    "weighted_score",
]
