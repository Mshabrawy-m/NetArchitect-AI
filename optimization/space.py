"""Apply candidate decisions to a new twin without mutating the baseline.

The only way a candidate becomes a network design is :func:`build_candidate_twin`.
It starts from the supplied baseline twin and uses the immutable-style helpers
in :mod:`digital_twin` and :mod:`network.topology`. The baseline object is never
modified.
"""

from __future__ import annotations

from core.exceptions import OptimizationValidationError
from core.schemas.network import Link
from digital_twin import DigitalTwin, set_link_capacity, set_link_cost, set_topology
from network.topology import add_link

from .models import Candidate, CapacityTier, CostModel, OptimizationSettings


def pool_index(settings: OptimizationSettings) -> dict[str, Link]:
    """Return candidate-pool links keyed by id."""
    return {link.id: link for link in settings.candidate_pool}


def baseline_link_index(baseline_twin: DigitalTwin) -> dict[str, Link]:
    """Return baseline links keyed by id."""
    return {link.id: link for link in baseline_twin.topology.links}


def tier_for_link(
    link_id: str,
    candidate: Candidate,
    cost_model: CostModel,
) -> CapacityTier:
    """Return the candidate tier for a link, defaulting to the first tier."""
    name = candidate.tier_for(link_id)
    if name is None:
        return cost_model.tiers[0]
    try:
        return cost_model.tier(name)
    except ValueError as error:
        raise OptimizationValidationError(str(error)) from error


def _validate_candidate(
    baseline_twin: DigitalTwin,
    candidate: Candidate,
    settings: OptimizationSettings,
) -> tuple[dict[str, Link], dict[str, Link]]:
    pool = pool_index(settings)
    baseline_links = baseline_link_index(baseline_twin)
    known = set(pool) | set(baseline_links)

    unknown_selected = sorted(set(candidate.selected_link_ids) - set(pool))
    if unknown_selected:
        raise OptimizationValidationError(
            "Candidate selects link(s) outside the candidate pool: "
            + ", ".join(unknown_selected)
        )
    clashes = sorted(set(candidate.selected_link_ids) & set(baseline_links))
    if clashes:
        raise OptimizationValidationError(
            "Candidate selects link id(s) that already exist in the baseline: "
            + ", ".join(clashes)
            + ". Use a tier assignment to upgrade an existing link."
        )
    for link_id, tier_name in candidate.tier_assignments:
        if link_id not in known:
            raise OptimizationValidationError(
                f"Tier assignment names unknown link {link_id!r}"
            )
        if tier_name not in {tier.name for tier in settings.cost_model.tiers}:
            raise OptimizationValidationError(
                f"Tier assignment for {link_id!r} names unknown tier "
                f"{tier_name!r}"
            )
    for link_id, _ in candidate.cost_multipliers:
        if link_id not in known:
            raise OptimizationValidationError(
                f"Cost multiplier names unknown link {link_id!r}"
            )
    return pool, baseline_links


def build_candidate_twin(
    baseline_twin: DigitalTwin,
    candidate: Candidate,
    settings: OptimizationSettings,
) -> DigitalTwin:
    """Return a new twin with ``candidate`` decisions applied.

    Baseline capacity upgrades are applied first, pool links are added next,
    and routing-cost multipliers are applied last. The input twin is never
    mutated.
    """
    pool, baseline_links = _validate_candidate(baseline_twin, candidate, settings)
    twin = baseline_twin

    for link_id, _ in candidate.tier_assignments:
        if link_id not in baseline_links:
            continue
        tier = tier_for_link(link_id, candidate, settings.cost_model)
        twin = set_link_capacity(twin, link_id, tier.capacity_mbps)

    for link_id in candidate.selected_link_ids:
        source = pool[link_id]
        tier = tier_for_link(link_id, candidate, settings.cost_model)
        multiplier = candidate.multiplier_for(link_id)
        link = source.model_copy(
            update={
                "capacity_mbps": tier.capacity_mbps,
                "cost": source.cost * multiplier,
            }
        )
        twin = set_topology(twin, add_link(twin.topology, link))

    for link_id, multiplier in candidate.cost_multipliers:
        if link_id in baseline_links:
            current = next(
                link for link in twin.topology.links if link.id == link_id
            )
            twin = set_link_cost(twin, link_id, current.cost * multiplier)

    return twin


def candidate_changes(
    baseline_twin: DigitalTwin,
    candidate: Candidate,
    settings: OptimizationSettings,
) -> tuple[str, ...]:
    """Return deterministic human-readable change descriptions."""
    baseline_links = baseline_link_index(baseline_twin)
    pool = pool_index(settings)
    changes: list[str] = []
    for link_id in candidate.selected_link_ids:
        tier = tier_for_link(link_id, candidate, settings.cost_model)
        link = pool[link_id]
        changes.append(
            f"Add link {link_id} ({link.endpoints[0]}-{link.endpoints[1]}) "
            f"at {tier.name} / {tier.capacity_mbps:g} Mbps"
        )
    for link_id, _ in candidate.tier_assignments:
        if link_id not in baseline_links:
            continue
        tier = tier_for_link(link_id, candidate, settings.cost_model)
        changes.append(
            f"Set baseline link {link_id} to {tier.name} / "
            f"{tier.capacity_mbps:g} Mbps"
        )
    for link_id, multiplier in candidate.cost_multipliers:
        changes.append(
            f"Scale routing cost of {link_id} by {multiplier:g}"
        )
    return tuple(changes)


__all__ = [
    "baseline_link_index",
    "build_candidate_twin",
    "candidate_changes",
    "pool_index",
    "tier_for_link",
]
