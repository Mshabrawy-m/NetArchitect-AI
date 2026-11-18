# Release audit - Blueprint §11 and §16

This is a criterion-by-criterion audit for `v1.0.0-rc1`. Evidence refers to local release verification on Windows with Python 3.11 and 3.12 clean virtual environments. Status labels are deliberately narrow:

- **PASS** - verified locally by an executed command or test.
- **PASS (local)** - verified in-process/headless locally; the equivalent remote/deployed check was not performed.
- **UNVERIFIED (remote)** - not performed in this environment; remains an owner action.
- **PARTIAL** - part of the criterion is verified locally and part remains remote.

## Phase 15 exit criteria

| criterion | evidence | status |
|---|---|---|
| Critical test suites pass | `pytest -q` -> `975 passed in 33.79s`; `ruff check .` -> `All checks passed!`; `pytest -q -m smoke` -> `12 passed, 963 deselected in 8.55s` | PASS |
| No secrets are exposed | tree/history secret-pattern scans produced no output; no tracked `.env`, `.streamlit/secrets.toml`, or key files; release tests check logs, traces, reports, exports, and session dumps | PASS |
| Structured fallback works without an LLM | AppTest clears all setting keys and renders all 15 pages with no exception; Settings shows `API key configured No`; AI Designer uses the structured form when no key exists | PASS |
| App starts on the target deployment | local headless Streamlit startup returned `health: ok`, `agent status: ready`, root title `Dashboard`, `exceptions: 0`; Community Cloud itself was not deployed | PARTIAL |
| Memory and execution remain within observed free-tier limits | profile rerun: peak tracemalloc allocation 8.7 MiB; all memory-run rows `over budget = no`; no-memory max-search rows are bounded by the 60 s hard cap and flagged by the script's 5 s threshold | PASS (local) |
| Known limitations are documented | `KNOWN_LIMITATIONS.md`, in-app Settings > Release limitations, and this document set | PASS |

## Blueprint §11 - module requirements

| criterion | evidence | status |
|---|---|---|
| Every module includes unit tests | 975 tests across 16 category directories plus two root files; release module adds 37 tests | PASS |
| Every module includes input validation | guarded JSON/CSV/text/identifier parsers in `core/inputs.py`, Pydantic models, compiled caps in `config/limits.py` | PASS |
| Every module includes error handling | typed exceptions in `core/exceptions`; parser/engine failures raise explicit errors instead of silent truncation | PASS |
| Deterministic behavior where applicable | fixed generator/optimization seeds, reproducible simulation tests, deterministic report ordering and canonical JSON | PASS |
| Integration tests where relevant | `tests/unit/release/test_phase15_acceptance.py` covers IP, routing, simulation, optimization, LLM validation, reports, no-key pages, and security criticality | PASS |
| Documentation | README plus architecture, API, agent, test, deployment, audit, limits, roadmap, changelog, limitations, and status documents | PASS |
| Resource limits | `docs/RUNTIME_LIMITS.md` records all compiled caps; source scan finds no runtime dynamic execution or disk writes | PASS |

## Blueprint §11 - system-wide acceptance criteria

| criterion | evidence | status |
|---|---|---|
| No unintended subnet overlap | acceptance test checks generated IP plans across three base networks with `detect_overlaps` | PASS |
| No duplicate IP allocation | acceptance test checks generated plans with `detect_duplicate_ips` | PASS |
| All generated routes correspond to valid graph paths | acceptance test walks every returned route on four topology generators across at least 40 source/destination pairs | PASS |
| Failed links and nodes are excluded from post-failure routes | acceptance tests compare failed elements against post-failure paths and routing tables in simulation and routing engines | PASS |
| Simulation results are reproducible with fixed inputs and seeds | acceptance test reruns a scenario with identical inputs and asserts equality | PASS |
| Optimization respects hard constraints | acceptance test exercises greedy, genetic, and NSGA-II settings with infeasible constraints and verifies no infeasible recommendation | PASS |
| Optimized designs are compared against a baseline | `OptimizationRun.baseline`, `compare_runs`, `objective_deltas`, and `trade_off_messages` are covered by optimization tests | PASS |
| Agents do not invent engineering calculations | tool allowlists, registered tool result models, critic revalidation, and security-agent prose rejection of invented numeric tokens | PASS |
| Invalid LLM output cannot bypass schemas and validators | `validate_structured` rejects malformed output with `LLMSchemaError`; acceptance test feeds invalid coerced values into `RequirementsExtraction` | PASS |
| Reports reflect actual computed results | acceptance test compares `ValueRecord.numeric` values to twin/engine results and runs `check_consistency` | PASS |
| Demo Mode works without external AI access | release test clears all setting keys and renders all 15 pages without exception; structured workflow uses real tools | PASS |
| The application can be deployed within the target environment's observed limits | config is headless/bounded; local profile stays under 300 MiB; actual Community Cloud deployment was not performed | UNVERIFIED (remote) |

