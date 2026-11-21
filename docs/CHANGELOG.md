# Changelog

All notable changes to NetArchitect AI are recorded here. Dates are ISO-8601.

## 2026-11-21 - S6: integrated design-time security workflow on feature/v2-security

### Added
- S6: ten-tab Security Analysis page (Zones, Policy, Flow check, Reachability,
  Segmentation, Optimizer, Zero-trust, Findings, Checklist, Templates) using new
  EN/AR catalog keys, theme-backed status chips, versioned editor keys, and a
  fingerprint-keyed bounded analysis cache.
- Deterministic C3 "why?" requests for blast radius and segmentation score;
  explicit Optimizer and Zero-trust apply actions that create a NEW twin and one
  C4 decision each (`optimization_candidate_selected` or
  `security_proposal_accepted`).
- Critic handling for `REACH-` codes and S1 exposure findings in the existing
  deterministic gate, with selective re-plan to the security step. Report
  Security additions now carry step/tool provenance and pass numeric consistency
  checks.
- Focused coverage for page tabs/apply flows, reachability/score explanations,
  Critic exposure, report provenance/consistency, i18n parity, fingerprint cache,
  and forbidden network/process imports and tokens.

### Changed
- No schema version bump (`TWIN_SCHEMA_VERSION` stays `2`); S6 is UI and wiring
  only. The cache's optional fingerprint argument preserves existing callers.
  No new runtime dependency, thread, worker, or app disk write.

### Evidence
- Focused S6 tests: `60 passed in 6.81s`.
- `pytest -q`: `1270 passed, 6 deselected in 47.72s`.
- `ruff check .`: `All checks passed!`.
- `pytest -q -m smoke`: `13 passed, 1263 deselected in 6.44s`.
- Live Streamlit agent API: health `ok`; all 10 tabs rendered with no exceptions
  and no server warnings; server stopped afterward.
- Not verified: real-browser rendering, Cloud deployment, Linux CI.

## 2026-11-21 - S5: fixed design checklist on feature/v2-security

### Added
- S5: fixed, versioned (`1.0`) eight-item design checklist with stable IDs, fixed
  text, explicit rule linkage, evidence, and only `pass` / `fail` /
  `not-modeled` statuses derived from modeled facts.
- Additive optional `SecurityAnalysis.checklist` field. The logging item is
  always `not-modeled` because the design model has no logging field.

### Changed
- No schema version bump (`TWIN_SCHEMA_VERSION` stays `2`); no new runtime
  dependency, thread, worker, or app disk write. Wording is limited to a design
  checklist aligned with common practice (design-level); no compliance claim.

### Evidence
- `pytest -q`: `1260 passed, 6 deselected in 51.13s`.
- `ruff check .`: `All checks passed!`.

## 2026-11-21 - S4: zero-trust microsegmentation on feature/v2-security

### Added
- S4: inert microsegmentation suggestions for high-criticality zones. Allow
  rules are strictly limited to demand-implied zone pairs and named services;
  lower-trust pairs with no modeled need get explicit denies. Each suggestion
  shows before/after segmentation score, reachable pair count, and max criticality
  reached.
- Additive optional `SecurityAnalysis.microsegmentation` field and bounded
  `MAX_MICROSEGMENTATION_PROPOSALS=4`, `MAX_MICROSEGMENTATION_RULES=48`.
- Explicit selection creates a NEW twin and can emit a C4
  `security_proposal_accepted` decision through an injected callback.

### Changed
- No schema version bump (`TWIN_SCHEMA_VERSION` stays `2`); no new runtime
  dependency, thread, worker, or app disk write. Described as design-level
  alignment with common practice only, with no compliance claim.

### Evidence
- `pytest -q`: `1249 passed, 6 deselected in 47.72s`.
- `ruff check .`: `All checks passed!`.

## 2026-11-21 - S3: deterministic policy optimizer on feature/v2-security

### Added
- S3: inert, deterministic policy proposals (merge duplicates, remove
  shadowed/redundant, reorder specific-before-any, tighten any-service, explicit
  default deny) with a full finite decision-table equivalence proof and explicit
  behavior-changing flags.
- Additive optional `SecurityAnalysis.optimizer` field and bounded
  `MAX_OPTIMIZATION_PROPOSALS=12`.
- Explicit selection applies proposals to a NEW twin and emits one optional C4
  `optimization_candidate_selected` decision via an injected callback.

### Changed
- No schema version bump (`TWIN_SCHEMA_VERSION` stays `2`); no new runtime
  dependency, thread, worker, or app disk write. Proposals are inert until
  explicitly applied and never generate device configuration or commands.

### Evidence
- `pytest -q`: `1241 passed, 6 deselected in 48.94s`.
- `ruff check .`: `All checks passed!`.
- Bounded Hypothesis cross-check against `evaluate_policy` in
  `tests/property/test_security_optimizer.py` passed.

## 2026-11-21 - S2: visible segmentation score on feature/v2-security

### Added
- S2: deterministic 0--100 segmentation score with the complete formula in the
  `security.segmentation` module docstring and every weighted input returned in
  `SegmentationScore.inputs` for hand checking.
- Additive optional `SecurityAnalysis.segmentation` field; legacy analysis JSON
  without the key still parses.

### Changed
- Criticality weighting is stated exactly as c/5 and applies only to the trust
  term; the exposure threshold remains a separate S1 finding. No schema version
  bump, runtime dependency, thread, worker, or app disk write.

### Evidence
- `pytest -q`: `1228 passed, 6 deselected in 44.13s`.
- `ruff check .`: `All checks passed!`.

## 2026-11-21 - S1: policy reachability and blast radius on feature/v2-security

### Added
- S1: deterministic, offline `security/reachability.py` with a zone x zone x
  service modeled policy reachability matrix, bounded transitive-closure blast
  radius, and exposure highlights for lower-trust zones reaching criticality >= 4.
- Additive optional `SecurityAnalysis.reachability` field; legacy analysis JSON
  without the key still parses, and twin JSON/fingerprints are unchanged.
- Bounded constants `MAX_BLAST_RADIUS_HOPS` and `MAX_ROUTE_PROBE_DEVICES`.

### Changed
- No schema version bump (`TWIN_SCHEMA_VERSION` stays `2`); no new runtime
  dependency, thread, worker, or app disk write. Results are labeled policy
  reachability, never an attack path or exploit chain.

### Evidence
- `pytest -q`: `1219 passed, 6 deselected in 49.51s`.
- `ruff check .`: `All checks passed!`.
- `pytest -q -m perf -o addopts= ...::test_s1_max_zone_count_timing -s`:
  `S1 max-zone reachability (32 zones, 32 services): 0.241s`.

## 2026-11-21 - C1-C5: deterministic copilot on feature/v2-copilot

### Added
- C1: optional EN/AR sentence interpretation in Simulation Lab with a
  deterministic-first parser, typed audited drafts, editable preview, and no
  execution before confirmation.
- C2: deterministic improvement suggestions from SPOF, overloaded links,
  security design issues, and failure sweeps; exact before/after metrics and
  explicit apply-to-new-snapshot confirmation.
- C3: auditable "why?" explanations for routes, findings, simulation results,
  and optimization candidates; deterministic text always present, optional AI
  prose labeled and audited.
- C4: bounded typed decision log with injected timestamps, Digital Twin JSON
  export, and a provenance-tagged `design_decisions` report section.
- C5: Settings cache/budget/trace visibility, a 24-case EN/AR golden eval set
  using `FakeProvider`, and a local-only redacting response recorder.

### Changed
- No persisted schema version bump: `TWIN_SCHEMA_VERSION` stays `2`; all copilot
  additions are additive and key-free flows remain complete.
- Report section order now includes `design_decisions` before `assumptions`.
- No new runtime dependency, thread, worker, or app disk write; cache, trace,
  decision, and golden-eval state stay bounded and secret-free.

### Evidence
- `pytest -q`: `1213 passed, 5 deselected in 43.92s`.
- `ruff check .`: `All checks passed!`.
- `pytest -q -m smoke`: `13 passed, 1205 deselected in 5.80s`.
- `pytest -q tests/eval`: `25 passed in 0.87s` (24 golden cases + coverage check).
- Not verified: live Groq responses, browser rendering, and Cloud deployment.

## 2026-11-21 - E1-E5: bounded engine power and UI/report wiring

### Added
- E1: `RoutingMode`, `PathSplit`, bounded ECMP path enumeration, equal split,
  truncation warnings, and explicit directed/undirected load rules. Legacy
  twin/run JSON and fingerprint fixtures prove byte compatibility.
- E2: capacity-aware admission control with exact blocked-path fields, the
  `insufficient capacity` reason, and deterministic side-by-side mode comparison.
- E3: `SharedRiskGroup` on the twin, bounded N-1/N-2 failure sweeps, typed case
  plans/impacts/results/stop reasons, slice JSON/CSV exports, and an `st.fragment`
  page flow with real progress, Cancel, and "showing X of Y".
- E4: seeded simulated annealing with an optional hybrid start, bounded
  demand/capacity sensitivity with a precise robust definition, and pure Pareto
  re-ranking from stored evaluations only.
- E5: bounded session stores/accessors, 60 new EN/AR catalog keys, Simulation Lab
  routing/SRG/comparison/sweep controls, Optimization Center SA/hybrid/rerank/
  sensitivity controls, and four provenance-tagged report sections.

### Changed
- No schema-version bump: `TWIN_SCHEMA_VERSION` remains `2`; every added field is
  optional and defaults to the legacy result. GA/NSGA-II seeded vectors and the
  pre-E4 optimization JSON/hash fixture are unchanged.
