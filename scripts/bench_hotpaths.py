"""Small reproducible hot-path benchmarks (no pytest, no tracemalloc).

Runs one all-pairs routing call, one MAX_DEMANDS evaluation, and one seeded GA
with a five-second search budget. Used before and after the V2 hot-path change;
the output is a Markdown table that can be pasted into docs/PERFORMANCE.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.routing import reachability_matrix
from optimization import Algorithm, run_optimization
from scripts.profile_phase12 import (
    _max_topology,
    _max_twin,
    _optimization_settings,
)
from simulation import evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ga-seconds", type=float, default=5.0)
    args = parser.parse_args()

    topology = _max_topology()
    twin = _max_twin(topology)
    rows: list[tuple[str, float, str]] = []

    started = time.perf_counter()
    reachability_matrix(topology)
    rows.append(("all-pairs routing", time.perf_counter() - started, "one call"))

    started = time.perf_counter()
    evaluate(twin)
    rows.append(
        ("evaluate with MAX_DEMANDS", time.perf_counter() - started, "one call")
    )

    settings = _optimization_settings().model_copy(
        update={
            "seed": 42,
            "max_runtime_seconds": args.ga_seconds,
            "max_evaluations": 20_000,
            "max_iterations": 1_000,
        }
    )
    started = time.perf_counter()
    run = run_optimization(twin, settings, Algorithm.genetic)
    elapsed = time.perf_counter() - started
    rows.append(("GA search wall clock", elapsed, f"stop={run.stop_reason.value}"))

    print()
    print("| measurement | seconds | evaluations | per second | note |")
    print("| --- | ---: | ---: | ---: | --- |")
    for name, seconds, note in rows[:2]:
        print(f"| {name} | {seconds:.3f} | - | - | {note} |")
    rate = run.evaluations / elapsed if elapsed else 0.0
    print(
        f"| GA evaluations/sec | {elapsed:.3f} | {run.evaluations} | "
        f"{rate:.1f} | cache_hits={run.cache_hits}; "
        f"stop={run.stop_reason.value} |"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
