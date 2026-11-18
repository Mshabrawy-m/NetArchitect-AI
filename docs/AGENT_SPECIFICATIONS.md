# Agent specifications

The agent layer selects and coordinates deterministic engineering work. It is not a source of engineering calculations. Every numeric result comes from a registered tool backed by the network, digital twin, simulation, optimization, security, or reporting engines.

## Contracts

- `BaseAgent` defines `validate_input`, `run`, `validate_output`, and `replan`. Inputs and outputs are Pydantic models.
- `AgentContext.call_tool(name, payload)` routes a call through `ToolRegistry.invoke`, which validates the payload against the tool's input schema and checks the caller's allowlist.
- `ExecutionTrace.record(...)` appends ordered `TraceEntry` records with step, timestamp, task id, agent, tool, action, status, attempt, and bounded input/output summaries. `to_json()` is deterministic.
- `WorkflowState.to_dict()` and trace summaries redact credential-like keys and truncate depth and strings.

## Agent inventory

| Name | Implementation | Allowed tools | Role |
|---|---|---|---|
| `requirements` | `RequirementsAgent` | `requirements_validate` | Validate structured design requirements. |
| `requirements_understanding` | `RequirementsUnderstandingAgent` | `requirements_validate` | Optional LLM-backed extraction into the same validated requirements model. |
| `topology` | `TopologyAgent` | `topology_from_requirements`, `topology_connectivity`, `working_twin_build` | Build and check topology from validated requirements. |
| `ip_vlan` | `IpVlanAgent` | `ip_plan_from_requirements`, `demand_plan`, `working_twin_build` | Produce validated IP/VLAN plans and demands. |
| `routing` | `RoutingAgent` | `routing_path`, `routing_table` | Compute paths and routing tables from the twin. |
| `validation` | `ValidationAgent` | `addressing_validate`, `twin_validate` | Report addressing and twin health. |
| `simulation` | `SimulationAgent` | `simulation_run` | Run one bounded scenario and return the deterministic result. |
| `optimization` | `OptimizationAgent` | `optimization_run` | Run a bounded, seeded search and return engine results. |
| `revalidation` | `RevalidationAgent` | `twin_validate` | Re-check the twin after design changes. |
| `security` | `SecurityAgent` | `security_analysis` | Copy verdict, risk, findings, and posture from the deterministic security engine. |
| `critic` | `CriticAgent` | `topology_connectivity`, `addressing_validate`, `twin_validate`, `routing_path`, `twin_load_state`, `spof_analysis`, `security_analysis` | Independently re-run checks and approve, warn, or reject. |
| `documentation` | `DocumentationAgent` | none | Write explanatory prose from already validated result objects. |
| `report` | `ReportAgent` | none | Assemble the provenance-tagged report from completed results. |

An agent that has no allowed tools still cannot manufacture values: its inputs are validated result models, and the report/consistency layer checks displayed numbers against those models.

## Workflow

`build_standard_plan()` creates the default 11-step DAG:

```text
requirements -> topology -> ip_vlan -> routing -> validation -> simulation
             -> optimization -> revalidation -> critic -> documentation -> report
```

With `include_security=True`, a `security` step is inserted after `revalidation` and before `critic`, making 12 steps. `validate_workflow_plan` rejects duplicate ids, unknown dependencies, cycles, over-limit plans, unknown agents, and tools that are not registered or not allowlisted.

`Orchestrator.run` executes the DAG deterministically:

- failed tasks skip their dependents;
- recoverable failures are retried up to the compiled bound;
- selective re-planning resets only the affected task and its dependents;
- critic rejection can stop the workflow;
- every run ends with one `WorkflowStopReason`: `completed`, `failed`, `step_limit`, `runtime_limit`, `replan_limit`, or `critic_rejected`.

Selective re-plan policy maps `subnet_overlap`, `duplicate_ip`, and `twin_vlan_subnet_missing` back to `ip_vlan`. The Security Agent declines automatic re-plans so an offline assessment cannot silently rewrite design state.

## Budgets

| Budget | Limit |
|---|---:|
| Workflow steps | 50 |
| Workflow wall-clock | 120 s |
| Retries per recoverable failure | 3 |
| Selective re-plans | 2 |
| LLM calls per browser session | 20 |
| LLM tokens per browser session | 60,000 |
| Schema repair retries | 2 |
| HTTP 429 retries | 2 |
| Backoff | 1 s base, 30 s cap |
| Request timeout | 30 s |
| Completion tokens | 4,096 |

These constants live in `config/limits.py` and are documented in `docs/RUNTIME_LIMITS.md`.

## Critic and security behavior

The critic re-runs connectivity, addressing, twin, routing, SPOF, and optional security tools. It maps blocking findings to the responsible step and can stop with `critic_rejected`. Nonblocking findings become warnings in an approved verdict.

The Security Agent may call only `security_analysis`. It copies the engine's verdict and findings rather than deriving them. Optional model prose carries the label `AI-generated text; not a source of design data.`; invented numeric tokens or out-of-scope claims cause the prose to be discarded in favor of the deterministic explanation. Criticality gates `SEC-DW-009` but is not a numeric risk-formula term.

## Optional LLM layer

Applications depend on the abstract `LLMProvider`, not an SDK. `GroqProvider` uses standard-library `urllib` with injectable transport and sleep hooks for tests. It adds a schema instruction to the request and calls `validate_structured`; invalid output triggers at most two bounded repair attempts before a typed `LLMSchemaError`.

Prompt-injection text is treated as untrusted data. Even if a provider reply says "ignore previous instructions", the agent can only call its allowlisted tools and must still pass Pydantic output validation. A release test verifies that the trace contains only the expected tool call.

## No-key behavior

`Settings.GROQ_API_KEY` defaults to an empty string. With no key:

- all 15 Streamlit pages render without exception;
- the structured requirements form is used in AI Designer;
- the deterministic workflow runs with real tools;
- Settings shows `API key configured No`;
- no provider request is attempted.

This is the release Demo Mode. It does not require external AI access or a paid API.

## Provenance

Each reported value carries `Provenance(step, tool, twin_version)`. Trace entries record attempts and tool calls. Report consistency checks verify labels and numbers against computed values. The value audit appendix lets a reviewer follow an engineering number back to the producing step and tool.
