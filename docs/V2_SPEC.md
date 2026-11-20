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
