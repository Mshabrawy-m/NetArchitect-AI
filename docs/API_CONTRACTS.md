# API contracts

NetArchitect AI exposes **Python-level contracts**, not a public HTTP API. The application opens no server ports of its own and provides no web service endpoints for third-party clients. These contracts are the stable imports used by the UI, agents, tests, and reports. Phase 15 did not change any public domain schema.

## Shared validation contract

| Contract | Module | Behavior |
|---|---|---|
| Domain schemas | `core.schemas` | Pydantic models for topology, twin, scenario, optimization, forecast, security, report, and agent data. |
| Typed errors | `core.exceptions` | Explicit failures such as limit violations, schema errors, missing keys, and invalid structured output. |
| Guarded inputs | `core.inputs` | Size/depth/width/character/number/identifier checks before Pydantic parsing. Rejects duplicate keys, hidden controls, path-like ids, and non-finite numbers. |
| CSV safety | `core.csv_safe.neutralize_cell` | Neutralizes spreadsheet-formula prefixes while leaving ordinary signed numbers usable. |
| Settings | `config.settings.get_settings` | Cached, no-key-safe settings from defaults, environment variables, and Streamlit secrets, in that precedence order. |
| Limits | `config.limits` | Compiled numeric caps consumed by engines and docs. |

## Digital twin

| Export | Result / contract |
|---|---|
| `DigitalTwin`, `TwinMetadata`, `DeviceState`, `LinkState`, `OperationalState` | Typed current model; `TWIN_SCHEMA_VERSION = 2`, with versions `{1, 2}` supported. |
| `effective_device_state`, `effective_link_state` | Merge declared state with modeled failures. |
| `set_topology`, `set_device_state`, `set_link_state`, `apply_failure`, `restore_entities`, `set_link_capacity`, `set_link_cost`, `add_demand`, `set_demands`, `set_addressing_plan`, `set_vlan_plan`, `set_dhcp_scopes`, `set_assumptions` | Immutable-style operations: each returns a new twin rather than mutating the baseline in place. |
| `create_snapshot`, `SnapshotStore`, `diff_twins` | Bounded snapshots and typed before/after changes. |
| `to_json`, `from_json`, `canonical_payload`, `json_size_bytes` | Canonical serialization and typed version/schema errors. |
| `validate_twin` | `ValidationReport` for twin consistency. |
| `FailureSelection`, `failed_entities`, `routing_arguments`, `analysis_arguments` | Adapters from twin state to engine inputs. |

## Network engines

| Area | Key contracts |
|---|---|
| Topology | `generate_star`, `generate_ring`, `generate_spine_leaf`, `generate_hierarchical_campus`, graph build/edit/serialize helpers. |
| Addressing | subnet/CIDR/VLSM planning, `detect_overlaps`, `detect_duplicate_ips`, utilization and table builders. |
| VLAN/DHCP | VLAN plan generation, DHCP scope planning, validation, and table builders. |
| Routing | `build_routing_graph`, `shortest_path`, `alternative_paths`, `routing_table`; every returned route is a graph walk. |
| Analysis | Graph metrics, SPOF detection, redundancy, findings, and table builders. |

## Simulation

```python
run_scenario(
    baseline_twin: DigitalTwin,
    scenario: Scenario,
    assumptions: SimulationAssumptions | None = None,
    *,
    max_runtime_seconds: float | None = None,
) -> ScenarioRun
```

`ScenarioRun` contains the scenario, baseline and scenario twin references, assumptions, thresholds, before/after network state, `ScenarioComparison`, warnings, and `model_note`. `ScenarioComparison` reports served counts/ratios, newly unserved and recovered demands, path/link changes, congestion and utilization deltas, recovery availability, and a summary.

Supporting contracts: `validate_scenario`, `compare_runs`, `evaluate`, `twin_fingerprint`, bounded `ScenarioHistory`, `run_to_json`, `run_to_json_bytes`, `run_to_csv`, and table helpers. Results are deterministic and labeled as abstract models, not packet emulation.

## Optimization

```python
run_optimization(
    baseline_twin: DigitalTwin,
    settings: OptimizationSettings,
    algorithm: Algorithm,
    *,
    deadline: float | None = None,
) -> OptimizationRun
```

`Algorithm` is `greedy | genetic | nsga2`; PSO was intentionally not implemented. `OptimizationSettings` bounds candidate pool, population, iterations, evaluations, runtime, weights, and hard constraints. `OptimizationRun` records settings, limits, evaluations, cache hits, `StopReason`, baseline, candidate records, Pareto front, best candidate, and fixed model/cost/search notes.

