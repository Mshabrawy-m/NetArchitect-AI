"""Shared genome, dominance, crowding, and enumeration utilities.

PSO is intentionally not implemented. A continuous velocity has no sound,
documented mapping onto the mixed discrete decisions used here (link presence,
per-link capacity tier, and optional cost multiplier). Implemented algorithms
are the deterministic greedy baseline, a seeded Genetic Algorithm, and NSGA-II.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import product

import numpy as np

from digital_twin import DigitalTwin

from ..models import (
    Candidate,
    CandidateEvaluation,
    CandidateRecord,
    ObjectiveDirection,
    OptimizationSettings,
)
from ..space import baseline_link_index, pool_index

MAX_EXHAUSTIVE_SEED = 5_000


@dataclass(frozen=True)
class GenomeSpace:
    """The ordered integer encoding used by GA and NSGA-II.

    Layout:
    * one presence bit per candidate-pool link,
    * one tier gene per pool link followed by one per baseline link,
    * one cost-multiplier gene per pool and baseline link.

    Pool tier genes are 0..T-1. Baseline tier genes use 0 for "unchanged" and
    1..K for the tiers that actually change that link's capacity, where K
    depends on the link. A tier that matches the baseline capacity is encoded
    as "unchanged" so equivalent designs share one hash. Multiplier genes use 0
    for unchanged and 1..M for a configured non-identity multiplier option.
    """

    pool_ids: tuple[str, ...]
    baseline_ids: tuple[str, ...]
    baseline_tier_names: tuple[tuple[str, ...], ...]
    tier_names: tuple[str, ...]
    multiplier_options: tuple[float, ...]

    @property
    def link_ids(self) -> tuple[str, ...]:
        return (*self.pool_ids, *self.baseline_ids)

    @property
    def tier_count(self) -> int:
        return len(self.tier_names)

    @property
    def size(self) -> int:
        return (
            len(self.pool_ids)
            + len(self.link_ids)
            + len(self.link_ids)
        )

    @property
    def upper_bounds(self) -> np.ndarray:
        """Return exclusive upper bounds for each gene position."""
        bounds: list[int] = []
        bounds.extend([2] * len(self.pool_ids))
        bounds.extend([self.tier_count] * len(self.pool_ids))
        bounds.extend(
            len(names) + 1 for names in self.baseline_tier_names
        )
        bounds.extend([len(self.multiplier_options) + 1] * len(self.link_ids))
        return np.asarray(bounds, dtype=np.int64)

    def encode(self, candidate: Candidate) -> np.ndarray:
        """Encode a candidate into the integer genome representation."""
        selected = set(candidate.selected_link_ids)
        tiers = {tier: index for index, tier in enumerate(self.tier_names)}
        multipliers: dict[str, int] = {}
        for index, option in enumerate(self.multiplier_options):
            multipliers[f"{option:.12g}"] = index
        genes: list[int] = []
        genes.extend(1 if link_id in selected else 0 for link_id in self.pool_ids)
        for link_id in self.pool_ids:
            tier_name = candidate.tier_for(link_id) or self.tier_names[0]
            genes.append(tiers[tier_name])
        for link_id, names in zip(self.baseline_ids, self.baseline_tier_names):
            tier_name = candidate.tier_for(link_id)
            if tier_name is None:
                genes.append(0)
                continue
            if tier_name in names:
                genes.append(names.index(tier_name) + 1)
            else:
                # A no-op assignment (same as baseline capacity) is unchanged.
                genes.append(0)
        for link_id in self.link_ids:
            value = candidate.multiplier_for(link_id)
            index = multipliers.get(f"{value:.12g}")
            genes.append(0 if index is None else index + 1)
        return np.asarray(genes, dtype=np.int64)

    def decode(self, genome: np.ndarray, settings: OptimizationSettings) -> Candidate:
        """Decode a genome into a canonical candidate."""
        genes = [int(value) for value in genome]
        selected = [
            link_id
            for link_id, present in zip(self.pool_ids, genes[: len(self.pool_ids)])
            if present
        ]
        offset = len(self.pool_ids)
        tier_genes = genes[offset : offset + len(self.link_ids)]
        pool_tiers = tier_genes[: len(self.pool_ids)]
        baseline_tiers = tier_genes[len(self.pool_ids) :]
        assignments: list[tuple[str, str]] = []
        for link_id, index in zip(self.pool_ids, pool_tiers):
            if link_id in selected:
                assignments.append(
                    (link_id, self.tier_names[min(max(index, 0), self.tier_count - 1)])
                )
        for link_id, index, names in zip(
            self.baseline_ids,
            baseline_tiers,
            self.baseline_tier_names,
        ):
            if index > 0 and names:
                assignments.append(
                    (
                        link_id,
                        names[min(max(index - 1, 0), len(names) - 1)],
                    )
                )
        multiplier_genes = genes[offset + len(self.link_ids) :]
        baseline = set(self.baseline_ids)
        multipliers = [
            (link_id, self.multiplier_options[value - 1])
            for link_id, value in zip(self.link_ids, multiplier_genes)
            if value > 0
            and (value - 1) < len(self.multiplier_options)
            and (link_id in selected or link_id in baseline)
        ]
        return Candidate(
            selected_link_ids=tuple(selected),
            tier_assignments=tuple(assignments),
            cost_multipliers=tuple(multipliers),
        )


def genome_space(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
) -> GenomeSpace:
    """Build the genome layout for one baseline and settings pair."""
    baseline_links = baseline_link_index(baseline_twin)
    baseline_ids = tuple(sorted(baseline_links))
    baseline_tier_names = tuple(
        tuple(
            tier.name
            for tier in settings.cost_model.tiers
            if tier.capacity_mbps != baseline_links[link_id].capacity_mbps
        )
        for link_id in baseline_ids
    )
    return GenomeSpace(
        pool_ids=tuple(sorted(pool_index(settings))),
        baseline_ids=baseline_ids,
        baseline_tier_names=baseline_tier_names,
        tier_names=tuple(tier.name for tier in settings.cost_model.tiers),
        multiplier_options=tuple(
            sorted(
                float(value)
                for value in settings.cost_multiplier_options
                if value != 1.0
            )
        ),
    )


def random_genome(rng: np.random.Generator, space: GenomeSpace) -> np.ndarray:
    """Draw one integer genome uniformly from its gene bounds."""
    bounds = space.upper_bounds
    return np.asarray(
        [int(rng.integers(0, int(bound))) for bound in bounds],
        dtype=np.int64,
    )


def random_candidate(
    rng: np.random.Generator,
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
) -> Candidate:
    """Draw one random candidate through the genome encoding."""
    space = genome_space(baseline_twin, settings)
    return space.decode(random_genome(rng, space), settings)


def crossover(
    left: np.ndarray,
    right: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Uniform crossover: each gene is independently drawn from a parent."""
    if left.shape != right.shape:  # pragma: no cover - defensive
        raise ValueError("Crossover parents must have the same genome length.")
    if left.size == 0:
        return left.copy()
    mask = rng.random(left.size) < 0.5
    return np.where(mask, left, right)


