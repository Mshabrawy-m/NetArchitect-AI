"""Seeded heuristic algorithms over the discrete optimization design space.

Implemented: the deterministic greedy baseline, a Genetic Algorithm, NSGA-II,
and seeded simulated annealing with an optional hybrid start. Particle Swarm
Optimization is intentionally omitted because a
continuous velocity vector has no sound mapping onto link-presence bits,
per-link capacity tiers, and optional cost multipliers without introducing an
undocumented hybrid scheme.
"""

from .budget import SearchBudget
from .common import (
    MAX_EXHAUSTIVE_SEED,
    GenomeSpace,
    best_feasible,
    candidate_space_size,
    constraint_key,
    crossover,
    crowding_distance,
    crowding_distance_values,
    dedupe,
    dominates,
    dominates_values,
    enumerate_candidates,
    genome_space,
    iter_random_candidates,
    mutate,
    mutation_rate,
    non_dominated_sort,
    pareto_front,
    random_candidate,
    random_genome,
    rank_population,
    record_for,
    tournament,
)
from .dispatch import run_optimization
from .genetic import run_genetic
from .nsga2 import run_nsga2
from .simulated_annealing import (
    FINAL_TEMPERATURE,
    INITIAL_TEMPERATURE,
    NEIGHBOR_ATTEMPTS,
    run_simulated_annealing,
)

__all__ = [
    "FINAL_TEMPERATURE",
    "INITIAL_TEMPERATURE",
    "MAX_EXHAUSTIVE_SEED",
    "NEIGHBOR_ATTEMPTS",
    "GenomeSpace",
    "SearchBudget",
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
    "run_genetic",
    "run_nsga2",
    "run_optimization",
    "run_simulated_annealing",
    "tournament",
]
