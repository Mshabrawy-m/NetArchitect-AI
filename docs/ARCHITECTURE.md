# Architecture

NetArchitect AI is a layered, mostly pure-Python application wrapped in a Streamlit UI. The engineering engines do not import Streamlit, an LLM SDK, a database client, or device libraries. Agents orchestrate those engines; the UI renders and caches results. This separation is what lets the same computations run in tests, headless checks, and the Streamlit app.

## Layered view

```text
Browser / Streamlit Community Cloud
        |
        v
app.py  ->  ui/pages/*  ->  ui/components/*  ->  ui/state.py, ui/cache.py
        |                                             |
        v                                             v
agents/*  ->  services/llm/* (optional)       core/schemas/*, config/*
        |
        v
services/reporting/*, services/export/*, services/validation/*
        |
        v
digital_twin/*  ->  network/*  simulation/*  optimization/*
                    forecasting/*  capacity/*  security/*
        |
        v
core/inputs.py, core/csv_safe.py, core/exceptions/*
```

No layer writes to disk at runtime. Exports and reports are assembled in memory and returned as bytes or text for user-owned downloads.

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | Entry point, page configuration, sidebar navigation, 15-page dispatch, and Dashboard rendering. |
| `ui/` | Streamlit pages, reusable components, session accessors, and content-keyed caches. Presentation only. |
| `agents/` | Typed agent contracts, tool registry, orchestrator, workflow trace, and specialized requirements, topology, IP/VLAN, routing, validation, simulation, optimization, revalidation, report, critic, documentation, requirements-understanding, and security agents. |
| `services/llm/` | Provider abstraction, optional Groq HTTP implementation using `urllib`, request/token budgets, structured-output validation, and a test fake. No SDK dependency. |
| `services/reporting/` | Typed report document IR, builder, provenance, value audit, consistency checks, and disclosure templates. |
| `services/export/` | In-memory Markdown, JSON, CSV bundle, PDF, and configuration-template exports. |
| `services/validation/` | Unified design health across addressing, VLAN, twin, routing, and security checks. |
| `digital_twin/` | Typed twin model, immutable operations, adapters, validation, snapshots, diffs, and canonical JSON. Single source of truth for the current design. |
| `network/` | Topology generation/editing, addressing, VLAN/DHCP, routing, and graph analysis. |
| `simulation/` | Deterministic bounded what-if scenarios, comparisons, history, and exports. |
| `optimization/` | Bounded reproducible multi-objective search, hard constraints, Pareto comparison, baseline comparison, and history. |
| `forecasting/` | CSV parsing, synthetic data, deterministic forecast rules, model selection, intervals, findings, and exports. |
| `capacity/` | Projected demand evaluation and bounded upgrade recommendations. |
| `security/` | Offline design-time zones, services, firewall policy, flow checks, findings, risk arithmetic, proposals, and data-only templates. |
| `core/` | Shared Pydantic domain schemas, typed exceptions, guarded JSON/text/identifier parsing, and CSV formula neutralization. |
| `config/` | Compiled resource limits and no-key-safe settings loaded from environment variables or Streamlit secrets. |
| `scripts/` | Reproducible performance/memory profile helper; not imported by the app. |

## Data flow

1. A user builds or imports a topology. `network/topology` creates a validated graph and `digital_twin` stores it as the current twin.
2. Addressing, VLAN, routing, and analysis engines read the twin and return typed results. Writes use immutable twin operations, so a new twin version is produced instead of silently mutating the baseline.
3. Scenario, optimization, capacity, and security runs are content-keyed and bounded. Their outputs reference the twin version and stated assumptions.
4. Agents call registered tools with schema-validated inputs. They may reorder or select deterministic work, but they do not calculate engineering values themselves.
5. The report builder collects completed results, marks unrun sections with reasons, attaches `step/tool/twin_version` provenance to values, and runs consistency checks.
6. Exports serialize the report or engine results in memory. CSV cells pass through formula neutralization before download.

## State and caching

- All interactive state lives in Streamlit Session State (`ui/state.py`): the twin, scenario/optimization/capacity histories, agent traces, security model, and optional session key.
- `ui/cache.py` stores reproducible analyses keyed by canonical inputs. Changing the twin, model, or flow payload invalidates the relevant key.
- There is no database, file-backed session store, background worker, or cross-user persistence. A restart returns to a fresh session.
- Snapshot and history stores are bounded by count and serialized byte size. See `docs/RUNTIME_LIMITS.md`.

## Determinism and validation

- Topology generators, optimization runs, forecasts, scenarios, and reports are deterministic for fixed inputs and seeds.
- Public data models are Pydantic schemas. Unsupported twin versions, malformed structures, non-finite numbers, duplicate JSON keys, deep nesting, path-like identifiers, and oversized payloads are rejected with typed errors.
- `core/inputs.py` pre-scans untrusted JSON and text before Pydantic validation. `core/csv_safe.py` neutralizes spreadsheet-formula prefixes in every CSV writer while preserving ordinary signed numbers.
- The release source scan verifies that runtime modules contain no `eval`, `exec`, `subprocess`, `os.system`, `shell=True`, `__import__`, or direct file writes.

## Security boundary

NetArchitect AI performs design-time security modeling only. The security engine reads zones, services, firewall rules, and flow requests from the twin model and returns findings, flow verdicts, visible risk arithmetic, inert proposals, and vendor-neutral data templates. It never scans a network, probes a host, opens a socket, or emits device commands. Asset and zone criticality are a gate for `SEC-DW-009`; they are not a numeric term in the risk formula.

Optional LLM text is untrusted data. Agent outputs must still satisfy Pydantic schemas, tool calls must be on the agent's allowlist, and numeric design values must match deterministic engine results. Trace summaries redact credential-like keys.

## External integration

The only external service is the optional Groq-compatible provider. `config/settings.py` reads `GROQ_API_KEY`, `GROQ_MODEL`, and `GROQ_BASE_URL` from environment variables or Streamlit secrets, with secrets taking precedence. No key means the deterministic path runs normally. The provider uses standard-library `urllib` with injectable transport and sleep functions for testing; adding a provider SDK was out of scope.

## Free-tier fit

The deployment design follows the blueprint's Community Cloud constraints: headless server config, 2 MB upload widget, no usage stats, bounded loops and deadlines, session-only state, in-memory downloads, optional paid API, and no Docker, ports, workers, or persistent storage. `docs/DEPLOYMENT.md` contains the manual deployment procedure; `docs/RELEASE_AUDIT.md` records which items were verified locally and which remain remote.
