# Changelog

All notable changes to NetArchitect AI are recorded here. Dates are ISO-8601.

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