- The report section order is now architecture, topology, addressing, VLAN/DHCP,
  routing, graph, simulation, capacity, optimization, failure sweep, mode
  comparison, sensitivity, re-ranking, security, assumptions, limitations, and
  agent trace. Missing E5 sources render as `not_run` with producing pages.
- `docs/V2_SPEC.md` records the additive engine contract. No runtime dependency,
  worker, thread, or app disk write was added; caches and session stores stay
  bounded.

### Evidence
- `pytest -q`: `1130 passed, 5 deselected in 40.59s`.
- `ruff check .`: `All checks passed!`.
- `pytest -q -m smoke`: `13 passed, 1122 deselected in 5.87s`.
- `pytest -q -m perf`: `5 passed, 1130 deselected in 10.85s`.
- Focused E5: i18n 9 passed, state 7 passed, reporting/cache 43 passed, UI
  pages 26 passed. EN/AR parity `True`; missing keys `()`.
- N-1 sweep: medium `0.355934 s` direct to `0.140281 s` sweep; max `1.339096 s`
  direct to `0.648555 s` sweep. Not verified: browser rendering, Cloud timing/
  RSS, Linux CI.

## 2026-11-21 - D5: accessibility and consistent formatting

### Added
- `ui/formatting.py`: bounded number, percentage, ratio, Mbps, ms, signed-delta,
  and missing-value formatting with LTR isolation for Arabic sessions.
- `ui/components/feedback.py`: one shared spinner for bounded synchronous
  provider, workflow, connection, CSV, forecast, capacity, and scenario actions.
- `tests/unit/ui/test_d5_accessibility.py`: static checks for visible widget
  labels, full-width tables, shared error formatting, one RTL stylesheet, and
  text contrast >= 4.5:1; behavioral checks for status text, congestion labels,
  and English/Arabic numeric formatting.

### Changed
- Simulation metrics, topology hover/inspector values, forecast tables, twin
  diffs, optimization scores, and Dashboard ratios now use the shared formatters.
- Congestion bars carry visible level labels and hover text, so color is not the
  only cue. Long-running actions show one loading message on the script thread.
- Domain errors in capacity, digital twin, security, settings, AI designer, and
  Simulation Lab use `format_error`. No thread, worker, disk write, cache,
  engine, schema, export, PDF, or runtime dependency was added.

### Evidence
- Focused UI tests: 153 passed.
- `pytest -q`: 1048 passed/3 deselected.
- `pytest -q -m smoke`: 12 passed/1039 deselected.
- `ruff check .`: All checks passed!
- Fresh runtime-only venv: health `ok`, root status 200, 15 pages rendered by
  `scripts/verify_runtime_only.py`, pytest absent.
- Final clean profile imports: app total `1459589` us; Dashboard first render
  `1.340` s.

## 2026-11-21 - D4: ar/en interface and RTL

### Added
- `ui/i18n.py`: one ar/en catalog with parity checks, English fallback,
  normalized session language codes, RTL detection, a scoped direction
  stylesheet, and Unicode isolates for Latin engineering terms and numerics.
- Settings language segmented control persisted to the session only. Dashboard,
  navigation, progress, shared components, health, and topology wording now
  come from catalog keys.
- `tests/unit/ui/test_i18n.py`: catalog parity, missing-key and malformed-
  placeholder fallback, engineering-term LTR isolation, RTL direction helpers,
  Arabic first render in AppTest, and Settings toggle back to English.

### Changed
- Raw English UI defaults were kept where tests depend on exact wording, so
  D1-D3 assertions still pass in the default English session.
- The About-menu release test now checks `i18n.EN["app.about"]` instead of
  scanning `app.py`; the wording moved into the catalog without changing it.
- PDF, export, engine, schema, and dependency behavior was not changed.

### Evidence
- `i18n.catalog_parity()` True; `i18n.missing_translation_keys()` empty.
- Focused UI tests: 81 passed.
- `pytest -q`: 1038 passed/3 deselected.
- `pytest -q -m smoke`: 12 passed/1029 deselected.
- `ruff check .`: All checks passed!
- Fresh runtime-only venv: health `ok`, root status 200, 15 pages rendered by
  `scripts/verify_runtime_only.py`, pytest absent.

## 2026-11-21 - D3: layered topology UX

### Added
- `ui/topology_view.py`: deterministic bounded layered layout, device-type
  marker shapes, stable zone colors, role/utilization color modes, a fixed
  metadata legend, bounded label thinning, and hover details for devices/links.
- Plotly point selection for devices and link midpoints, a keyboard-reachable
  entity picker, an inspector with properties, and quick actions that queue
  node/link failure scenarios in the existing Simulation Lab session keys.
- Two alternating Plotly chart keys so selection can be cleared or replaced
  without assigning a mounted widget key; no new session state grows per click.
- Focused tests for deterministic tier order, bounded coordinates, symbol and
  legend coverage, color tokens, hover/selection metadata, inspector actions,
  and clearing selection.

### Changed
- `ui/pages/topology_editor.py` now delegates only its diagram section to
  `render_topology_view`. Generators, table editors, JSON import/export, and
  twin-consistency reporting are unchanged.
- The old NetworkX spring-layout figure and role-only color map were removed;
  no engine, schema, or runtime dependency changed.

### Evidence
- Focused tests: 11 passed.
- `pytest -q`: 1030 passed/3 deselected.
- `pytest -q -m smoke`: 12 passed/1021 deselected.
- `ruff check .`: All checks passed!
- Fresh runtime-only venv: health `ok`, root status 200, 15 pages rendered by
  `scripts/verify_runtime_only.py`, pytest absent.
- Live Streamlit agent API: Topology page generated a star topology, exposed
  Color by / Inspect entity / Clear selection, and reported no exceptions or
  server warnings.

## 2026-11-21 - D2: guided workflow and sample projects

### Added
- `ui/progress.py`: a six-step Project progress strip (Design, Addressing,
  Validate, Simulate, Optimize, Report) rendered above the selected page. Each
  step links to its page and shows Done, Incomplete, or Stale; Stale means the
  retained result fingerprint differs from the current twin.
- `ui/sample_projects.py` and Dashboard quick start: three labeled sample
  twins (small office, campus, spine-leaf DC) built from existing generators,
  VLSM/VLAN/DHCP engines, and the twin model. A select action stores a pending
  key only; a confirm action replaces the twin with a new one, and cancel
  leaves the current twin unchanged.
- Read-only session accessors and bounded source-fingerprint maps in
  `ui/state.py`; subnet checks record their twin fingerprint in
  `ui/pages/ip_addressing.py`.

### Changed
- `app.py` renders the progress strip before `page.run()` so Dashboard and the
  main engineering pages share the same workflow context.
- No existing test assertion was changed in D2. New tests cover Done,
  Incomplete, and Stale progress states with crafted session data, six ordered
  page links, deterministic/valid samples, and rejection of unconfirmed loads.
  The optimizer fixture in the progress tests uses the a-b-c-d pool twin so the
  candidate links have valid endpoints; source fingerprints are still supplied
  explicitly by the crafted session data.

### Evidence
- Focused UI tests: 50 passed.
- `pytest -q`: 1020 passed/3 deselected.
- `pytest -q -m smoke`: 12 passed/1011 deselected.
- `ruff check .`: All checks passed!
- Fresh runtime-only venv: health `ok`, root status 200, 15 pages rendered by
  `scripts/verify_runtime_only.py`, pytest absent.

## 2026-11-21 - D1: design system and navigation

### Added
- `ui/theme.py`: one token module with light/dark palettes, semantic status
  colors, role and zone colors, a spacing scale, and WCAG contrast helpers.
- Shared `ui.components` helpers: `metric_tile`, `status_badge`,
  `section_header`, `callout`, `empty_state`, and `key_value_list`.
- `ui/navigation.py` and 15 thin `app_pages/` entry files for native grouped
  `st.navigation`/`st.Page` navigation.

### Changed
- `.streamlit/config.toml` now declares paired light and dark themes with one
  typeface. Plotly colors in four UI pages use theme tokens instead of raw hex.
- `app.py` no longer renders a `page_nav` selectbox. The Dashboard render
  function moved to `ui/pages/dashboard.py` and is unchanged in behavior.
- Navigation tests switch through registered page files. The prior assertion
  that Security immediately followed Capacity in the flat selectbox order was
  removed because the specified group order places Security in Analyze before
  Capacity in Operate. New assertions cover the exact groups and page labels.

### Evidence
- `pytest -q` 1006 passed/3 deselected; `pytest -q -m smoke` 12 passed/
  997 deselected; `ruff check .` clean.
- A token scan test fails if any raw hex color appears in `ui/` outside
  `ui/theme.py`; a contrast test asserts every text token pair is >= 4.5:1.

## 2026-11-20 - T5: bounded Hypothesis properties

### Added
- `tests/property/` with eight bounded properties for VLSM (IPv4/IPv6),
  deterministic shortest-path walks under failures, twin JSON/fingerprint and
  legacy-v1 round trips, CSV formula neutralization, and optimizer hard-constraint
  infeasibility.
- Shared `BOUNDED` Hypothesis settings: 50 examples, `derandomize=True`, and no
  deadline, so default and smoke runs stay deterministic and bounded.

### Evidence
- `pytest -q` 1000 passed/3 deselected; `pytest -q -m smoke` 12 passed/
  991 deselected; `pytest -q -m perf` 3 passed/1000 deselected;
  `ruff check .` clean.
- A local 1000-example probe of the same properties passed. No product bug was
  found; one incorrect IPv6 prefix assertion in the new test itself was
  corrected before commit.

## 2026-11-20 - T4: cold-start lazy imports

### Added
- `scripts/profile_imports.py` measures fresh `import app` cumulative import
  time and one clean Dashboard `AppTest` render.
