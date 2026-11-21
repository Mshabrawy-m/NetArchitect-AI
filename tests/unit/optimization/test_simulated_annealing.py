"""Seeded simulated annealing and hybrid-start behaviour."""

from __future__ import annotations

import pytest

from config.limits import MAX_SA_INITIAL_CANDIDATES
from core.exceptions import LimitsExceededError
from optimization import (
    Algorithm,
    Candidate,
    run_greedy,
    run_optimization,
    run_simulated_annealing,
)
from simulation import twin_fingerprint
from tests.unit.optimization.helpers import (
    connect_cd,
    settings,
    tiny_twin,
)


def test_sa_is_dispatchable_and_records_typed_provenance() -> None:
    config = settings(max_iterations=5, max_evaluations=80)
    run = run_optimization(tiny_twin(), config, Algorithm.simulated_annealing)

    assert run.algorithm is Algorithm.simulated_annealing
    assert run.seed == config.seed
    assert run.limits == config.limits()
    assert run.stop_reason.value in {"max_iterations", "max_evaluations"}
    assert run.baseline.candidate == Candidate()
    assert len(run.candidates) == run.evaluations


def test_sa_hybrid_start_uses_a_greedy_candidate() -> None:
    twin = tiny_twin()
    config = settings(max_iterations=5, max_evaluations=120)
    greedy = run_greedy(twin, config)
    assert greedy.best is not None

    hybrid = run_simulated_annealing(
        twin,
        config,
        initial_candidates=(greedy.best.evaluation.candidate,),
    )

    assert hybrid.algorithm is Algorithm.simulated_annealing
    assert greedy.best.evaluation.candidate_hash in {
        record.evaluation.candidate_hash for record in hybrid.candidates
    }
    assert hybrid.best is not None
    assert hybrid.best.evaluation.feasible


def test_sa_hybrid_start_never_mutates_the_source_twin() -> None:
    twin = tiny_twin()
    before = twin_fingerprint(twin)

    run_simulated_annealing(twin, settings(), initial_candidates=(connect_cd(),))

    assert twin_fingerprint(twin) == before


def test_sa_rejects_an_over_large_hybrid_start_list() -> None:
    starts = tuple(Candidate() for _ in range(MAX_SA_INITIAL_CANDIDATES + 1))

    with pytest.raises(LimitsExceededError, match="hybrid-start"):
        run_simulated_annealing(tiny_twin(), settings(), initial_candidates=starts)


def test_dispatch_rejects_hybrid_starts_for_byte_stable_algorithms() -> None:
    with pytest.raises(ValueError, match="only supported by simulated annealing"):
        run_optimization(
            tiny_twin(),
            settings(),
            Algorithm.genetic,
            initial_candidates=(connect_cd(),),
        )
