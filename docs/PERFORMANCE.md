# Performance evidence (V2)

All numbers in this file are measured, not estimated. Timings were produced on
the local Windows host with Python 3.11.15 unless a Linux CI number is named.
The reproducible profile command is:

```bash
python scripts/profile_phase12.py --no-memory
```

It is intentionally run once before the V2 hot-path change and once after; it
is not part of a normal test run. `tracemalloc` is disabled in these wall-clock
runs.

## Linux RSS gate

`.github/workflows/ci.yml` runs `scripts/check_linux_memory.py` on
`ubuntu-latest` after importing `app` and rendering the Dashboard with
`AppTest`. The gate reads `VmRSS` from `/proc/self/status` and fails above
**450 MB**.

Why 450 MB: Community Cloud Free provides roughly 1 GB RAM. The OS, Streamlit
server, cold-start imports, and one interactive session need the remainder;
450 MB leaves headroom for those while still catching an accidental import or
unbounded cache regression. This is process RSS, not a `tracemalloc` peak. The
check has **not** been executed remotely; the first CI push must confirm it.

## Baseline (before V2 hot-path changes)

Command: `python scripts/profile_phase12.py --no-memory` (run once before the
change). Verbatim table:

| operation | seconds | peak MiB | over budget | note |
| --- | ---: | ---: | :---: | --- |
| generate max-size topology | 0.004 | 0.0 | no |  |
| build max twin | 0.078 | 0.0 | no |  |
| all-pairs routing | 0.970 | 0.0 | no |  |
| evaluate with MAX_DEMANDS | 0.762 | 0.0 | no |  |
| genetic at configured maxima | 60.900 | 0.0 | yes | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60 |
| nsga2 at configured maxima | 60.928 | 0.0 | yes | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60 |
| report build | 2.129 | 0.0 | no |  |
| PDF build | 1.232 | 0.0 | no |  |

Budget threshold: >5 s in a --no-memory run, or >300 MiB in a tracemalloc run, is flagged. Tracemalloc adds time overhead and records Python allocations, not total process RSS. Run with --no-memory for wall-clock numbers.

Command: `python scripts/bench_hotpaths.py --ga-seconds 5` (same host, seed 42,
one run each):

| measurement | seconds | evaluations | per second | note |
| --- | ---: | ---: | ---: | --- |
| all-pairs routing | 0.974 | - | - | one call |
| evaluate with MAX_DEMANDS | 0.940 | - | - | one call |
| GA evaluations/sec | 5.893 | 6 | 1.0 | cache_hits=0; stop=runtime_limit |

The 5 s GA run overshot its deadline because the search checks it between
full candidate evaluations; the overshoot itself is part of the baseline.

## After-change table (T3)

Command: `.venv\Scripts\python.exe -B scripts/profile_phase12.py --no-memory`
(same host and fixed seed, run once after the hot-path change). Verbatim table:

| operation | seconds | peak MiB | over budget | note |
| --- | ---: | ---: | :---: | --- |
| generate max-size topology | 0.005 | 0.0 | no |  |
| build max twin | 0.080 | 0.0 | no |  |
| all-pairs routing | 0.066 | 0.0 | no |  |
| evaluate with MAX_DEMANDS | 0.045 | 0.0 | no |  |
| genetic at configured maxima | 60.118 | 0.0 | yes | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60 |
| nsga2 at configured maxima | 60.498 | 0.0 | yes | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60 |
| report build | 1.192 | 0.0 | no |  |
| PDF build | 1.263 | 0.0 | no |  |

Budget threshold: >5 s in a --no-memory run, or >300 MiB in a tracemalloc run, is flagged. Tracemalloc adds time overhead and records Python allocations, not total process RSS. Run with --no-memory for wall-clock numbers.

Command: `.venv\Scripts\python.exe -B scripts/bench_hotpaths.py --ga-seconds 5`
(seed 42, one run each):

| measurement | seconds | evaluations | per second | note |
| --- | ---: | ---: | ---: | --- |
| all-pairs routing | 0.063 | - | - | one call |
| evaluate with MAX_DEMANDS | 0.082 | - | - | one call |
| GA evaluations/sec | 5.072 | 51 | 10.1 | cache_hits=0; stop=runtime_limit |