- `tests/unit/test_cold_start.py` asserts that cold app import defers report,
  export, PDF, and four rarely used page modules; that PDF helpers load only on
  first use; that public function names survive submodule loading; and that all
  six `st.cache_data` decorators stay bounded.

### Changed
- `app.py` imports page modules inside the selected branch instead of at module
  import. Dashboard cold start no longer imports report, agent, security, or
  other rarely used pages.
- `services/export/__init__.py` resolves every public export through module-level
  `__getattr__`, keeping ReportLab and report modules out of cold start. A
  shadow-restore step keeps `config_templates` and `csv_tables` callable after
  their implementation modules load.
- `ui/cache.py` imports reporting and export helpers only inside cached
  functions. No cache bound, schema, feature, UI, or runtime dependency changed.

### Evidence
- Against commit `bf2b5b8` on the same host: app cumulative import `2327519` to
  `1564059` us; Dashboard first render `1.994` to `1.363` s. The seven targeted
  import rows are all `0` after the change. Full verbatim tables are in
  `docs/PERFORMANCE.md`.
- `pytest -q` 992 passed/3 deselected; `pytest -q -m smoke` 12 passed/
  983 deselected; `ruff check .` clean.

## 2026-11-20 - T3: sparse routing and per-run precomputation

### Added
- `network/routing/sparse.py`: bounded CSR adjacency arrays built from the same
  arc rules as the NetworkX routing graph. Distances, reachability, and
  components use `scipy.sparse.csgraph`; deterministic path extraction keeps the
  original lexicographic tie-break and directed/undirected semantics.
- `scripts/bench_hotpaths.py`, `tests/routing_reference.py`, sparse equivalence
  tests, and a byte-identical seeded GA/NSGA-II objective-vector fixture from
  commit `3e31a41`.
- `perf` pytest marker and opt-in timing budgets in
  `tests/unit/test_perf_budgets.py`; default and smoke runs exclude them.

### Changed
- `network/routing/paths.py` and `simulation/evaluator.py` now use one sparse
  router per routing signature. `optimization/evaluator.py` shares baseline
  link/pool indexes and the router cache across one seeded run; greedy, GA, and
  NSGA-II reuse that context. No schema, UI, or runtime dependency changed.
- Fixed a real equivalence bug found by the new reference tests: a float
  tolerance in sparse path extraction preferred `a-b-d` (`0.30000000000000004`)
  over the reference's exact `a-d` (`0.3`). Suffix distances now come from the
  candidate neighbor as source and are compared exactly; the minimal topology
  is a regression test.

### Evidence
- Profile: all-pairs 0.970 s to 0.066 s (14.7x); evaluate 0.762 s to 0.045 s
  (16.9x). Bench: 0.974 s to 0.063 s, 0.940 s to 0.082 s, and GA throughput
  1.0 to 10.1 evaluations/sec in the same 5 s budget. Full tables are in
  `docs/PERFORMANCE.md`.
- `pytest -q` 988 passed/3 deselected; `pytest -q -m smoke` 12 passed/
  979 deselected; `pytest -q -m perf` 3 passed/988 deselected;
  `ruff check .` clean.

## 2026-11-20 - V2 package started (feature/v2-tech)

### Added
- `docs/V2_SPEC.md`: short shared reference for the 2.0-2.5 roadmap and the
  non-negotiable Community Cloud Free rules. This package adds no features, UI,
  schema changes, or runtime dependencies.
- `requirements-dev.txt` with pytest, ruff, and Hypothesis; it is the only file
  CI and developers install for tools. `scripts/verify_runtime_only.py` proves a
  runtime-only install starts headless Streamlit and renders all 15 pages
  without pytest.

### Changed
- `requirements.txt` now has nine flat inline pins (pytest and ruff removed).
  README, deployment docs, release pin tests, and CI install the dev file for
  tooling. Cloud still installs only the runtime file.
- Evidence: `pytest -q` 975 passed; `pytest -q -m smoke` 12 passed/963 deselected;
  `ruff check .` clean; fresh runtime-only venv health `ok`, root 200, 15 pages.

## 2026-11-20 - T2: Linux CI and safety gates

### Added
- `.github/dependabot.yml` with weekly pip and github-actions updates.
- `scripts/check_linux_memory.py`: Linux-only VmRSS gate after app import and
  Dashboard render, limited to 450 MB with the rationale in
  `docs/PERFORMANCE.md`.
- Owner checklist for the first Linux CI push in `docs/DEPLOYMENT.md`.

### Changed
- `.github/workflows/ci.yml` now runs on ubuntu-latest: Python 3.11/3.12 dev
  verification, a runtime-only headless/15-page job, and a throwaway-venv
  pip-audit job. No secrets are referenced. GitHub Actions was not run remotely.

### Evidence
- `pytest -q` 975 passed; `ruff check .` clean; the RSS script skips on win32 by
  design and will be exercised on the first Linux CI run.

## 2026-11-19 - Inline pyarrow pin for Community Cloud install

### Changed
- `requirements.txt` now declares eleven inline pins and includes
  `pyarrow==23.0.1` directly. `constraints.txt` was removed so Community Cloud
  installs from a single dependency file. This does not add a runtime dependency;
  Streamlit already requires `pyarrow`.
- The release hardening test now asserts eleven inline packages and the absence
  of `constraints.txt`. README, deployment, test-strategy, limitations, and
  status documents were updated to match.
- This change follows the pushed `v1.0.0-rc1` and `v1.0.0` tags; those tags still
  point at the release commit `b1507f9`.

### Evidence
- `pytest -q -m smoke` and `pytest -q` passed after the change.
- `ruff check .` -> `All checks passed!`.

## 2026-11-18 - v1.0.0-rc1: Release preparation (Phase 15)

### Added
- `tests/unit/release/test_phase15_acceptance.py`: 18 Blueprint acceptance tests covering IP overlap/duplicates, graph-walk route validity, failure exclusion, reproducible simulation and optimization, hard constraints, invalid LLM output, report/computed-value consistency, no-key rendering of all 15 pages, and the security criticality decision.
- `tests/unit/release/test_phase15_hardening.py`: 14 adversarial-input and secret-containment tests covering guarded JSON/CSV/text/identifiers, formula neutralization, prompt-injection tool allowlisting, no dynamic execution or runtime disk writes, gitignore/secrets safety, and exact dependency pins.
- `tests/unit/release/test_phase15_deployment.py`: 5 tests for headless/bounded Streamlit config, CI workflow contents, deployment docs and secrets placeholder, in-app release limitations with no key, and About-menu scope.
- Release documentation: `README.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/AGENT_SPECIFICATIONS.md`, `docs/TEST_STRATEGY.md`, `docs/DEPLOYMENT.md`, `docs/RELEASE_AUDIT.md`, `docs/ROADMAP.md`, and `KNOWN_LIMITATIONS.md`.
- `.github/workflows/ci.yml`: Python 3.11/3.12 matrix running install, lint, full tests, smoke tests, and a deployment-config assertion. Remote execution was not performed.
- In-app Settings > Release limitations and an About menu that identifies `v1.0.0-rc1` and the design-time scope.
- `pytest.ini` defines the optional `smoke` marker.

### Changed
- At the release tag, `requirements.txt` pinned exactly ten direct packages and referenced `constraints.txt`; `constraints.txt` pinned the transitive `pyarrow==23.0.1` wheel. No direct runtime dependency was added. This layout was superseded by the inline-pin change above.
- `core/inputs.py` and `core/csv_safe.py` add bounded, typed parsing and spreadsheet-formula neutralization before Pydantic validation and CSV export.
- Untrusted import/export paths across twin, simulation, forecasting, optimization, security, reporting, and documentation modules use the guarded parsers and neutralizer.
- `.streamlit/config.toml` sets `headless = true`, `maxUploadSize = 2`, and disables usage stats.
- `CURRENT_STATUS.md` records Phase 15 evidence and the remaining owner deployment action.
- Security criticality is documented as a gate for `SEC-DW-009`, not a numeric risk-formula term.

### Evidence
- `pytest -q`: `975 passed in 33.79s`.
- `pytest -q -m smoke`: `12 passed, 963 deselected in 8.55s`.
- `ruff check .`: `All checks passed!`.
- Clean Python 3.11 venv: `975 passed in 38.79s`; `All checks passed!`.
- Clean Python 3.12 venv: `975 passed in 44.79s`; `All checks passed!`.
- `pip-audit -r requirements.txt --progress-spinner off`: `No known vulnerabilities found`.
- Local headless startup: `health: ok`, `agent status: ready`, root title `Dashboard`, `exceptions: 0`.
- Profile rerun: peak traced allocation 8.7 MiB; maximum optimization searches are wall-clock bounded by 60 s.

### Not verified
- Streamlit Community Cloud deployment, real-browser rendering, live Groq requests, PDF visual layout, and remote GitHub Actions execution.

## 2026-11-18 - Phase 14d: Security Analysis UI

### Added
- `ui/pages/security_analysis.py`: 15th application page with Zones, Policy,
  Flow check, Findings, and Templates tabs. It is presentation only: all edits
  go through the immutable security operations, all results come from the
  deterministic engine, and the exact design-time disclaimer is always shown.
- Zones and Policy editors use shared components and versioned widget keys.
  Rejected edits bump the affected key, queue a one-shot error notice, and
  rerun from the stored model rather than leaving rejected rows on screen.
  Zone ids, service names, and rule ids are immutable, and rule references are
  validated before a model is stored.
- Bounded session accessors for modeled flow checks in `ui/state.py`, capped by
  `MAX_SECURITY_FLOW_CHECKS`. `ui/cache.py` adds a content-keyed
  `cached_security_analysis` keyed by canonical twin, model, and flow payloads.