def mutate(
    genome: np.ndarray,
    rng: np.random.Generator,
    space: GenomeSpace,
    rate: float,
) -> np.ndarray:
    """Reset individual genes to a uniformly random valid value."""
    mutated = genome.copy()
    bounds = space.upper_bounds
    for index, bound in enumerate(bounds):
        if rng.random() < rate:
            mutated[index] = int(rng.integers(0, int(bound)))
    return mutated


def mutation_rate(space: GenomeSpace) -> float:
    """Return a bounded per-gene mutation rate (at least one expected gene)."""
    if space.size == 0:
        return 0.0
    return max(1.0 / space.size, 0.02)


def candidate_space_size(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
) -> int:
    """Return an upper bound on the number of encoded candidate combinations."""
    tiers = len(settings.cost_model.tiers)
    pool = len(settings.candidate_pool)
    baseline = baseline_link_index(baseline_twin)
    size = (tiers + 1) ** pool
    for link in baseline.values():
        different = sum(
            1
            for tier in settings.cost_model.tiers
            if tier.capacity_mbps != link.capacity_mbps
        )
        size *= 1 + different
    multipliers = len(
        [value for value in settings.cost_multiplier_options if value != 1.0]
    )
    size *= (multipliers + 1) ** (pool + len(baseline))
    return size