### Before/after summary

| measurement | before | after | speedup |
| --- | ---: | ---: | ---: |
| all-pairs routing, profile (s) | 0.970 | 0.066 | 14.7x |
| evaluate with MAX_DEMANDS, profile (s) | 0.762 | 0.045 | 16.9x |
| all-pairs routing, bench (s) | 0.974 | 0.063 | 15.5x |
| evaluate with MAX_DEMANDS, bench (s) | 0.940 | 0.082 | 11.5x |
| GA evaluations/sec, 5 s bench | 1.0 | 10.1 | 10.1x |
| GA wall clock, configured maxima (s) | 60.900 | 60.118 | 1.01x |

The >=3x target was met for both all-pairs routing and evaluation in both
scripts. The limiter for GA/NSGA-II wall clock is unchanged:
`MAX_OPTIMIZATION_RUNTIME_SECONDS = 60`. The search now performs about ten
times as many candidate evaluations inside that fixed budget, but it still
stops at `runtime_limit`; this is a throughput result, not a shorter search.
Single local Windows runs are subject to network/CPU variance, so the ratios are
evidence for this host, not a guarantee for Cloud.

### Correctness gate

- `tests/routing_reference.py` freezes the pre-V2 NetworkX algorithms.
  `tests/unit/routing/test_sparse_equivalence.py` compares typed results against
  it for equal-cost ties, parallel links, directed links, failures,
  disconnected graphs, and star/ring/campus/spine-leaf/max-size topologies.
- `tests/unit/optimization/v2_objective_vectors.json` was captured from commit
  `3e31a41` before the change. `tests/unit/optimization/test_hotpath_regression.py`
  asserts the seeded GA and NSGA-II objective-vector JSON is byte-identical
  after the change.
- A real equivalence bug was found during this work: using a float tolerance in
  sparse path extraction preferred `a-b-d` (`0.1 + 0.2 = 0.30000000000000004`)
  over the reference's exact `a-d` (`0.3`). Suffix distances are now taken from
  the candidate neighbor as source and compared exactly; the minimal topology
  is a regression test.
- Opt-in timing budgets live in `tests/unit/test_perf_budgets.py` with the
  `perf` marker. They are excluded from default and smoke runs by `pytest.ini`
  and use at least a 2x margin over the measured after-change numbers.

## Cold-start imports (T4)

Command: `.venv\Scripts\python.exe -B scripts/profile_imports.py`. This runs
`python -X importtime -c "import app"` in a fresh child process and then times
one clean `AppTest` run of the Dashboard. The baseline was measured in a
throwaway worktree at commit `bf2b5b8` with the same script and interpreter;
the after numbers were measured in the working tree after the lazy-import
changes. `importtime` cumulative values include nested imports, so target rows
overlap and are not added together. The harmless
`missing ScriptRunContext` warning appeared on stderr in both runs.

Baseline (before T4), verbatim table:

| import target | cumulative us |
| --- | ---: |
| reportlab | 322842 |
| services.reporting | 137397 |
| services.export | 367015 |
| ui.pages.reports | 4040 |
| ui.pages.agent_control_center | 192633 |
| ui.pages.ai_designer | 6939 |
| ui.pages.security_analysis | 7186 |
| app (total cumulative) | 2327519 |

| measurement | seconds |
| --- | ---: |
| Dashboard first render | 1.994 |

After T4, verbatim table:

| import target | cumulative us |
| --- | ---: |
| reportlab | 0 |
| services.reporting | 0 |
| services.export | 0 |
| ui.pages.reports | 0 |
| ui.pages.agent_control_center | 0 |
| ui.pages.ai_designer | 0 |
| ui.pages.security_analysis | 0 |
| app (total cumulative) | 1564059 |

| measurement | seconds |
| --- | ---: |
| Dashboard first render | 1.363 |

Measured delta: app cumulative import `2327519` to `1564059` us; Dashboard
first render `1.994` to `1.363` s. All seven deferred targets are absent from
`sys.modules` after a cold `import app`; PDF/report/export modules load on
first use. All six `@st.cache_data` decorators remain bounded with
`max_entries=8` and `show_spinner=False`; `tests/unit/test_cold_start.py`
asserts both properties.