- Findings show visible risk arithmetic, typed findings, the fixed catalog, and
  proposed rules. Proposals are inert until IDs are selected and explicitly
  accepted into a new twin. Templates are vendor-neutral data-only downloads.
- AppTest coverage for the twin-required state, five tabs, flow add/remove,
  accepted and rejected edits, proposal acceptance, and disclosures; cache and
  navigation tests cover the new content key and 15-page sidebar.

### Changed
- `app.py` now lists and dispatches 15 pages, with Security Analysis immediately
  after Capacity Planning. The sidebar caption says all 15 pages are available.
- Changed existing assertions (disclosed): `tests/unit/ui/test_navigation.py`
  now asserts 15 declared pages and the Security Analysis position;
  `tests/unit/ui/test_cache.py` imports the new security cache helpers and adds
  one cache test. No existing assertion was weakened.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `938 passed in
  22.97s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified. The
  catalog is a modeling aid, not an audit standard.

## 2026-11-18 - Phase 14c: Security Agent and integration

### Added
- `agents/security_agent.py`: fifth, strictly allowlisted Security Agent. It may
  call only `security_analysis`; the verdict, risk, findings, and posture are
  copied from that deterministic result. Optional model prose carries the label
  `AI-generated text; not a source of design data.`, and invented numeric tokens
  or out-of-scope terms cause the prose to be rejected in favor of the
  deterministic explanation. The agent never proposes changes silently.
- `agents/tools.py`: registered, schema-validated `security_analysis` tool with a
  `SecurityAnalysisInput` model. `config/limits.py` bounds prose to 1,200
  characters and flow checks to 20.
- Optional 12-step workflow via `include_security=True`; the default remains
  11 steps. The security step runs after re-validation and before the critic.
  The critic independently re-runs the security tool, maps `SEC-*`/`POLICY-*`
  findings to that step, adds a nonblocking `security_high_risk` warning for the
  high band, and treats blocking security findings as a critic rejection. The
  Security Agent declines automatic re-plans so fixes require user acceptance.
- Report Security section with the exact disclaimer, typed values, provenance,
  findings/flow tables, and explicit notes that proposals are inert and templates
  are vendor-neutral data. Documentation and workflow reports include the
  Security section when the optional step runs. The unified design-health pass
  gained a basic `security` category for supplied findings; expensive checks
  remain opt-in.
- Tests for the one-tool allowlist, ToolRegistry validation, determinism,
  AI-label/numeric rejection/provider failure behavior, forbidden imports,
  optional workflow/critic gating, report provenance, and design-health grouping.

### Changed
- Changed existing assertions (disclosed): `test_tool_allowlist_is_exactly_the_independent_checks`
  now includes `security_analysis`; `test_registry_names_are_deterministic`
  asserts the new tool name; `tests/unit/services/test_reporting.py::SECTION_IDS`
  includes `security` between `optimization` and `assumptions`, and the not-run
  section pointer table includes `("security", "Security Analysis")`. No
  assertion was weakened.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `925 passed in
  22.03s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified. The
  catalog is a modeling aid, not an audit standard.

## 2026-11-18 - Phase 14b: deterministic security engine

### Added
- `security/policy.py`: stateless first-match policy evaluation with explicit
  default action, disabled-rule skipping, named-service matching, intra-zone
  handling, and routing-aware `check_flow()` that distinguishes `no_route`,
  `policy_denied`, `unassigned_zone`, and `allowed`.
- `security/catalog.py`: nine fixed, ordered design-weakness rules from
  `SEC-DW-001` to `SEC-DW-009`, covering flat networks, missing management zone,
  public server placement, user-to-restricted paths, guest/IoT reachability,
  boundary SPOF, oversized subnets, unzoned devices, and high-criticality
  segmentation. Base severities are fixed in code, not configurable by UI state.
- `security/risk.py`: visible modeled-risk arithmetic with weights
  `info=0, warning=1, error=4, critical=8`, a `default_action=allow` bonus of 2,
  thresholds `0=low`, `1-3=moderate`, `4-7=elevated`, `>=8=high`, and an
  overall posture of hardened / needs_review / high_risk.
- `security/remediation.py`: inert deny-rule proposals from actionable findings
  and explicit acceptance into a NEW twin; accepted ids are validated before any
  edit and applied in proposal order.
- `security/templates.py`: vendor-neutral data-only records beginning with the
  exact line `TEMPLATE - not applied to any device`; no device syntax or commands.
- `security/engine.py`: `analyze_design()` combines the policy checks, design
  catalog, flow checks, risk, proposals, and template in one deterministic call.
- `tests/unit/security`: four-rule first-match tests, one crafted case per
  catalog rule plus a clean hardened control, policy finding cases, exact risk
  arithmetic and threshold/posture tests, proposal acceptance tests, both
  end-to-end flow failure modes, and template header/data-only tests.

### Changed
- Security output models now inherit a `DisclosedModel` base that requires the
  exact `SECURITY_DISCLAIMER`; findings, decisions, flow checks, risk, template,
  and the complete analysis cannot be constructed with a different label.
- Changed existing assertions: none. 14b adds new tests and new design fixtures;
  it does not alter any assertion from earlier phases.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `904 passed in
  23.74s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified. The
  catalog is a modeling aid, not an audit standard.

## 2026-11-18 - Phase 14a: security models and backward-compatible twin field

### Added
- `security/models.py`: frozen Pydantic models for zones, services, firewall
  rules, and a bounded `SecurityModel`. Validation covers member references,
  criticality range, port ranges, service/rule modes, duplicate ids/orders, and
  `MAX_ZONES`, `MAX_SERVICES`, `MAX_FIREWALL_RULES`, and
  `MAX_SECURITY_ASSUMPTIONS`. The exact disclaimer string is exported as
  `SECURITY_DISCLAIMER`.
- `security/derivation.py`: deterministic default zone derivation from VLAN
  department/name/subnet/purpose and device type/role. Keyword priority is
  fixed, unmatched members stay unassigned, the default policy is deny, and
  explicit guest/IoT boundary deny rules are emitted only when those zones exist.
- `security/operations.py`: immutable-style add/update/remove/reorder operations.
  Every edit is revalidated after copying, references cannot be removed while a
  rule uses them, and each operation returns a NEW twin with schema version 2.
- `tests/unit/security`: model validation/bounds, reproducible derivation,
  NEW-twin operation checks, and a forbidden-import/dynamic-execution audit.
- Tests for legacy schema 1 JSON, omitted security field, unchanged legacy
  fingerprint, schema 2 round-trip, and rejection of schema 3.

### Changed
- `DigitalTwin` gained optional `security: SecurityModel | None`; the schema
  version is 2 and supported versions are 1 and 2. `canonical_payload()` omits
  `security=None`, so legacy JSON and the legacy fingerprint
  `4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c` remain
  unchanged. Newer schemas are rejected by serialization and twin validation.
- `simulation.twin_fingerprint()` now hashes the canonical payload. A stored
  security model changes the fingerprint; an absent one does not.
- Changed existing assertions (disclosed): `test_unsupported_schema_version_is_an_error`
  was renamed to `test_supported_and_future_schema_versions_are_distinguished`
  and now uses version 1 as supported plus the first unsupported version,
  replacing the literal assumption that version 2 was future.
  `tests/unit/services/test_design_health.py::_schema_twin` now uses
  `TWIN_SCHEMA_VERSION + 1` instead of literal 2. No assertion's behavior was
  weakened: both still verify that unsupported schemas produce findings.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `866 passed in
  20.29s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified.

## 2026-11-18 - Phase 14.0: housekeeping and report source freshness

### Owner decision
- The project now has 15 phases: Phase 13 Capacity, Phase 14 Security Analysis,
  and Phase 15 Testing, Security review and Deployment.
- Design-time security analysis of the modeled twin is in scope. Live scanning,
  probing, penetration testing, SOC operations, vulnerability database lookups,
  exploit content, attack steps, and device access remain excluded. Security
  code performs no network I/O.
- The owner explicitly approved the new security models and the optional
  `DigitalTwin.security` field planned for 14a; this approval overrides the
  ask-before-schema-change rule only for those additions. All other public
  schemas remain unchanged.

### Added
- Root blueprint and `AI_INSTRUCTIONS.md` document the 15-phase roadmap, module
  3.11 Security Analysis, the fifth Security Agent, and the Security Analysis
  page. The blueprint's blanket pentest/vulnerability-scanning exclusion was
  replaced with the design-time inclusion and live-operation exclusions.
- Report sections for simulation, capacity, and optimization now include a
  visible warning note when the selected run's source twin fingerprint differs
  from the current twin. Optimization has no persisted fingerprint, so
  `ui/state.py` records its source fingerprint in a bounded session map at run
  creation and `ReportSources` carries it into the builder; no run schema changed.
- Tests for all three source-mismatch warnings, free-tier default limits, and a
  content-keyed state accessor for optimization source fingerprints.

### Changed
- `config/limits.py`: `MAX_SCENARIOS` lowered from 50 to 20 for free-tier safety.
  `DEFAULT_OPTIMIZATION_RUNTIME_SECONDS=20` was added and used by
  `OptimizationSettings` and the UI; `MAX_OPTIMIZATION_RUNTIME_SECONDS` remains
  60 as the hard cap, so users can still raise the budget.