def enumerate_candidates(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    *,
    limit: int,
) -> tuple[Candidate, ...]:
    """Enumerate the discrete candidate space when it is small.

    Returns an empty tuple when the upper-bound space size exceeds ``limit``.
    Only used to seed tiny search spaces deterministically and to support
    brute-force tests; it is never a general optimizer.
    """
    size = candidate_space_size(baseline_twin, settings)
    if size > limit:
        return ()
    pool = tuple(sorted(pool_index(settings)))
    baseline = baseline_link_index(baseline_twin)
    pool_choices = [
        (None, *(tier.name for tier in settings.cost_model.tiers))
        for _ in pool
    ]
    baseline_choices = [
        (
            None,
            *(
                tier.name
                for tier in settings.cost_model.tiers
                if tier.capacity_mbps != baseline[link_id].capacity_mbps
            ),
        )
        for link_id in sorted(baseline)
    ]
    multiplier_choices = [None, *(
        value for value in settings.cost_multiplier_options if value != 1.0
    )]
    link_ids = (*pool, *sorted(baseline))
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for pool_pick in product(*pool_choices) if pool_choices else [()]:
        selected = [
            link_id
            for link_id, choice in zip(pool, pool_pick)
            if choice is not None
        ]
        pool_assignments = [
            (link_id, choice)
            for link_id, choice in zip(pool, pool_pick)
            if choice is not None
        ]
        for baseline_pick in (
            product(*baseline_choices) if baseline_choices else [()]
        ):
            assignments = [
                *pool_assignments,
                *(
                    (link_id, choice)
                    for link_id, choice in zip(sorted(baseline), baseline_pick)
                    if choice is not None
                ),
            ]
            for multiplier_pick in (
                product(*([multiplier_choices] * len(link_ids)))
                if link_ids
                else [()]
            ):
                multipliers = [
                    (link_id, value)
                    for link_id, value in zip(link_ids, multiplier_pick)
                    if value is not None
                    and (link_id in selected or link_id in baseline)
                ]
                candidate = Candidate(
                    selected_link_ids=tuple(selected),
                    tier_assignments=tuple(assignments),
                    cost_multipliers=tuple(multipliers),
                )
                key = candidate.model_dump_json()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
    return tuple(candidates)


def dominates_values(
    left: Sequence[float],
    right: Sequence[float],
    directions: Sequence[ObjectiveDirection],
) -> bool:
    """Return whether ``left`` Pareto-dominates ``right``.

    Every objective is at least as good and at least one is strictly better.
    """
    if len(left) != len(right) or len(left) != len(directions):
        raise ValueError("Dominance comparison needs equal-length vectors.")
    at_least_one = False
    for left_value, right_value, direction in zip(left, right, directions):
        if direction is ObjectiveDirection.minimize:
            if left_value > right_value:
                return False
            at_least_one = at_least_one or left_value < right_value
        else:
            if left_value < right_value:
                return False
            at_least_one = at_least_one or left_value > right_value
    return at_least_one