## Blueprint §16 - final definition of done

| criterion | evidence | status |
|---|---|---|
| The main network engineering modules work | full suite passes across topology, addressing, VLAN, routing, analysis, twin, simulation, optimization, capacity, and security | PASS |
| Topology generation and editing are functional | topology tests cover generators, graph operations, serialization, and bounded edits | PASS |
| IP and VLAN plans are mathematically validated | addressing and VLAN suites plus acceptance overlap/duplicate checks | PASS |
| Routing and graph analysis are correct | routing and analysis suites plus graph-walk and post-failure acceptance checks | PASS |
| The Digital Twin supports bounded scenarios | twin and simulation suites; snapshot count/byte caps in `docs/RUNTIME_LIMITS.md` | PASS |
| Simulation results are reproducible and clearly labeled | deterministic rerun test; `MODELED_ESTIMATE_LABEL`, `model_note`, and simulation disclosures | PASS |
| Multiple optimization approaches can be compared against a baseline | algorithm set `greedy`, `genetic`, `nsga2`; baseline record and comparison helpers | PASS |
| Agentic workflows use real tools and conditional task execution | `ToolRegistry`, per-agent allowlists, `validate_workflow_plan`, retry/replan policy, and 11/12-step plans | PASS |
| The Critic Agent can reject invalid designs | critic tests and `WorkflowStopReason.critic_rejected` | PASS |
| Explanations and reports reflect validated results | report consistency checks, provenance triples, and value audit appendix | PASS |
| Demo Mode works without an LLM API | no-key all-pages AppTest and structured workflow | PASS |
| The integrated Streamlit application deploys on the target free tier | exact steps are documented in `docs/DEPLOYMENT.md`; no remote deployment was performed | UNVERIFIED (remote) |
| Tests, setup instructions, architecture, limitations, and status are documented | this release documentation set and updated `CURRENT_STATUS.md` | PASS |

## Blueprint §10 - supporting deployment constraints

| criterion | evidence | status |
|---|---|---|
| No physical equipment, server, Docker, ports, workers, always-on service, local persistence, paid API, or database | architecture is pure Python plus Streamlit; no runtime disk writes; optional Groq only; no sockets opened by application code | PASS |
| Streamlit Session State for temporary interactive state | `ui/state.py`; all twins, runs, traces, and session keys are session-scoped | PASS |
| JSON/CSV downloads for user-owned exports | `services/export` builds Markdown, JSON, CSV, PDF, and config bundles in memory | PASS |
| Optional Groq integration; deterministic Demo Mode | no-key path verified across all pages and in the structured workflow | PASS |
| Ephemeral restart handling | no dependency on local persisted files; an app restart returns to a fresh session | PASS |
| Secrets only in Streamlit secrets or environment variables | `config/settings.py` reads `os.environ` and `st.secrets`; no secrets file is tracked | PASS |
| Never print API keys or sensitive values to logs | release test checks logs/traces/reports/exports/session dumps; trace summarization redacts credential-like keys | PASS |
| Bounded node, edge, scenario, population, iteration, and time limits | complete bounds table in `docs/RUNTIME_LIMITS.md` | PASS |
| Cache only safe, reproducible computations | `ui/cache.py` content-keys cached analyses and reports by canonical inputs | PASS |
| Avoid large duplicate graph/simulation objects in session state | bounded scenario/snapshot/history caps; canonical twin references in scenario runs | PASS |
| Test actual deployment behavior; do not assume limits | local headless startup and profile were executed; remote free-tier check remains an owner action | PARTIAL |
| Disclose that simulations are abstract, not packet-level or hardware-accurate | in-app Settings > Release limitations, simulation model notes, reports, and `KNOWN_LIMITATIONS.md` | PASS |
