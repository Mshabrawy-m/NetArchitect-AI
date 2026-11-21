# V2 Specification (reference for later V2 prompts)

This is the shared reference for the v2 work on `feature/v2-tech`. It records the
roadmap and the non-negotiable Community Cloud Free constraints. This package
itself adds **no features, no UI changes, no schema changes, and no runtime
dependencies**: it only improves speed, install size, and the verification
safety net.

## Free-tier rules (non-negotiable)

- Target is Streamlit Community Cloud Free: about 1 GB RAM and a slow cold start.
- No background workers or threads, no disk writes by the app, no always-on
  services, and no paid services.
- `requirements.txt` is the only file Cloud installs. Never add `-c` or `-r`
  lines to it; a `-c constraints.txt` line already broke a deploy once.
- Keep `requirements.txt` flat with exact `==` pins and `pyarrow` pinned inline.
  `requirements-dev.txt` may start with `-r requirements.txt` and holds only
  development tools (pytest, ruff, Hypothesis).
- No new runtime dependencies. New checks and benchmarks belong in dev tools or
  scripts, not in the deployed import path.
- Session state and caches stay bounded; no cache may grow past a few tens of MB.

## Roadmap

### 2.0 - Design and UX

- Refresh the 15-page information architecture and navigation for clarity.
- Standardize page headers, empty states, notes, and disclosure wording.
- Improve accessibility and responsive layout without adding UI dependencies.
- Keep deterministic engineering results and the no-key path unchanged.

### 2.1 - Simulation and optimization power

- Speed up routing, reachability, path extraction, and per-candidate evaluation
  while preserving exact deterministic results.
- Reuse per-run precomputation (adjacency arrays, candidate pool) inside a
  seeded optimization run.
- Keep equal-cost tie-breaking, directed/undirected semantics, and failure
  handling identical to v1.
- Expand what-if models and search comparisons only with explicit model notes
  and bounded work.

### 2.2 - Copilot

- Make optional AI assistance helpful for explanation, clarification, and
  navigation, never a source of computed engineering values.
- Keep the structured no-key workflow authoritative; provider prose remains
  labeled and audited.
- Enforce allowlists, budgets, redaction, and typed provider failures.

### 2.3 - Advanced design-time security

- Extend the offline catalog, policy checks, and flow analysis with fixed,
  reviewed rules and visible arithmetic.
- Keep output design-time only: no scanning, probing, exploit content, or device
  access.
- Continue deriving proposals that stay inert until explicitly accepted.

### 2.4 - Wider engineering coverage

- Add more bounded design checks and domains (for example capacity models and
  resilience metrics) using the same typed finding/provenance contract.
- Preserve the current twin, routing, and reporting schemas unless a later task
  explicitly approves and documents a change.
- Prefer deterministic pure functions and existing engines over new packages.

### 2.5 - Reports, bundle, and CLI

- Improve deterministic reports, in-memory bundles, and export provenance.
- Consider a small local CLI for batch checks and exports, kept out of the
  Streamlit runtime import path.
- Keep all reports in-memory on Cloud; never require a writable disk.

## V2 engine additions (feature/v2-engine)

The engine work on `feature/v2-engine` implements roadmap items 2.1 and 2.4 with
additive, deterministic, modeled estimates. It obeys the same free-tier rules:
no new runtime dependency, no worker or thread, no disk write by the app, and
bounded session/cache/sweep state. The default path remains byte-identical to
the v1 engine: an old twin JSON, an old run JSON, and their fingerprints are
unchanged.

- **E1 - routing modes.** `single_path` remains the default. `ecmp` splits a
  demand equally across all deterministic lowest-cost paths up to
  `MAX_ECMP_PATHS`, with an explicit truncation warning. Directed links carry
  only their forward share; undirected links sum both directions against one
  capacity. Unserved reasons are unchanged.
- **E2 - capacity-aware admission.** A deterministic largest-first admission
  model accepts demands on the lowest-cost path with residual capacity and reports
  `unserved: insufficient capacity` with the best blocked path when none fits.
  This is an admission-control model, not a routing protocol.
- **E3 - bounded failure sweeps.** N-1 covers links and devices up to
  `MAX_NODES`/`MAX_EDGES`. N-2 uses a caller-chosen subset capped by
  `MAX_N2_PAIRS`. Additive shared-risk groups expand targets, not case counts.
  Slice-based `st.fragment` rendering, Cancel, real progress, a typed stop reason,
  and "showing X of Y" stay on the script thread.
- **E4 - bounded optimization.** A seeded simulated-annealing algorithm supports
  an optional hybrid start from retained greedy/baseline candidates. Bounded
  demand/capacity sensitivity re-evaluates a small candidate subset and reports a
  candidate as robust only when it is feasible in the source run and every
  completed perturbation scenario and stays within the documented score
  tolerance. Weight changes re-rank only stored Pareto evaluations; no candidate
  is re-evaluated and no infeasible design is recommended.
- **E5 - UI and report wiring.** Simulation Lab exposes routing mode, shared-risk
  groups, mode comparison, and failure sweeps. Optimization Center exposes the
  seeded annealer, hybrid start, sensitivity, and instant re-ranking. Reports can
  select those results, print their provenance and not-run states, and keep the
  consistency checker green.

All added fields are optional and default to legacy behavior. New schema names
are `RoutingMode`, `PathSplit`, `SimulationAssumptions.routing_mode`,
`DemandEvaluation.splits`, blocked-path fields on demand evaluations and
unserved demands, `SharedRiskGroup`, `DigitalTwin.shared_risk_groups`, the sweep
case/plan/impact/result models, `Algorithm.simulated_annealing`,
`RerankedCandidate`, `ParetoReranking`, `SensitivityScenario`, `SensitivityCase`,
`SensitivityScenarioResult`, and `SensitivityReport`. `TWIN_SCHEMA_VERSION`
remains `2`.