def dominates(
    left: CandidateEvaluation,
    right: CandidateEvaluation,
) -> bool:
    """Constraint-domination used by both algorithms.

    Feasible candidates dominate infeasible ones. Between infeasible candidates,
    fewer violated hard constraints dominates. Objective Pareto dominance is
    applied only when feasibility status and violation counts tie.
    """
    if left.feasible != right.feasible:
        return left.feasible
    if not left.feasible:
        left_violations = len(left.violated_constraints)
        right_violations = len(right.violated_constraints)
        if left_violations != right_violations:
            return left_violations < right_violations
    left_values = [value.raw_value for value in left.objectives]
    right_values = [value.raw_value for value in right.objectives]
    directions = [value.direction for value in left.objectives]
    return dominates_values(left_values, right_values, directions)


def constraint_key(evaluation: CandidateEvaluation) -> tuple[bool, int, float, str]:
    """Sort key: feasible first, fewer violations, lower weighted score."""
    return (
        not evaluation.feasible,
        len(evaluation.violated_constraints),
        evaluation.weighted_score,
        evaluation.candidate_hash,
    )


def non_dominated_sort(
    evaluations: Sequence[CandidateEvaluation],
) -> list[list[CandidateEvaluation]]:
    """Return Pareto layers using deterministic constraint domination."""
    ordered = sorted(evaluations, key=lambda item: item.candidate_hash)
    dominated_by: dict[str, set[str]] = {
        item.candidate_hash: set() for item in ordered
    }
    dominated_count: dict[str, int] = {
        item.candidate_hash: 0 for item in ordered
    }
    by_hash = {item.candidate_hash: item for item in ordered}
    for left in ordered:
        for right in ordered:
            if left.candidate_hash == right.candidate_hash:
                continue
            if dominates(left, right):
                dominated_by[left.candidate_hash].add(right.candidate_hash)
            elif dominates(right, left):
                dominated_count[left.candidate_hash] += 1

    layers: list[list[CandidateEvaluation]] = []
    remaining = set(by_hash)
    while remaining:
        layer = sorted(
            (
                by_hash[key]
                for key in remaining
                if dominated_count[key] == 0
            ),
            key=lambda item: item.candidate_hash,
        )
        if not layer:  # pragma: no cover - defensive
            layer = [by_hash[key] for key in sorted(remaining)]
        layers.append(layer)
        for item in layer:
            remaining.discard(item.candidate_hash)
            for candidate_hash in dominated_by[item.candidate_hash]:
                if candidate_hash in remaining:
                    dominated_count[candidate_hash] -= 1
    return layers


def crowding_distance_values(values: Sequence[Sequence[float]]) -> list[float]:
    """Return crowding distances for fixed objective vectors.

    Boundary points receive infinity. Interior contributions are normalized by
    each objective's observed range in the supplied layer.
    """
    count = len(values)
    if count == 0:
        return []
    if count <= 2:
        return [float("inf")] * count
    widths = len(values[0])
    distances = [0.0] * count
    for index in range(widths):
        order = sorted(range(count), key=lambda item: values[item][index])
        low = values[order[0]][index]
        high = values[order[-1]][index]
        distances[order[0]] = float("inf")
        distances[order[-1]] = float("inf")
        if high == low:
            continue
        for position in range(1, count - 1):
            upper = values[order[position + 1]][index]
            lower = values[order[position - 1]][index]
            distances[order[position]] += (upper - lower) / (high - low)
    return distances


def crowding_distance(
    evaluations: Sequence[CandidateEvaluation],
) -> list[float]:
    """Return crowding distances aligned with the supplied evaluations."""
    vectors = [
        [value.normalized_value for value in evaluation.objectives]
        for evaluation in evaluations
    ]
    return crowding_distance_values(vectors)


def rank_population(
    evaluations: Sequence[CandidateEvaluation],
) -> dict[str, tuple[int, float]]:
    """Return candidate hash -> (Pareto rank, crowding distance)."""
    ranks: dict[str, tuple[int, float]] = {}
    for index, layer in enumerate(non_dominated_sort(evaluations)):
        distances = crowding_distance(layer)
        for evaluation, distance in zip(layer, distances):
            ranks[evaluation.candidate_hash] = (index, distance)
    return ranks