- `tests/unit/optimization/helpers.py` now uses the new default constant instead
  of a literal 30 seconds. No existing assertion pinned the old 50/30 defaults;
  the 14.0 tests add explicit 20/20/60 assertions instead.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `847 passed in
  20.74s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified.

## 2026-11-18 - Phase 13c: capacity UI and report integration

### Added
- `ui/pages/capacity_planning.py`: four-tab Data/Forecast/Capacity/Downloads
  workflow using strict CSV input or a deterministic labeled SYNTHETIC generator,
  statistical forecasts, bounded capacity evaluation against copies of the
  current twin, and in-memory downloads. The visible note states that outputs
  are modeled projections, not measurements or guarantees.
- Optional report section `capacity` with source fingerprint, data labels,
  forecast models, stop reason, projected utilization, bottlenecks, tier
  upgrades, and proxy cost deltas. Capacity numbers are registered in the
  sourced-value appendix for consistency checking.
- `capacity/history.py`: bounded ordered `CapacityHistory`; `ui/state.py`
  capacity series/forecast/run accessors; `ui/cache.py` content-keyed
  forecast/capacity caches and an optional capacity payload for cached reports.
- Tests: four-tab AppTest workflow, downloaded artifacts, capacity report
  provenance/consistency/tamper detection, cache reuse, bounded history, and
  report source selection. Full suite: `843 passed in 22.16s`.

### Changed
- Additive schema/API only: `ReportSources.capacity_run`, section id `capacity`
  between `simulation` and `optimization`, `ProjectedDemand.model`,
  `CapacityHistory`, capacity session keys, and the new cache parameters. No
  existing field was removed or renamed. No new dependency or machine learning
  was introduced.

## 2026-11-18 - Phase 13b: capacity projection and evaluation

### Added
- `capacity/`: typed demand mapping (user-count forecasts require a supplied
  `per_user_mbps`), scenario copies of the baseline twin evaluated with the
  existing simulation flow model, congestion-band crossings, ranked bottlenecks,
  horizon-end headroom, smallest-tier upgrade recommendations with `CostModel`
  proxy deltas, insufficient-tier gaps, and bounded typed stop reasons.
- `tests/unit/capacity`: 12 tests covering hand-computed utilization/cost
  values, crossings, twin immutability, mapping findings, synthetic labels,
  evaluation/runtime limits, and JSON provenance.

### Changed
- No existing twin, simulation, or optimization schema changed; the new capacity
  result schemas are additive. Baseline twins are never mutated.

## 2026-11-18 - Phase 13a: forecasting engine

### Added
- `forecasting/`: strict typed CSV parsing with explicit findings and non-silent
  gap policies; deterministic labeled SYNTHETIC generator; NumPy-only naive,
  moving-average, OLS linear, Holt additive, and seasonal-naive models with one
  chronological split, naive baseline comparison, approximate intervals, and
  horizon refusal; deterministic CSV/JSON export carrying provenance.
- `config/limits.py`: bounded forecast inputs/horizons and reserved capacity
  evaluation limits.
- `core/exceptions`: typed forecast and capacity error classes.
- `tests/unit/forecasting`: 18 tests including hand-computed forecast/metric
  values, chronological selection, parsing/gap behavior, synthetic determinism,
  horizon refusal, and exports.

### Changed
- No public schema was removed or renamed; new forecasting schemas are additive.
  Statistical baselines only: no machine learning and no new dependencies.

## 2026-11-18 - Phase 12c: UI consistency and navigation

### Added
- `ui/components`: shared `page_header`, `empty_state`, and
  `model_estimate_note` helpers, plus versioned `st.data_editor` keys and
  one-shot notices that survive the rerun after a rejected edit.
- `ui/pages/capacity_planning.py`: read-only inventory of configured link
  capacity, stated demand bandwidth, and the latest modeled utilization from a
  scenario run on the same twin revision. It performs no forecasting and gives
  no recommendation.
- `tests/unit/ui/test_navigation.py`: 28 AppTest cases covering all 14 nav
  entries with and without a twin, including an assertion that no placeholder
  wording is visible.
- `tests/unit/ui/test_dashboard_page.py`: 3 AppTest cases for the empty
  Dashboard and the populated Dashboard backed by twin, snapshot, scenario,
  and optimization data.
- `tests/unit/ui/test_capacity_planning_page.py`: 2 AppTest cases for the
  required-twin state and the read-only inventory.

### Changed
- Rejected table edits now advance the editor widget version, queue the error
  message, and rerun, so the rejected rows disappear instead of remaining in
  the widget. Applied to topology, simulation demand, optimization pool/tier,
  IP addressing, VLAN, and digital-twin state editors.
- Page titles, notes, empty states, number formats, table column labels, and
  download-button placement were normalized across all pages. Modeled values
  are labeled as estimates, and "coming soon"/"later phase" text was removed.
- The Dashboard now reports only existing twin and session data and hosts the
  single design-health panel. `ui.state` gained read-only `peek_*` accessors so
  viewing the Dashboard does not create empty history stores.
- `app.py` routes all 14 sidebar entries to working pages; no placeholder
  renderer remains.

## 2026-11-18 - Phase 12b: profiling and bounded derived results

### Added
- `scripts/profile_phase12.py`: reproducible wall-clock and tracemalloc
  measurements for topology generation, twin construction, all-pairs routing,
  evaluation, bounded searches, report build, and PDF build.
- `ui/cache.py`: content-keyed caches for design health, report documents, and
  each export; `tests/unit/ui/test_cache.py` and report assertions cover cache
  reuse and invalidation when the twin changes.
- Batched `network.topology.operations.replace_links` and optimizer runtime
  budgeting, with tests for link replacement and configured search limits.
- `ui/state.py`: bounded stable report-timestamp mapping keyed by twin
  fingerprint.

### Changed
- Reports no longer rebuild every export on each rerun. Workflow-backed
  reports build directly from the live workflow; exports remain cached.
- `config/limits.py` documents measured session payload sizes used to set
  history bounds.

## 2026-11-18 - Phase 12a: unified design health

### Added
- `services/validation`: categorized `Finding` records with severity, affected
  entities, remediation, and an expensive-check flag; one deterministic
  design-health report combining addressing, topology, routing, and structural
  checks.
- `ui/components/health.py` and a single design-health panel on the Digital
  Twin and Dashboard pages.
- `tests/unit/services/test_design_health.py`: crafted twin per category, clean
  twin, severity ordering, and constrained-check coverage.

### Changed
- Free-form user constraints are informational; only explicit utilization,
  served-demand-ratio, and no-single-point-of-failure statements are
  machine-checked. All-pairs reachability and redundancy checks report their
  cost and are opt-in.

## 2026-11-15 - Phase 11c: Reports & Documentation page

### Added
- `ui/pages/reports.py`: report page that selects the current twin plus any
  retained workflow, scenario run, or optimization run; lets the user choose
  sections; lists not-run sections with their reason and producing page; runs
  the consistency checker on the selected document; previews typed blocks and
  tables; and shows the bounded source-value registry.
- The page offers in-memory PDF, Markdown, JSON, CSV-table ZIP, and
  configuration-template ZIP downloads, with the PDF font-coverage warning and
  the template-only notice.
- `tests/unit/ui/test_reports_page.py`: 6 AppTest cases covering the empty
  state, populated preview and all downloads, section-limited preview, the
  no-selection guard, a retained workflow, and a retained scenario run.

### Changed
- `app.py`: Reports & Documentation is a ready page, dispatched to the new
  renderer; the sidebar and dashboard text include it.

## 2026-11-15 - Phase 11b: report exports and configuration templates

### Added
- `services/export/common.py`: in-memory export helpers with a fixed ZIP member
  timestamp for byte-stable archives and a shared `MAX_REPORT_BYTES` bound that
  raises `ReportLimitError`.
- `services/export/markdown.py`: deterministic Markdown rendering of the report
  document with escaped table cells, visible truncation notes, and a bounded
  value-provenance appendix.
- `services/export/json_export.py`: stable sorted-key UTF-8 JSON plus
  `from_json`, which validates schema version and structure back into
  `ReportDocument`. The round trip is exact.
- `services/export/csv_export.py`: CSV tables for the IP plan, VLAN
  assignments, DHCP scopes, routing table, link utilization, findings, and
  optimization candidates, an optional documented UTF-8 BOM, and a stable ZIP
  bundle with a README.
- `services/export/config_templates.py`: vendor-neutral device, interface,
  subnet, VLAN, and DHCP-scope templates built only from validated twin data.
  Every file starts with `TEMPLATE - not applied to any device`.
- `services/export/pdf.py`: ReportLab PDF with title block, disclosure labels,
  contents, paginating tables, page numbers, an injected-clock header/footer,
  the exact disclosure footer, bounded layout sizes, deterministic byte output,
  and detect-and-warn fallback for non-Latin text.
- `tests/unit/services/test_export.py`: 18 tests covering JSON round-trip,
  Markdown content and determinism, CSV content/BOM/archive stability and
  truncation reporting, configuration-template headers and twin-only values,
  PDF structure and clock, long-table pagination, visible row and cell
  truncation, non-Latin behaviour, and size limits.

### Changed
- No dependency was added (ReportLab was already present) and no public domain
  schema changed.

## 2026-11-15 - Phase 11a: report document, provenance, and consistency

### Added
- `services/reporting/models.py`: stable `ReportDocument` with ordered,
  typed sections and blocks; per-value and per-table `Provenance`; a
  `ValueRecord` audit appendix; fixed disclosure labels; and a `not_run`
  section status that requires both a reason and the producing page.
- `services/reporting/builder.py`: deterministic report from the digital twin
  plus optional scenario, optimization, and workflow objects. Sections cover
  architecture, topology rationale, addressing, VLAN/DHCP, routing and
  reachability, structural analysis, simulation before/after, optimization
  versus baseline, assumptions, limitations, and the agent execution trace.
  Every printed number is copied from an engine and recorded with step, tool,
  and twin fingerprint. Tables are bounded and keep the source row count.
- `services/reporting/consistency.py`: checker that detects orphan numbers,
  missing disclosure labels, missing provenance, and empty available sections.
- `services/reporting/explain.py`: optional AI explanation with the Phase 10
  numeric-token rejection rule and graceful provider-failure handling.
- `services/reporting/formatting.py` and `templates.py`: deterministic number
  formatting, token extraction with IP/CIDR masking, and explanation templates
  built only from supplied values.
- `tests/unit/services/test_reporting.py`: 24 tests covering engine-matching
  values, not-run pointers, deterministic output, tampering detection, table
  truncation, section filtering, the three run types, and AI explanation
  acceptance/rejection/failure.

### Changed
- `config/limits.py`: added `MAX_REPORT_TABLE_ROWS` and `MAX_REPORT_BYTES`.
- `core/exceptions/__init__.py`: added report error classes.
- No dependency was added and no public domain schema changed.

## 2026-11-14 - Phase 10d: AI Network Designer and Agent Control Center

### Added
- `ui/pages/ai_designer.py`: optional free-text requirements next to the
  structured form. Without an API key the page shows the form only with a note;
  the form runs the complete deterministic workflow.
- Fact/assumption separation, missing and contradictory items, and clarification
  questions are displayed from the requirements agent. Results show the summary,
  critic verdict and findings, documentation preview, assumptions, limitations,
  labelled optional AI text, and report JSON/Markdown downloads.
- Applying a design saves a new snapshot and never replaces the baseline twin.
- `ui/pages/agent_control_center.py`: read-only DAG table with dependencies,
  status, attempts, re-plans, duration, skipped reason, and error; typed stop
  reason; critic findings; full trace with a JSON download; and a source
  selector for multiple session workflows.
- `agents/requirements_agent.py`: `understand_requirements` helper that runs the
  agent once in an isolated single-task context for the UI.
- `tests/unit/ui/test_ai_designer_page.py` (7 tests) and
  `tests/unit/ui/test_agent_control_center_page.py` (5 tests) covering both pages,
  including the key-missing state and secret non-leakage.

### Changed
- `app.py`: wired the AI Network Designer and Agent Control Center into the
  navigation, `READY_PAGES`, and dashboard text.
- `agents/__init__.py`: exported the `understand_requirements` helper.
- No public domain schema changed and no dependency was added.

## 2026-11-14 - Phase 10c: Documentation Agent

### Added
- `agents/documentation.py`: `DocumentationAgent` assembles the validated
  workflow results into a typed report with a summary, topology choice and
  deterministic rationale, addressing/VLAN/DHCP tables, routing summary, critic
  findings, simulation comparison, optimization comparison against the
  baseline, assumptions, limitations, and the full execution trace.
- Every reported value carries `step` and `tool` provenance; the agent copies
  values from task results and never recalculates them.
- Optional model-written explanation, clearly separated from the deterministic
  report. A numeric token that does not match a computed value causes the text
  to be rejected and deterministically replaced; provider failures are ignored.
- `export_json`, `export_csv`, and `export_markdown` deterministic exports. No
  PDF is produced.
- `tests/unit/agents/test_documentation.py`: 14 tests covering the no-provider
  plan, engine-matching values, provenance, copied critic findings, separated
  assumptions and limitations, hostile number rejection, accepted model text,
  provider failure, export round-trip, rejection labelling, trace coverage, the
  empty tool allowlist, and the import guard.

### Changed
- `agents/orchestrator.py`: the standard plan now has eleven tasks with
  `documentation` between `critic` and `report`.
- `agents/network_agents.py`: registered `DocumentationAgent` and added a
  deterministic "Documentation" report section.
- `config/limits.py`: added `MAX_DOCUMENTATION_EXPLANATION_CHARS`.
- `ui/components/requirements_form.py` and the settings-page test now reflect
  the eleven-step plan.
- No public domain schema changed and no dependency was added.

## 2026-11-14 - Phase 10b: Validation and Critic Agent

### Added
- `agents/critic.py`: independent critic that re-runs topology connectivity,
  addressing validation, twin validation, routing reachability, modeled
  load/unserved demands, and SPOF analysis with deterministic tools. It never
  reads another agent's validity claim and never lets model text change the
  verdict.
- Deterministic verdict (`APPROVED`, `APPROVED_WITH_WARNINGS`, `REJECTED`),
  deduplicated findings with severity, entities, explanation, remediation, a
  responsible workflow step, and a blocking flag.
- Optional non-authoritative model summary bounded by
  `MAX_CRITIC_SUMMARY_CHARS`; provider failures and malformed notes are ignored.
- `agents/tools.py`: `twin_load_state` tool exposing modeled link load,
  utilization, and unserved demands to the critic.
- `tests/unit/agents/test_critic.py`: 16 tests covering clean approval,
  disconnected topology, overloaded links, requested-redundancy SPOFs, IP
  overlap mapping, missing twin, LLM verdict immunity in both directions,
  provider failure, prior validity claims, deduplication, tool allowlist, step
  mapping, and a full workflow with a scripted provider.

### Changed
- `agents/orchestrator.py`: the standard plan now has ten tasks with `critic`
  before `report`; critic-origin re-plans honour an explicit target, and an
  unmapped, missing, declined, or over-limit critic re-plan stops with the typed
  `WorkflowStopReason.critic_rejected`.
- `agents/network_agents.py`: registered `CriticAgent` in `default_agents()` and
  added a deterministic "Critic review" report section.
- `agents/models.py`: added `WorkflowStopReason.critic_rejected`.
- `config/limits.py`: added `MAX_CRITIC_SUMMARY_CHARS`.
- `ui/components/requirements_form.py` and the settings-page test now reflect the
  ten-step plan.
- No public domain schema changed and no dependency was added.

## 2026-11-14 - Phase 10a: Requirements Understanding Agent

### Added
- `agents/requirements_agent.py`: bounded free-text extraction into validated
  `NetworkRequirements`, with deterministic number provenance, separate user
  facts and system assumptions, missing/contradictory item detection, bounded
  clarification questions, and typed unavailable/failed outcomes.
- `tests/unit/agents/test_requirements_agent.py`: 16 tests covering valid and
  invented numbers, facts versus assumptions, missing data, contradictions,
  oversized values, repair bounds, provider failure, no-provider paths,
  structured merge, input limits, and the tool allowlist.

### Changed
- `config/limits.py`: added bounded requirements-text, department, list-item,
  and clarification-question limits.
- `agents/__init__.py`: exported the requirements agent and its typed models.
- `tests/unit/agents/test_orchestrator.py`: the agent-package escape-hatch test
  now also rejects `urllib` and `http.client`.
- No public domain schema changed and no dependency was added.

## 2026-11-14 - Phase 9c: Settings page and structured design form

### Added
- `ui/pages/settings.py`: optional AI configuration showing key presence and
  source (never the key), model, session request/token budget, read-only limits,
  a bounded one-request connection test, key-required feature explanation,
  secrets/environment documentation, and session-only key save/clear.
- `ui/components/requirements_form.py`: typed structured requirements form that
  runs the deterministic nine-step agent plan without an LLM and displays task
  statuses, the report, and a downloadable execution trace.
- `ui/state.py`: session accessors for the optional LLM session key and the
  per-session `RequestBudget`.
- `tests/unit/ui/test_settings_page.py`: 8 AppTest tests covering key states,
  absence of key leakage, budget display/reset, injected-provider connection
  tests, an end-to-end form run with an untouched baseline twin, and validation
  errors.

### Changed
- `ui/components.py` became the `ui/components/` package; existing imports are
  unchanged.
- `app.py`: Settings is now ready and routed. Dashboard and sidebar copy updated
  to Phase 9. No other placeholder changed.
- No public domain schema changed and no dependency was added.

## 2026-11-13 - Phase 9b: bounded agent core and deterministic workflow

### Added
- `agents/`: typed `WorkflowTask`/`WorkflowPlan`/`WorkflowState` models, an
  ordered `ExecutionTrace` with an injectable clock, and typed
  `WorkflowStopReason` values for completion, failure, step, runtime, and
  re-plan limits.
- `ToolRegistry` with typed input/output models, a per-agent allowlist, typed
  unknown/disallowed/input/output failures, and wrappers for topology, VLSM,
  VLAN, addressing, routing, analysis/SPOF, twin validation, simulation, and
  optimization engines.
- `BaseAgent`, `AgentContext`, and nine standard deterministic agents.
- `Orchestrator` with cycle and plan validation, dependency-ordered execution,
  bounded attempts, step/runtime caps, failed-task dependent skipping, and
  selective re-planning bounded by `MAX_AGENT_REPLANS`.
- `build_standard_plan`/`run_structured_design`: requirements -> topology ->
  IP/VLAN -> routing -> validation -> simulation -> optimization ->
  re-validation -> report without any LLM call.
- 26 agent-framework tests covering registry contracts, engine parity,
  orchestration bounds, selective re-planning, trace redaction, baseline
  immutability, and the no-LLM deterministic plan.
- `config/limits.py`: `MAX_AGENT_REPLANS`.

### Changed
- `MAX_AGENT_RETRIES` is documented as total attempts including the first.
- No public domain schema changed and no dependency was added.

## 2026-11-13 - Phase 9a: optional Groq provider layer

### Added
- `services/llm/`: provider-independent `LLMProvider.complete` interface,
  typed frozen request/response models, and a `GroqProvider` that uses
  `urllib.request` against the OpenAI-compatible Groq endpoint.
- Typed LLM failures for missing key, authentication, timeout, rate limit
  (HTTP 429 with bounded `Retry-After`/backoff), provider outage, malformed
  response, schema failure after bounded repairs, and budget exhaustion.
- Structured output: JSON extraction without code execution, Pydantic
  validation, and at most `MAX_LLM_REPAIR_RETRIES` repair attempts.
- `services/llm/budget.py`: per-session request and token budget.
- `services/llm/testing.py`: scripted `FakeProvider` test double (not a demo
  mode and not used by the application).
- `config/settings.py`: configurable `GROQ_MODEL` and `GROQ_BASE_URL`; the key
  continues to come from environment variables or Streamlit secrets only.
- `config/limits.py`: LLM call, token, repair, retry, backoff, timeout, and
  response-token limits.
- 15 provider tests, including a secret scan over logs, errors, status, and
  serialized output. No test contacts the network.

### Changed
- `core.exceptions`: typed `LLMError` hierarchy. No public domain schema changed.

## 2026-11-13 - Phase 8c: Optimization Center page, history, and exports

### Added
- `optimization/history.py`: bounded `OptimizationHistory` that honors
  `MAX_OPTIMIZATION_RUNS` and raises `LimitsExceededError` instead of silently
  dropping runs.
- `optimization/export.py`: deterministic sorted-key JSON and standard-library
  CSV exports that include the seed, every setting, limits, stop reason, the
  baseline, and every evaluated candidate.
- `ui/state.py`: `OPTIMIZATION_HISTORY_KEY` and the sole session accessors for
  the optimization history, plus `save_twin_snapshot` for derived designs.
- `ui/pages/optimization_center.py`: candidate-link pool, capacity tiers and
  proxy costs, optional routing-cost multipliers, objective/weight/bound
  selection, every hard constraint, algorithm/seed/population/iterations and
  evaluation/runtime caps, progress status, baseline-versus-optimized deltas,
  trade-off warnings, a two-objective Pareto scatter with the baseline marked,
  candidate feasibility and violations, a bounded inspector with the changes
  from the baseline, explicit snapshot/baseline actions, bounded history, and
  algorithm comparison with stated weights.
- `tests/unit/optimization/test_history_export.py` and
  `tests/unit/ui/test_optimization_center_page.py`.
- `app.py` routes and advertises the Optimization Center.

### Changed
- `optimization/__init__.py` exports the history and export helpers.
- No public domain schemas were changed; optimization inputs and results stay in
  `optimization/models.py`.

## 2026-11-13 - Phase 8b: seeded GA, NSGA-II, and comparison

### Added
- `optimization/algorithms/`: canonical integer genome, random generation,
  uniform crossover, bounded mutation, tournament selection, constrained
  domination, non-dominated sorting, crowding distance, and exhaustive
  enumeration for tiny spaces.
- Seeded Genetic Algorithm with elitism and explicit constrained feasibility
  handling, and seeded NSGA-II whose selection uses no weights and whose
  reported front is the true rank-0 feasible front over every evaluated
  candidate.
- `optimization/algorithms/budget.py`: baseline evaluation precedes the search
  clock; search stops cleanly at `max_evaluations` or the runtime limit with a
  typed `StopReason`.
- `optimization/algorithms/dispatch.py`: one result shape for greedy, genetic,
  and NSGA-II. Particle Swarm Optimization is intentionally omitted because a
  continuous velocity has no sound mapping onto discrete link-presence, tier,
  and multiplier decisions.
- `optimization/compare.py`: baseline-versus-algorithm comparison with
  per-objective change, trade-offs, Pareto sets, and weights stated alongside
  any weighted recommendation.
- Tests for brute-force Pareto equality, dominance and crowding arithmetic,
  reproducibility, limit stop reasons, and baseline immutability.

### Changed
- No public domain schemas were changed.

## 2026-11-13 - Phase 8a: bounded design space, objectives, constraints, and greedy

### Added
- `optimization/models.py`: deterministic serializable `Candidate` (pool links,
  one capacity tier per link, optional routing-cost multipliers), objective
  definitions, weighted objective specs with fixed normalization bounds,
  `OptimizationSettings`, every `HardConstraints` field, candidate evaluations,
  and a complete `OptimizationRun` with algorithm, seed, settings, limits,
  typed stop reason, baseline, candidates, and notes.
- `optimization/space.py`: `build_candidate_twin` applies decisions through
  `digital_twin` without mutating the baseline; `candidate_changes` reports
  deterministic human-readable changes.
- `optimization/objectives.py`: min-max normalization with stated bounds and
  documented proxy infrastructure cost arithmetic.
- `optimization/constraints.py`: every hard constraint is checked separately
  from objectives; infeasible candidates are recorded but never recommended.
- `optimization/evaluator.py`: `evaluate_candidate` reuses the existing
  simulation evaluator, caches by candidate hash per run, and counts
  evaluations and cache hits separately.
- `optimization/greedy.py`: deterministic hill-climb baseline that accepts only
  strictly improving feasible one-change moves.
- `config/limits.py`: `MAX_EVALUATIONS`, `MAX_OPTIMIZATION_RUNTIME_SECONDS`,
  `MAX_OPTIMIZATION_RUNS`, `MAX_POPULATION`, and `MAX_OPTIMIZATION_ITERATIONS`.
- 44 tests under `tests/unit/optimization/`.

### Changed
- `core.exceptions` adds `OptimizationError`, `OptimizationValidationError`, and
  `OptimizationRuntimeExceeded`.
- No public domain schemas were changed; the optimization-specific inputs and
  results are local to `optimization/models.py`.

## 2026-11-13 - Phase 7c: Simulation Lab page

### Added
- `ui/pages/simulation_lab.py`: baseline demand editor, scenario builder for all
  scenario types, valid/invalid scenario feedback, configurable thresholds and
  delay assumptions, before/after metrics, colored link comparison, utilization
  bar chart, path-change and unserved tables, deterministic Plotly topology with
  failed/congested highlights, bounded session history, two-result comparison,
  and JSON/CSV exports.
- `tests/unit/ui/test_simulation_lab_page.py`: empty state, demand editing,
  validation failure, and retained-run comparison/export smoke tests.
- `app.py` routes the Simulation Lab and advertises it in the sidebar/dashboard.

### Changed
- `simulation/tables.py`: absent before/after utilization values are `None`
  instead of `"not present"` so the table remains Arrow-compatible.
- No public domain schemas were changed.

## 2026-11-13 - Phase 7b: scenario engine, history, and exports

### Added
- `simulation/scenarios.py`: explicit `ScenarioPlan` validation for link/node
  failures, bandwidth reduction, traffic increase, expansion, routing-cost
  change, and redundancy/recovery tests; `ScenarioRun`, `ScenarioComparison`,
  `PathChange`, and `LinkChange`; deterministic `run_scenario` and
  `compare_runs` with twin fingerprints, assumptions, thresholds, and no
  timestamps.
- `simulation/history.py`: bounded `ScenarioHistory` that honors
  `MAX_SCENARIOS` and raises instead of silently dropping runs.
- `simulation/export.py`: deterministic sorted-key JSON and standard-library
  CSV exports; `simulation/tables.py` adds `link_comparison_rows`.
- `ui/state.py`: `SIMULATION_HISTORY_KEY` and the sole session accessors for
  the scenario history.
- 33 unit tests under `tests/unit/simulation/test_scenarios.py`.

### Changed
- No public domain schemas were changed; scenario-specific inputs use the
  existing `Scenario.parameters` dict.

## 2026-11-13 - Phase 7a: abstract flow evaluator

### Added
- `simulation/models.py`: frozen `NetworkState`, `DemandEvaluation`,
  `UnservedDemand`, `LinkLoad`, `SimulationAssumptions`,
  `CongestionThresholds`, and `TwinReference`, plus the mandatory `MODEL_NOTE`.
- `simulation/evaluator.py`: deterministic single-path flow evaluation over an
  unmodified digital twin, shared undirected link capacity, directed-link
  asymmetry, unclamped utilization, configurable congestion bands, explicit
  unserved reasons, connectivity summary, optional latency from per-link delay
  assumptions, twin fingerprinting, and a typed runtime guard.
- `simulation/tables.py`: UI-agnostic link, demand, unserved, metric, and path-
  change rows.
- `config/limits.py`: `MAX_SCENARIO_ELEMENTS = 50`; `core.exceptions` adds
  `SimulationError`, `SimulationRuntimeExceeded`, and
  `ScenarioValidationError`.
- 20 unit tests under `tests/unit/simulation/`.

### Changed
- No public domain schemas were changed; the core `ScenarioResult` model is
  unchanged. The simulation layer defines its own richer result types.

## 2026-11-12 - Phase 6c: Digital Twin page

### Added
- `ui/pages/digital_twin.py`: twin summary, editable device/link operational
  state table, validation findings, bounded snapshot creation/list/download/
  delete, and a before/after revision comparison with CSV download.
- `tests/unit/ui/test_digital_twin_page.py`: empty state, snapshot lifecycle,
  and twin-failure propagation to the routing page.
- `app.py` routes `Digital Twin`.

### Changed
- Sidebar and dashboard availability text now include the Digital Twin.
- `tests/unit/ui` assertions read `ui.state.TWIN_KEY` instead of removed raw
  topology/VLAN session keys; widget keys are unchanged.

## 2026-11-12 - Phase 6b: digital-twin session integration

### Added
- `ui/state.py`: the single session accessor for the baseline twin, snapshots,
  derived result keys, and session helpers. Migrates a legacy bare `Topology`
  once and deletes the legacy key.

### Changed
- `topology_editor.py`, `ip_addressing.py`, `vlan_dhcp.py`,
  `routing_analysis.py`, and `network_analytics.py` now read/write the twin
  through `ui.state`; no page keeps a second topology copy.
- VLSM allocations, VLAN plans, and DHCP scopes are written into the twin;
  conflicts are reported without discarding the existing plan.
- Routing and analytics apply twin failures, union them with scenario
  selections, and warn about stale state.
- A topology change shows dependent-plan findings in the Topology Editor
  instead of silently leaving stale references.

## 2026-11-12 - Phase 6a: digital twin model

### Added
- `digital_twin/models.py`: frozen `DigitalTwin` with topology, optional
  addressing/VLAN plans, DHCP scopes, demands, per-entity operational state,
  assumptions, and versioned metadata. The twin is documented as a software
  model, not a live copy of real equipment.
- `digital_twin/validation.py`: `validate_twin` reusing topology, addressing,
  and DHCP validators plus cross-part checks; stale references are reported and
  never pruned.
- `digital_twin/operations.py`: immutable-style topology, state, capacity,
  cost, demand, plan, and assumption operations returning new twins.
- `digital_twin/snapshots.py`: frozen deep-copied snapshots, bounded
  `SnapshotStore`, and structured `diff_twins`.
- `digital_twin/serialization.py`: exact JSON round-trip with
  `TwinSchemaVersionError` for unsupported versions.
- `digital_twin/adapters.py`: thin adapters feeding the existing routing and
  analysis engines.
- `config/limits.py`: `MAX_SNAPSHOTS`, `MAX_DEMANDS`,
  `MAX_TWIN_SNAPSHOT_BYTES`; `core/exceptions` adds
  `TwinSchemaVersionError`.
- 53 unit tests under `tests/unit/digital_twin/`.

### Changed
- No public domain schemas were changed in Phase 6a.

## 2026-11-12 - Phase 5c: routing and analytics pages

### Added
- `ui/pages/routing_analysis.py`: source/destination selection, k-alternative
  paths, failure scenario for devices and links, shortest path metrics,
  routing table, directed reachability matrix, before/after comparison when
  failures are active, Plotly path highlighting, and CSV downloads.
- `ui/pages/network_analytics.py`: centrality bar charts and tables, connected
  components, per-component diameters, critical devices/links, SPOF summary
  and findings, per-pair node-/edge-disjoint path counts, CSV downloads, and
  an expandable metric-definition section.
- `tests/unit/ui/test_analysis_pages.py`: AppTest smoke tests for both pages,
  including the no-topology empty state and a routing failure scenario.

### Changed
- `app.py` routes `Routing Analysis` and `Network Analytics`; sidebar and
  dashboard availability text updated. Other planned pages remain
  placeholders.
- `CURRENT_STATUS.md` records Phase 5 as complete.

## 2026-11-12 - Phase 5b: structural analysis engine

### Added
- `network/analysis/graph.py`: deterministic simple undirected projection
  with direction ignored, parallel links collapsed, and failures applied
  without mutating the input.
- `network/analysis/metrics.py`: degree and cost-weighted betweenness
  centrality, connected components, per-component hop diameter, articulation
  points, bridges, and exported `METRIC_DEFINITIONS`.
- `network/analysis/spof.py`: `SpofReport` over critical devices and links.
- `network/analysis/findings.py`: critical `spof_device`/`spof_link` findings
  plus `topology_disconnected` and `isolated_device` warnings.
- `network/analysis/redundancy.py`: direction-aware node-disjoint counts and
  physical-link edge-disjoint counts via a unit-capacity flow gadget.
- `network/analysis/report.py` and `tables.py`: aggregate `AnalysisReport`
  and UI-agnostic row helpers.
- 41 unit tests under `tests/unit/analysis/`.

### Changed
- No public domain schemas were changed; findings reuse `Finding`/`Severity`.

## 2026-11-12 - Phase 5a: routing engine

### Added
- `network/routing/graph.py`: routing graph construction honoring
  `Link.directed`, using `Link.cost` as the only weight, ignoring capacity,
  collapsing parallel links deterministically, and validating failure ids.
- `network/routing/paths.py`: typed shortest paths with unreachable results,
  deterministic lexicographic tie-breaking, bounded k-alternative simple
  paths, routing tables, directed reachability matrices, and weak/strong
  component summaries.
- `network/routing/tables.py`: UI-agnostic row helpers.
- `config/limits.py`: `MAX_ALTERNATIVE_PATHS = 10`.
- 50 unit tests under `tests/unit/routing/`.

### Changed
- No public domain schemas were changed and no dependencies were added.

## 2026-11-12 - Phase 4c: IP addressing and VLAN/DHCP pages

### Added
- `ui/pages/ip_addressing.py`: CIDR calculator with IPv4/IPv6 special-prefix
  handling, VLSM planner with an editable requirement table, allocation and
  utilization output, overlap checker, and CSV downloads.
- `ui/pages/vlan_dhcp.py`: department requirement table (prefilled from an
  organization in session state when available), VLAN mapping, DHCP scope
  table, validation findings, and CSV downloads.
- `ui/components.py`: shared error formatting, CSV serialization, and findings
  table rendering.
- `tests/unit/ui/test_planning_pages.py`: AppTest smoke tests for both pages,
  including a rejected parent block.

### Changed
- `app.py` now routes `IP Addressing & Subnetting` and `VLAN & DHCP Planner`;
  sidebar and dashboard availability text updated.
- `CURRENT_STATUS.md` records Phase 4 as complete.

## 2026-11-12 - Phase 4b: VLAN planning and DHCP scopes

### Added
- `network/vlan/plan.py`: deterministic department-to-VLAN-to-subnet planning
  with 1-4094 validation, reserved IDs `{1, 1002-1005}`, unique explicit and
  automatic assignment, duplicate checks, and overlap rejection.
- `network/vlan/dhcp.py`: DHCP scope planning and validation covering
  network/anycast, gateway, IPv4 broadcast, exclusions, pool boundaries, lease
  time, and a first-free-pool default. Findings use the shared `Finding`
  schema.
- `network/vlan/tables.py`: UI-agnostic VLAN and DHCP row dictionaries.
- 36 unit tests under `tests/unit/vlan/`.

## 2026-11-12 - Phase 4a: addressing engine

### Added
- `network/addressing/cidr.py`: `calculate_subnet` with IPv4/IPv6 netmask,
  broadcast, usable range/count, and documented `/31`, `/32`, `/127`, `/128`
  behaviour.
- `network/addressing/vlsm.py`: deterministic largest-first VLSM allocation
  with configurable reserved addresses, smallest fitting prefix, no overlaps,
  and `InsufficientAddressSpaceError` listing every unallocated requirement.
- `network/addressing/validation.py`: overlap and duplicate-IP detection using
  the existing `Finding`/`ValidationReport` schema.
- `network/addressing/utilization.py`: per-subnet and parent utilization from
  prefix arithmetic only.
- `network/addressing/tables.py`: UI-agnostic row helpers.
- `config/limits.py`: `MAX_SUBNETS` and `MAX_HOSTS_PER_SUBNET`.
- `core.exceptions.InsufficientAddressSpaceError`.
- 39 unit tests under `tests/unit/addressing/`.

### Changed
- No public domain schemas were changed; the engine reuses `Subnet`,
  `VlanPlan`, `DhcpScope`, `Finding`, and `ValidationReport`.

## 2026-11-12 - Phase 3b: remaining generators and Topology Editor

### Added
- `network/topology/generators.py`: `generate_hierarchical_campus`
  (single-homed and redundant dual-homing), `generate_spine_leaf`
  (full leaf-spine mesh and a bounded dual-homed variant), and
  `generate_hybrid` (core ring plus one access star per ring node).
  All are deterministic, reject invalid parameters, and enforce
  `MAX_NODES`/`MAX_EDGES` before construction.
- `ui/` package with `ui/pages/topology_editor.py`: generator controls for all
  seven families, connectivity summary, Plotly diagram with role and link
  legend, editable device/link tables, and JSON download/upload. The page
  delegates all engineering to `network.topology` and keeps a single model in
  `st.session_state["topology"]`.
- Sidebar page navigation in `app.py` using `st.selectbox` keyed `page_nav`;
  Dashboard and Topology Editor are functional, other pages remain
  placeholders.
- 16 generator tests covering count formulas, connectivity, dual-homing
  degrees, limits, duplicate ids, JSON round-trip, and determinism.
- `tests/unit/ui/test_topology_editor.py`: AppTest smoke test that loads the
  page and generates a star topology.

### Changed
- Exports in `network/topology/__init__.py` now include the three new
  generators.
- App page icon changed from `:gear:` to `:material/hub:`.
- `CURRENT_STATUS.md` records Phase 3 as complete.

## 2026-11-12 - Phase 3a: topology engine core

### Added
- `network/` package for deterministic, UI-free, LLM-free engineering services.
- `network/topology/graph.py`: `Topology` <-> NetworkX `MultiDiGraph`
  conversion with explicit per-link directedness (undirected links become
  reciprocal arcs), node/link metadata, and exact round-trip reconstruction.
- `network/topology/operations.py`: pure add/remove/update operations for
  devices and links; duplicate-id, missing-endpoint, not-found, and
  `MAX_NODES`/`MAX_EDGES` enforcement; device removal cascades attached links.
- `network/topology/connectivity.py`: typed, frozen `ConnectivityReport`
  with components and isolated devices.
- `network/topology/serialization.py`: JSON export/import with exact
  round-trip and limit enforcement.
- `network/topology/generators.py`: deterministic star, ring, full mesh, and
  balanced tree generators with pre-build limit checks.
- `core.exceptions.DeviceNotFoundError` and `LinkNotFoundError`.
- 74 new unit tests under `tests/unit/topology/`.

### Changed
- `CURRENT_STATUS.md` records Phases 1-2 as verified complete and Phase 3a as
  delivered.

## 2026-11-12 - Phase 1-2 baseline

### Added
- Phase 1 foundation: Streamlit skeleton, configuration, resource limits,
  secrets template, smoke test.
- Phase 2 domain schemas: eight Pydantic v2 schema modules, exception
  hierarchy, eight sample fixtures, 114 passing tests.
- Initial git history on `main` (`Phase 1-2: foundation and domain schemas`).