Supporting contracts: `Candidate`, `CandidateEvaluation`, `CandidateMetrics`, `ObjectiveValue`, `ConstraintResult`, `HardConstraints`, `ObjectiveKind`, `OBJECTIVE_DEFINITIONS`, `ComparisonReport`, `compare_runs`, `objective_deltas`, `trade_off_messages`, `EvaluationCache`, and `OptimizationHistory`.

## Forecasting and capacity

| Contract | Result |
|---|---|
| `parse_csv(text, gap_policy=...)` | `ParseResult` with typed series and findings; rejects invalid or adversarial rows. |
| `forecast_series(series, horizon=..., ...)` / `select_model` | `ForecastResult` with `ForecastPoint`s, history summary, model evaluations, fill report, intervals, and run metadata. |
| `generate_synthetic(SyntheticSpec)` | Clearly labeled synthetic series using `DataProvenance.SYNTHETIC`. |
| `forecast_csv`, `forecast_json`, `series_csv` | In-memory exports. |
| `project_demands`, `evaluate_capacity` | Bounded capacity projections and `CapacityRun` with upgrade recommendations. |
| `CapacityHistory`, `CapacityStopReason` | Bounded session history and explicit stop reasons. |

Forecast rules are `naive`, `moving_average`, `linear_trend`, `holt`, and `seasonal_naive`. A naive baseline wins unless held-out MAE improves.

## Security

```python
analyze_design(
    twin: DigitalTwin,
    *,
    model: SecurityModel | None = None,
    flows: tuple[FlowRequest, ...] | list[FlowRequest] = (),
) -> SecurityAnalysis
```

`SecurityAnalysis` contains the model, findings, flow checks, summary, risk, inert proposals, and a data-only template. Every disclosed object carries the exact disclaimer: `Modeled design-time assessment. Not a vulnerability scan, penetration test or audit.`

Key enums and results: `ZoneType`, `Protocol`, `PolicyAction`, `FindingCategory`, `RiskLevel`, `SecurityPosture`, `FlowVerdict`, `ProposalSet`, `TemplateDocument`, plus the fixed `SEC-DW-001..009` catalog and `SECURITY_DISCLAIMER`. Twin operations `get_security_model`, `set_security_model`, `ensure_security_model`, `clear_security_model`, and rule operations keep security state versioned and separate from silent mutation.

## Agents and LLM

| Contract | Result / behavior |
|---|---|
| `BaseAgent` | `validate_input`, `run`, `validate_output`, `replan`. |
| `ToolRegistry.invoke`, `AgentContext.call_tool` | Allowlist plus schema validation; unlisted tools are rejected. |
| `build_standard_plan`, `validate_workflow_plan`, `Orchestrator.run`, `run_structured_design` | Deterministic 11-step plan, optional 12-step security plan, bounded execution, typed stop reasons. |
| `WorkflowPlan`, `WorkflowState`, `ExecutionTrace`, `TraceEntry` | Typed workflow and deterministic, redacted trace serialization. |
| `LLMProvider.complete` | Abstract provider call returning `LLMResponse`; `GroqProvider` is the optional concrete implementation. |
| `validate_structured(text, schema)` | Extracts bounded JSON and returns a validated Pydantic model or raises `LLMSchemaError`. |
| `RequestBudget`, `provider_status`, `FakeProvider` | Budget enforcement, status display, and deterministic tests. |

## Reporting and exports

| Contract | Result |
|---|---|
| `ReportSources` | Inputs: twin, optional workflow, scenario run, optimization run, capacity run, security analysis, fingerprint, generated time. |
| `build_report(ReportSources)` | `ReportDocument` with ordered sections and typed paragraph/key-value/table/note blocks. Unrun sections include a reason and producing page. |
| `check_consistency(document)` | `ConsistencyReport` with typed codes and severities. |
| `filter_sections` | Select report sections without changing provenance. |
| `to_markdown`, `to_json`, `from_json`, `to_csv_bundle`, `to_pdf`, `to_config_bundle` | In-memory text/bytes; no file writes. |
| `build_design_health(twin)` | Unified `DesignHealth` across addressing, VLAN, twin, routing, and security checks. |

`REPORT_SCHEMA_VERSION = 1`. Report values carry `Provenance(step, tool, twin_version)` and are checked against computed engine values.

## Compatibility and stability

- Public domain schemas were not changed in Phase 15. The twin remains version 2 with version 1 compatibility.
- JSON/CSV exports are user-owned downloads, not a stable external integration format promised to third parties.
- Typed validation failures are part of the contract: callers should handle explicit errors rather than rely on silent coercion or truncation.
- No runtime code writes files, opens sockets, or invokes external processes.