def tournament(
    population: Sequence[CandidateEvaluation],
    rng: np.random.Generator,
    ranks: dict[str, tuple[int, float]] | None,
    *,
    size: int = 3,
) -> CandidateEvaluation:
    """Select one parent by binary/multi-way tournament.

    With ``ranks`` the NSGA-II comparator is used (lower rank, then larger
    crowding distance). Without it, the constraint-first weighted comparator is
    used.
    """
    if not population:
        raise ValueError("A tournament needs a non-empty population.")
    picks = [
        int(rng.integers(0, len(population)))
        for _ in range(min(size, len(population)))
    ]
    candidates = [population[index] for index in picks]
    if ranks is not None:
        return min(
            candidates,
            key=lambda item: (
                ranks.get(item.candidate_hash, (10**9, -1.0))[0],
                -ranks.get(item.candidate_hash, (10**9, -1.0))[1],
                item.candidate_hash,
            ),
        )
    return min(candidates, key=constraint_key)


def record_for(
    evaluation: CandidateEvaluation,
    ranks: dict[str, tuple[int, float]] | None = None,
) -> CandidateRecord:
    """Build a candidate record, attaching rank/crowding when available."""
    rank: int | None = None
    crowding: float | None = None
    if ranks is not None and evaluation.candidate_hash in ranks:
        rank, crowding = ranks[evaluation.candidate_hash]
    return CandidateRecord(
        evaluation=evaluation,
        rank=rank,
        crowding_distance=crowding,
    )


def best_feasible(
    evaluations: Sequence[CandidateEvaluation],
) -> CandidateRecord | None:
    """Return the lowest weighted-score feasible evaluation, if any."""
    feasible = [item for item in evaluations if item.feasible]
    if not feasible:
        return None
    best = min(
        feasible,
        key=lambda item: (item.weighted_score, item.candidate_hash),
    )
    return CandidateRecord(evaluation=best)


def dedupe(
    evaluations: Sequence[CandidateEvaluation],
) -> list[CandidateEvaluation]:
    """Return unique evaluations in first-seen order."""
    seen: dict[str, CandidateEvaluation] = {}
    for evaluation in evaluations:
        seen.setdefault(evaluation.candidate_hash, evaluation)
    return list(seen.values())


def pareto_front(
    evaluations: Sequence[CandidateEvaluation],
) -> list[CandidateEvaluation]:
    """Return the true non-dominated feasible front over every evaluation.

    Unlike a per-generation rank, this considers every candidate the run has
    evaluated, so a design cannot appear on the front merely because a
    dominating design was dropped from the final population.
    """
    ordered = sorted(dedupe(evaluations), key=lambda item: item.candidate_hash)
    front: list[CandidateEvaluation] = []
    for evaluation in ordered:
        if not evaluation.feasible:
            continue
        if any(dominates(member, evaluation) for member in front):
            continue
        front = [
            member for member in front if not dominates(evaluation, member)
        ]
        front.append(evaluation)
    front.sort(key=lambda item: item.candidate_hash)
    return front


def iter_random_candidates(
    rng: np.random.Generator,
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
) -> Iterator[Candidate]:
    """Yield random candidates indefinitely (bounded by the caller)."""
    space = genome_space(baseline_twin, settings)
    while True:
        yield space.decode(random_genome(rng, space), settings)


__all__ = [
    "MAX_EXHAUSTIVE_SEED",
    "GenomeSpace",
    "best_feasible",
    "candidate_space_size",
    "constraint_key",
    "crossover",
    "crowding_distance",
    "crowding_distance_values",
    "dedupe",
    "dominates",
    "dominates_values",
    "enumerate_candidates",
    "genome_space",
    "iter_random_candidates",
    "mutate",
    "mutation_rate",
    "non_dominated_sort",
    "pareto_front",
    "random_candidate",
    "random_genome",
    "rank_population",
    "record_for",
    "tournament",
]
