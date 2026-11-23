# Known limitations

This file is the consolidated limitation list for `v1.0.0-rc1`. It is intentionally explicit: the release is a graduation project and design-time workspace, not an operational network platform.

## Product scope

- The application does not connect to devices, scan or probe networks, run penetration tests, apply configurations, or open ports. Templates are inert design data and contain no device commands.
- Simulation is an abstract, deterministic flow model. It is not packet-level, queueing-aware, ECMP-aware, hardware-accurate, or a measurement of a real network.
- Forecasting and capacity results are model-based estimates from supplied or clearly labeled synthetic data. They are not guarantees of future demand or behavior.
- Security findings come from a fixed design-time catalog and policy model. They are not a vulnerability scan, audit, compliance certification, or replacement for expert review.
- Asset and zone criticality are a gate for `SEC-DW-009`; they are deliberately **not** a numeric term in the risk formula.
- Optimization results are bounded candidates under the stated objective weights and hard constraints. They do not prove a global optimum outside the configured search space.

## State and deployment

- All twins, runs, traces, and models live in Streamlit Session State. Closing or restarting the session discards them. The optional API key is not stored in session state. Download reports and exports before leaving.
- There is no database, file-backed persistence, background worker, always-on service, or cross-user sharing.
- The upload widget is capped at 2 MB; in-app parsers enforce tighter per-format caps, including 1,000,000 bytes for CSV and 2,000,000 bytes for JSON.
- The release was verified locally on Windows with Python 3.11 and 3.12. Streamlit Community Cloud runs Debian Linux and was **not** deployed or measured.
- The transitive `pyarrow==23.0.1` wheel is now pinned inline in `requirements.txt`; the earlier `constraints.txt` layout was removed for Cloud installs. Older/unpinned wheels were problematic on this Windows host (application-control block or a known advisory); Linux behavior remains unverified.
- Real-browser rendering, client-side JavaScript behavior, and responsive layouts were not tested. UI verification used Streamlit `AppTest` plus one headless agent-API page check.
- Remote execution of `.github/workflows/ci.yml` was not performed.
- No license file is included. The owner must decide on licensing before public distribution.

## Model fidelity and engine edge cases

- Full-mesh topologies can exceed the 2,000-link cap at larger node counts; the limit is enforced explicitly rather than silently expanding the graph.
- VLSM and DHCP allocation have edge cases at highly irregular boundary combinations; validate generated plans before operational use.
- Some graph metrics treat links as directed where the model declares direction. Interpret undirected assumptions carefully.
- Modeled operational state can drift from a declared design after failure/restore operations; inspect the effective-state view and twin version.
- Simulation history, snapshots, capacity runs, optimization runs, and scenario counts are bounded by count and size; older entries are dropped or rejected by design.
- Reports mark unrun sections with reasons, but a consumer must still read section status and provenance rather than assuming every section ran.
- Cached analyses are content-keyed, but stale browser tabs must be refreshed after external changes to source data.
- CSV floating-point precision and locale formatting can affect spreadsheet display; exported numeric values are model outputs, not accounting-grade decimals.

## AI and provider behavior

- The optional Groq integration requires a key and a currently available model name. Providers retire models; configure `GROQ_MODEL` rather than relying on a hardcoded guarantee.
- No live provider request was made during release verification. Tests use a fake provider with injected transport, clock, and response headers. Real Groq rate-limit header names, units, and reset semantics remain unverified.
- LLM prose is explanatory only. It cannot change computed values or call tools outside the active agent's allowlist, but it must still be read with the attached disclosure labels.
- The configured key is held only in process memory for request headers; it is never displayed, logged, serialized into exports, traced, or written to disk.
- Prompt-injection text is constrained by schema validation and tool allowlists, but adversarial model behavior cannot be exhaustively proven.

## Reports and exports

- PDF export uses ReportLab with standard fonts. Visual layout, pagination, and non-Latin shaping (for example Arabic) were not visually verified.
- Report consistency checks cover labels and numeric reflection against computed values; they are not a full semantic proof of prose correctness.
- Exports are built in memory under a 5 MB cap and must be downloaded by the user; there is no server-side export store.

## Verification and measurement

- The profile measures Python allocations with `tracemalloc` and wall-clock time, not total process RSS on Community Cloud.
- The no-memory profile flags the two maximum-size user-triggered optimization searches as over the script's 5 s threshold. They are bounded by the 60 s hard cap and are not unbounded loops.
- All local evidence comes from the pinned versions in `requirements.txt` on Windows. Dependency behavior on the deployment OS was not executed.
- Browser-visible behavior, deployed free-tier resource limits, live provider responses, PDF visual layout, and remote CI remain unverified and are listed in `docs/DEPLOYMENT.md` and `docs/RELEASE_AUDIT.md`.

## Scope decisions

- Phase 15 introduced no new features, no public schema changes, and no new runtime dependencies.
- No security-scanning functionality was added.
- No license was added without owner direction.
