# NetArchitect AI

## Master Project Blueprint & Development Roadmap

**Project title:** Agentic AI-Powered Network Architecture, Digital Twin
& Multi-Objective Optimization Platform\
**Project type:** Pure Software / Computer Networking / Agentic AI\
**Primary interface:** Streamlit\
**Deployment target:** Streamlit Community Cloud Free\
**Development approach:** AI-assisted Vibe Coding\
**Roadmap:** 14 implementation phases

------------------------------------------------------------------------

## Document purpose

This file is the single source of truth for planning, implementing,
testing, and deploying NetArchitect AI. It is intended to be supplied to
any AI coding assistant (Codex, Kiro, Cursor, Claude Code, or another
tool) before it performs project work.

Coding assistants must read this document and the current repository
status before making changes. They must not assume that a phase or
feature is complete unless the repository and tests provide evidence.

## 1. Project vision

NetArchitect AI is an intelligent software platform that designs,
analyzes, simulates, validates, and optimizes computer network
architectures using coordinated AI agents and deterministic
network-engineering tools.

A user provides natural-language or structured requirements. The system
converts them into validated requirements, generates candidate
architectures, plans IP addressing and VLANs, calculates routes,
simulates scenarios, evaluates alternatives, and produces an explainable
network blueprint and engineering documentation.

The platform is entirely software-based. Its network model and
simulation are abstractions implemented in Python; they do not configure
or operate real networking equipment.

### Main objectives

1.  Generate network architecture candidates from user requirements.
2.  Support common network topology families.
3.  Design and validate IPv4/IPv6 addressing and VLSM plans.
4.  Plan VLANs and DHCP scopes.
5.  Calculate routes and analyze path redundancy.
6.  Analyze graph connectivity, critical nodes, and critical links.
7.  Create a software-based Network Digital Twin.
8.  Simulate bounded what-if scenarios.
9.  Optimize designs against multiple objectives and hard constraints.
10. Estimate future capacity using explicitly supplied or simulated
    demand data.
11. Explain engineering and optimization decisions.
12. Generate downloadable technical reports and tables.

## 2. Project boundaries and non-goals

### Included

-   Network architecture design and comparison.
-   Topology generation and editing.
-   IPv4, IPv6, CIDR, and VLSM planning.
-   VLAN and DHCP scope planning.
-   Routing and graph analysis.
-   Network validation.
-   Software-based Digital Twin.
-   Bounded network scenario simulation.
-   Multi-objective optimization.
-   Capacity planning and forecasting.
-   Multi-agent orchestration and explainability.
-   Reports, CSV exports, and configuration templates.

### Explicitly excluded

-   Physical routers, switches, or other networking equipment.
-   Real network monitoring or administration.
-   Real packet forwarding or live traffic capture.
-   Penetration testing, vulnerability scanning, or SOC operations.
-   Device configuration over SSH, Telnet, SNMP, or vendor APIs.
-   Docker, Containerlab, GNS3, or EVE-NG as runtime dependencies.
-   Privileged processes, port opening, or host network access.
-   Persistent background workers or always-on services.
-   Dedicated servers or mandatory paid infrastructure.
-   Dependence on local persistent storage.

### Separation from other projects

NetArchitect AI is a network design and optimization platform. It must
not reproduce the operational monitoring and network-management role of
NetPilot, or the penetration-testing and SOC-analysis role of the
separate security project.

## 3. Core product modules

### 3.1 Intelligent Network Designer

-   Natural-language requirements input.
-   Structured requirements form.
-   Organization, building, department, and user-count modeling.
-   Device and link requirements.
-   Architecture recommendation.
-   Candidate topology generation.
-   Interactive topology visualization and editing.
-   Design constraints and assumptions display.

Supported topology families may include:

-   Star.
-   Ring.
-   Mesh.
-   Tree.
-   Hierarchical campus.
-   Spine-Leaf.
-   Hybrid.

The system should select only topology types appropriate to the modeled
network and explain its selection.

### 3.2 IP Addressing and Network Segmentation

-   IPv4 and IPv6 address planning.
-   CIDR and subnet calculations.
-   VLSM allocation.
-   Automatic subnet allocation.
-   VLAN planning and mapping.
-   DHCP scope planning.
-   Network and subnet overlap detection.
-   Duplicate IP detection.
-   Address utilization and remaining-capacity reporting.

All address calculations must use deterministic code, primarily Python's
`ipaddress` module. The LLM may propose requirements but must not be
trusted to perform subnet arithmetic.

### 3.3 Routing and Path Optimization

-   Shortest-path calculation.
-   Alternative path generation.
-   Routing table generation.
-   Configurable link costs.
-   Reachability analysis.
-   Redundancy analysis.
-   Single Point of Failure detection.
-   Re-routing after simulated failures.

Dijkstra should be the initial baseline. A\* may be added where a
defensible heuristic exists. Routing behavior must be explicit about
whether links are directed or undirected and how link weights are
interpreted.

### 3.4 Network Analysis Engine

-   Degree and betweenness centrality.
-   Connectivity and connected-component analysis.
-   Network diameter where applicable.
-   Critical node and critical link identification.
-   Bottleneck and cut-set analysis where feasible.
-   Redundancy and path-diversity indicators.

Every metric must have a documented definition and must not be presented
as a real-world measurement.

### 3.5 Network Digital Twin

The Digital Twin is a software model of the designed network, not a live
synchronized copy of a physical network.

It contains:

-   Device and link definitions.
-   Node and link states.
-   Link capacities and costs.
-   Traffic-demand abstractions.
-   Addressing and VLAN assignments.
-   Routing state.
-   Scenario state and simulation assumptions.

The model must support snapshots so that a baseline design can be
compared with modified designs.

### 3.6 Network Simulation Engine

Supported bounded scenarios:

-   Single link failure.
-   Multiple link failures.
-   Node failure.
-   Bandwidth reduction.
-   Increased traffic demand.
-   New department or building.
-   Network expansion.
-   Routing-cost changes.
-   Redundancy and recovery tests.

Simulation outputs may include:

-   Reachability before and after a scenario.
-   Selected paths.
-   Estimated path cost.
-   Modeled link utilization.
-   Congestion indicators.
-   Disconnected nodes or components.
-   Recovery or alternative-path availability.

Latency and throughput must be labeled as estimates derived from stated
model assumptions. Do not imply packet-level fidelity or claim to
reproduce real hardware behavior.

### 3.7 Multi-Objective Optimization Engine

Potential objectives:

-   Minimize modeled path cost or estimated latency.
-   Minimize infrastructure cost proxy.
-   Minimize congestion.
-   Maximize reliability or path diversity.
-   Maximize capacity utilization within safe limits.
-   Minimize unnecessary links or devices.

Algorithms to evaluate:

-   Deterministic graph optimization.
-   Genetic Algorithm (GA).
-   Particle Swarm Optimization (PSO).
-   NSGA-II for multi-objective optimization.

Requirements:

-   Define each objective mathematically.
-   Separate hard constraints from soft objectives.
-   Normalize objective values before weighted aggregation.
-   Provide configurable weights when using a weighted objective.
-   Use Pareto-front comparison for multi-objective results.
-   Compare optimized candidates against a baseline.
-   Record random seeds and algorithm settings.
-   Enforce iteration, population, and runtime limits.
-   Never claim an algorithm found a global optimum unless that is
    mathematically established.

### 3.8 Predictive Capacity Planning

-   User-growth estimation.
-   Traffic-demand forecasting.
-   Bandwidth capacity estimation.
-   Future bottleneck identification.
-   Expansion recommendations.
-   Capacity projection charts.

Forecasting must use historical data supplied by the user or clearly
labeled synthetic/simulated data. The application must never invent
historical measurements. A simple statistical baseline should be
implemented before optional machine-learning models.

### 3.9 Validation Engine

-   Schema and input validation.
-   Topology connectivity validation.
-   IP and subnet overlap validation.
-   Duplicate IP detection.
-   VLAN consistency checks.
-   Routing reachability checks.
-   Link-capacity constraint checks.
-   Redundancy requirement checks.
-   User-defined constraint validation.
-   Optimization result validation.

Validation should return machine-readable findings with severity,
affected entities, explanation, and suggested remediation.

### 3.10 Documentation and Reporting

-   Network architecture summary.
-   Topology diagram.
-   IP addressing plan.
-   VLAN and DHCP tables.
-   Routing tables.
-   Graph analysis results.
-   Simulation scenario reports.
-   Optimization comparisons and Pareto results.
-   Capacity-planning reports.
-   Agent decision and execution trace.
-   Configuration templates, clearly labeled as templates rather than
    device-applied configurations.
-   PDF and CSV exports.

Reports must be generated from validated application data, not directly
from unverified LLM prose.

## 4. Multi-Agent AI architecture

The project must implement a real tool-using, stateful, bounded agent
workflow. Agents are software components with explicit responsibilities,
typed inputs and outputs, and access to deterministic tools. A
collection of role-playing prompts alone does not qualify as a
multi-agent system.

### 4.1 Requirements Understanding Agent

Responsibilities:

-   Interpret natural-language requirements.
-   Extract network size, sites, departments, device counts, and
    constraints.
-   Identify missing or contradictory information.
-   Ask for clarification when essential.
-   Produce a structured requirements object.
-   Record assumptions separately from user-provided facts.

### 4.2 Planning Orchestrator

Responsibilities:

-   Build an execution plan.
-   Delegate tasks to specialized agents.
-   Enforce dependency order.
-   Track workflow state and task results.
-   Handle bounded retries and failures.
-   Trigger re-planning when validation fails.
-   Stop when acceptance criteria are met or a safe limit is reached.
-   Maintain an auditable execution trace.

### 4.3 Topology Design Agent

-   Select suitable topology families.
-   Generate candidate graph structures through tools.
-   Explain architecture trade-offs.
-   Respect node, link, site, and budget constraints.

### 4.4 IP Planning Agent

-   Request deterministic subnet calculations.
-   Allocate address blocks.
-   Plan VLANs and DHCP scopes.
-   Validate overlaps and capacity.
-   Explain address allocation choices.

### 4.5 Routing Agent

-   Select routing assumptions and cost models.
-   Invoke pathfinding tools.
-   Generate route tables.
-   Evaluate alternatives and redundancy.
-   Recalculate after simulated failures.

### 4.6 Capacity Planning Agent

-   Interpret demand inputs.
-   Invoke forecasting and capacity tools.
-   Identify projected constraints.
-   Distinguish measured, user-supplied, and synthetic data.

### 4.7 Optimization Agent

-   Select appropriate objectives and constraints.
-   Configure bounded optimization runs.
-   Generate and compare candidate designs.
-   Explain trade-offs and recommend a candidate.
-   Preserve baseline and candidate metrics.

### 4.8 Simulation Agent

-   Propose scenarios relevant to the design.
-   Invoke the simulation engine.
-   Summarize actual computed results.
-   Identify limitations and assumptions.

### 4.9 Validation and Critic Agent

-   Review candidate designs independently.
-   Invoke deterministic validation tools.
-   Reject invalid candidates.
-   Return structured findings and required corrections.
-   Avoid approving a design solely because another agent says it is
    valid.

### 4.10 Documentation Agent

-   Collect validated results.
-   Explain design choices and trade-offs.
-   Generate reports and export-ready content.
-   Preserve provenance of values and assumptions.

### 4.11 Agent workflow

Requirements → Planning → Topology generation → IP and VLAN planning →
Routing design → Validation → Simulation → Optimization → Re-validation
→ Documentation → Final Network Blueprint

Conditional branches are required. For example, if validation detects an
IP overlap, the workflow should return the relevant issue to the IP
Planning Agent, not restart every stage unnecessarily.

### 4.12 Agent engineering requirements

-   Typed input and output schemas.
-   Tool registry with explicit contracts.
-   Bounded retries and execution steps.
-   Timeout and failure handling.
-   Structured LLM output parsing.
-   Validation of every LLM-generated object.
-   No direct execution of arbitrary LLM-generated Python or shell
    commands.
-   Agent trace with inputs, outputs, tools, status, and timestamps
    where available.
-   Graceful operation when the LLM provider is unavailable.
-   Deterministic Demo Mode.

## 5. Technology stack

  Layer                   Preferred technology
  ----------------------- --------------------------------
  Language                Python 3.12
  UI                      Streamlit
  LLM provider            Groq API, optional
  Agent orchestration     Custom Python workflow
  Data validation         Pydantic
  Graph modeling          NetworkX
  IP addressing           Python `ipaddress`
  Numerical computing     NumPy
  Scientific algorithms   SciPy
  Data processing         Pandas
  Visualization           Plotly
  Reports                 ReportLab
  Testing                 Pytest
  Linting                 Ruff
  Type checking           mypy or Pyright, if practical
  Version control         Git and GitHub
  Deployment              Streamlit Community Cloud Free

Prefer a small dependency footprint. Add a library only when it provides
clear value and is compatible with the deployment environment.

### LLM integration

-   Keep the LLM provider behind a provider/client interface.
-   Store API keys in Streamlit secrets or environment variables.
-   Never commit secrets.
-   Validate structured responses with Pydantic.
-   Handle rate limits, timeouts, malformed responses, and provider
    outages.
-   Do not require an API key for core deterministic functionality.
-   Provide a visible Demo Mode and clear indication when AI features
    are unavailable.

## 6. Software architecture

Use a modular layered architecture.

### Presentation layer

-   Streamlit pages.
-   Forms and controls.
-   Interactive diagrams.
-   Charts and tables.
-   Downloadable reports.

### Application layer

-   Use cases.
-   Workflow controller.
-   Agent coordination.
-   Session management.
-   Application services.

### Agentic intelligence layer

-   Agent interfaces and implementations.
-   Orchestrator.
-   LLM provider client.
-   Tool registry.
-   Decision explanation.
-   Execution trace.

### Network engineering layer

-   Topology generation.
-   IP addressing.
-   VLAN planning.
-   Routing.
-   Graph analysis.
-   Validation.

### Simulation and optimization layer

-   Digital Twin state.
-   Scenario engine.
-   Simulation metrics.
-   Objective functions.
-   Constraints.
-   Optimization algorithms.
-   Candidate comparison.

### Data and infrastructure layer

-   Pydantic schemas.
-   JSON and CSV import/export.
-   Session state.
-   Configuration.
-   Logging and error handling.

Critical engineering calculations must remain in deterministic Python
services. The LLM can interpret, plan, coordinate, and explain; it must
not be the source of truth for calculations.

## 7. Application pages

1.  **Dashboard** --- project overview, recent session summary, design
    metrics, and shortcuts.
2.  **AI Network Designer** --- natural-language and structured
    requirements.
3.  **Topology Editor** --- interactive graph creation and editing.
4.  **IP Addressing & Subnetting** --- IPv4/IPv6, VLSM, CIDR, and
    allocation.
5.  **VLAN & DHCP Planner** --- segmentation and address scope planning.
6.  **Routing Analysis** --- paths, route tables, reachability, and
    redundancy.
7.  **Network Analytics** --- graph metrics and critical components.
8.  **Digital Twin** --- modeled network state and snapshots.
9.  **Simulation Lab** --- what-if scenarios and result comparisons.
10. **Optimization Center** --- objectives, constraints, algorithms, and
    Pareto results.
11. **Capacity Planning** --- demand projections and expansion planning.
12. **Agent Control Center** --- workflow steps, agent results, errors,
    and trace.
13. **Reports & Documentation** --- report generation and exports.
14. **Settings** --- API configuration, demo mode, and resource limits.

Pages should be introduced progressively. Do not build all pages as
disconnected mockups before the underlying services work.

## 8. Repository structure

The structure below is a target, not a reason to create empty files
prematurely.

``` text
NetArchitect-AI/
├── app.py
├── requirements.txt
├── packages.txt
├── README.md
├── AI_INSTRUCTIONS.md
├── CURRENT_STATUS.md
├── .gitignore
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── config/
│   ├── settings.py
│   └── limits.py
├── core/
│   ├── schemas/
│   ├── exceptions/
│   └── constants/
├── agents/
│   ├── base_agent.py
│   ├── orchestrator.py
│   ├── requirements_agent.py
│   ├── topology_agent.py
│   ├── ip_agent.py
│   ├── routing_agent.py
│   ├── capacity_agent.py
│   ├── optimization_agent.py
│   ├── simulation_agent.py
│   ├── critic_agent.py
│   └── documentation_agent.py
├── network/
│   ├── topology/
│   ├── addressing/
│   ├── vlan/
│   ├── routing/
│   ├── analysis/
│   └── validation/
├── digital_twin/
│   ├── models/
│   ├── state/
│   └── scenarios/
├── simulation/
│   ├── engine.py
│   ├── events.py
│   ├── traffic.py
│   ├── failures.py
│   └── metrics.py
├── optimization/
│   ├── objectives/
│   ├── constraints/
│   ├── algorithms/
│   └── evaluation/
├── forecasting/
│   ├── preprocessing/
│   ├── models/
│   └── evaluation/
├── services/
│   ├── llm/
│   ├── workflow/
│   ├── reporting/
│   └── export/
├── ui/
│   ├── pages/
│   ├── components/
│   └── visualization/
├── data/
│   └── samples/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── agents/
│   ├── simulation/
│   ├── optimization/
│   └── ui/
└── docs/
    ├── PROJECT_BLUEPRINT.md
    ├── ARCHITECTURE.md
    ├── REQUIREMENTS.md
    ├── ROADMAP.md
    ├── AGENT_SPECIFICATIONS.md
    ├── API_CONTRACTS.md
    ├── TEST_STRATEGY.md
    ├── DEPLOYMENT.md
    └── CHANGELOG.md
```

## 9. Fourteen-phase development roadmap

Every phase must have a scope, small tasks, acceptance criteria, tests,
and a documented handoff. A phase is complete only when its exit
criteria pass.

### Phase 1 --- Project Foundation and Environment

Tasks: - Create the GitHub repository. - Initialize the Python project
and virtual environment. - Add the initial Streamlit entry point. - Add
dependency management. - Configure environment variables and secrets
handling. - Create `.gitignore`. - Add README and project
documentation. - Add `AI_INSTRUCTIONS.md` and `CURRENT_STATUS.md`. -
Establish formatting, linting, and test commands. - Verify the
application starts locally.

Deliverable: A clean, runnable project skeleton.

Exit criteria: - Application starts locally. - No secrets are
committed. - Dependencies install from a clean environment. - Basic test
and lint commands run. - Project instructions and status files exist.

### Phase 2 --- Requirements and Domain Modeling

Tasks: - Define organization, site, department, and user models. -
Define device and link schemas. - Define topology and network
requirement schemas. - Define IP, subnet, VLAN, and DHCP schemas. -
Define routing and traffic-demand schemas. - Define simulation scenarios
and results. - Define optimization objectives and constraints. - Define
validation findings. - Add schema validation tests and sample fixtures.

Deliverable: Validated domain models and contracts.

Exit criteria: - Valid and invalid inputs are tested. - Schemas are
documented. - No UI or LLM dependency is required by the domain models.

### Phase 3 --- Network Topology Engine

Tasks: - Implement graph creation and serialization. - Implement
supported topology generators incrementally. - Add node and edge
metadata. - Support topology editing operations. - Validate node
identifiers and link endpoints. - Implement connectivity checks. -
Render interactive topology diagrams. - Add import/export of topology
JSON.

Deliverable: Functional Network Designer foundation.

Exit criteria: - Each supported topology has tests. - Graph
serialization round-trips correctly. - Invalid links and duplicate
identifiers are rejected. - Visualization reflects the actual graph.

### Phase 4 --- IP Addressing and VLAN Engine

Tasks: - Implement IPv4 and IPv6 network calculations. - Implement CIDR
and VLSM allocation. - Implement deterministic subnet allocation. - Add
subnet overlap detection. - Add duplicate IP detection. - Implement VLAN
planning and department mapping. - Implement DHCP scope planning. -
Calculate address utilization. - Generate IP and VLAN tables.

Deliverable: Functional IP and segmentation planner.

Exit criteria: - Calculations are tested against known cases. -
Overlapping allocations are detected. - Allocation respects requested
host counts and reserved addresses. - No LLM-generated arithmetic is
trusted.

### Phase 5 --- Routing and Graph Analysis Engine

Tasks: - Implement weighted shortest paths. - Implement alternative
paths. - Define link-cost semantics. - Generate routing tables. -
Implement reachability checks. - Calculate graph metrics. - Identify
critical nodes and links. - Analyze redundancy and single points of
failure. - Add deterministic tests.

Deliverable: Functional routing and graph analysis engine.

Exit criteria: - Paths are valid for the graph and weights. -
Disconnected cases are handled. - Failure cases produce correct
reachability results. - Metric definitions are documented.

### Phase 6 --- Network Digital Twin

Tasks: - Define the Digital Twin state model. - Represent device and
link states. - Represent capacities and traffic demands. - Connect
topology, addressing, VLAN, and routing data. - Add baseline
snapshots. - Add scenario copies that do not mutate the baseline. - Add
model validation. - Add serialization and restoration from JSON.

Deliverable: Software-based Network Digital Twin.

Exit criteria: - A model can be created, serialized, restored, and
validated. - Scenario changes do not corrupt the baseline. - All modeled
properties have documented meaning.

### Phase 7 --- Network Simulation Engine

Tasks: - Implement simulation inputs and assumptions. - Implement link
failure. - Implement node failure. - Implement bandwidth reduction. -
Implement increased traffic demand. - Implement network expansion
scenarios. - Recalculate reachability and routes. - Calculate modeled
utilization and congestion indicators. - Compare baseline and scenario
results. - Enforce node, link, scenario, and runtime limits.

Deliverable: Interactive Simulation Lab.

Exit criteria: - Scenarios are reproducible. - Failed components are
excluded from post-failure paths. - Results are traceable to model
inputs. - Estimated metrics are labeled as modeled estimates.

### Phase 8 --- Multi-Objective Optimization Engine

Tasks: - Define objective functions and units. - Define hard constraints
and soft objectives. - Create baseline candidate evaluation. - Implement
a deterministic baseline optimizer. - Implement Genetic Algorithm. -
Implement PSO. - Implement NSGA-II if feasible within resource limits. -
Normalize objective values where required. - Generate candidate
designs. - Compare candidates with the baseline. - Visualize Pareto
fronts. - Record seeds, settings, and execution limits.

Deliverable: Network Optimization Center.

Exit criteria: - Every candidate passes hard constraints before
recommendation. - Baseline and optimized metrics are comparable. -
Optimization is reproducible with fixed seeds. - The application reports
trade-offs rather than claiming one design is universally best.

### Phase 9 --- Agentic AI Framework

Tasks: - Implement provider-independent LLM client interface. - Add
optional Groq client. - Implement structured output parsing. - Define
base agent interface. - Implement tool registry and contracts. -
Implement orchestrator and workflow state. - Implement task delegation
and dependencies. - Add bounded retries and failure handling. - Add
execution trace. - Add Demo Mode without an LLM. - Test provider failure
and malformed outputs.

Deliverable: Reusable Agentic Framework.

Exit criteria: - Agents can call approved tools. - Invalid LLM outputs
are rejected. - Workflows terminate within configured limits. - Core
deterministic functionality works without an API key.

### Phase 10 --- Specialized AI Agents

Tasks: - Implement Requirements Understanding Agent. - Implement
Topology Design Agent. - Implement IP Planning Agent. - Implement
Routing Agent. - Implement Capacity Planning Agent. - Implement
Optimization Agent. - Implement Simulation Agent. - Implement Validation
and Critic Agent. - Implement Documentation Agent. - Integrate agents
through the orchestrator. - Test end-to-end workflow and failure
branches.

Deliverable: Integrated Multi-Agent System.

Exit criteria: - Each agent has a defined contract and tool access. -
Workflow branches according to actual tool results. - Critic can reject
invalid designs. - Execution traces show agent handoffs and outcomes. -
No agent can execute arbitrary shell or Python code generated by the
LLM.

### Phase 11 --- Predictive Capacity Planning

Tasks: - Define accepted historical data format. - Add data validation
and missing-value handling. - Implement a simple statistical baseline. -
Add optional ML forecasting if justified. - Forecast user or traffic
demand. - Estimate capacity requirements. - Identify future
bottlenecks. - Generate expansion recommendations. - Evaluate
forecasting error on held-out chronological data.

Deliverable: Predictive Capacity Planning module.

Exit criteria: - Forecasts use supplied or clearly synthetic data. - No
fabricated historical observations are shown. - Forecast evaluation and
assumptions are documented. - Resource use is bounded.

### Phase 12 --- Explainability and Documentation

Tasks: - Explain topology selection. - Explain IP and VLAN allocation. -
Explain routing choices. - Explain optimization objectives and
trade-offs. - Explain simulation assumptions and outcomes. - Collect
agent execution traces. - Generate architecture reports. - Generate PDF
reports. - Generate CSV tables. - Generate configuration templates. -
Test report consistency against application data.

Deliverable: Automated Network Documentation System.

Exit criteria: - Reports match validated computed results. - Assumptions
and estimates are clearly labeled. - Exports are downloadable without
persistent server storage.

### Phase 13 --- Frontend Integration and User Experience

Tasks: - Build the dashboard. - Integrate AI Network Designer. -
Integrate Topology Editor. - Integrate IP and VLAN planners. - Integrate
Routing Analysis. - Integrate Network Analytics. - Integrate Digital
Twin. - Integrate Simulation Lab. - Integrate Optimization Center. -
Integrate Capacity Planning. - Integrate Agent Control Center. -
Integrate Reports and Settings. - Add navigation, validation messages,
loading states, and error handling. - Verify responsive layouts and
session behavior.

Deliverable: Complete integrated application.

Exit criteria: - UI pages use real application services. - No critical
feature is only a mockup. - User workflows are understandable and
consistent. - Session state and downloads work as expected.

### Phase 14 --- Testing, Security, and Deployment

Tasks: - Run all unit tests. - Run integration tests. - Run agent
workflow tests. - Verify network calculation correctness. - Verify
simulation correctness. - Verify optimization constraints. - Test
invalid and adversarial inputs. - Test missing API keys and provider
outages. - Review secrets handling and logs. - Measure memory and
execution time. - Enforce resource limits. - Test a clean deployment
build. - Deploy to Streamlit Community Cloud Free. - Document setup and
known limitations. - Tag a release.

Deliverable: Tested and deployable graduation project.

Exit criteria: - Critical test suites pass. - No secrets are exposed. -
Demo Mode works. - App starts on the target deployment. - Memory and
execution remain within observed free-tier limits. - Known limitations
are documented.

## 10. Streamlit Community Cloud Free constraints

These are mandatory design constraints, not optional optimizations.

-   No physical network equipment.
-   No dedicated server.
-   No Docker or Containerlab requirement.
-   No privileged operations.
-   No opening ports.
-   No persistent background workers.
-   No always-on service.
-   No local persistent storage dependency.
-   No mandatory paid API or database.
-   No unbounded simulations or optimization runs.

Implementation rules:

-   Use Streamlit Session State for temporary interactive state.
-   Use JSON/CSV downloads for user-owned exports.
-   Use optional Groq integration; do not make it mandatory for core
    features.
-   Provide deterministic Demo Mode.
-   Handle application restarts and ephemeral storage.
-   Keep secrets in Streamlit secrets or environment variables.
-   Never print API keys or sensitive values to logs.
-   Use bounded node, edge, scenario, population, iteration, and time
    limits.
-   Cache only safe, reproducible computations.
-   Avoid storing large duplicate graph or simulation objects in session
    state.
-   Test actual deployment behavior; do not assume free-tier resource
    limits.

The platform must clearly disclose that simulations are abstract models
and not packet-level or hardware-accurate network emulation.

## 11. Quality assurance and acceptance criteria

Every module must include: 1. Unit tests. 2. Input validation. 3. Error
handling. 4. Deterministic behavior where applicable. 5. Integration
tests where relevant. 6. Documentation. 7. Resource limits.

System-wide acceptance criteria:

-   No unintended subnet overlap.
-   No duplicate IP allocation.
-   All generated routes correspond to valid graph paths.
-   Failed links and nodes are excluded from post-failure routes.
-   Simulation results are reproducible with fixed inputs and seeds.
-   Optimization respects hard constraints.
-   Optimized designs are compared against a baseline.
-   Agents do not invent engineering calculations.
-   Invalid LLM output cannot bypass schemas and validators.
-   Reports reflect actual computed results.
-   Demo Mode works without external AI access.
-   The application can be deployed within the target environment's
    observed limits.

## 12. Vibe Coding protocol and human product quality

All AI coding tools must follow the same protocol. The project is intentionally being built through **human-directed Vibe Coding**: the project owner sets direction and reviews decisions, while coding agents accelerate implementation. The tools must behave like disciplined engineering collaborators, not autonomous product owners.

### 12.1 Human-directed development

- Treat the project owner as the decision-maker for scope, priorities, product behavior, and major architectural changes.
- Break work into small, concrete tasks. Do not attempt to generate the entire system in one prompt.
- Before coding, summarize the task, inspect relevant code, identify dependencies, and propose a short implementation plan.
- Ask for clarification when a requirement is genuinely ambiguous or when a decision could change scope, cost, security, or deployment compatibility.
- For routine, low-risk implementation details, make a sensible choice consistent with this blueprint and document it rather than repeatedly asking unnecessary questions.
- Do not claim that code was run, tests passed, or deployment succeeded unless those actions were actually performed and their results inspected.
- Clearly distinguish implemented behavior from mockups, placeholders, planned work, and simulated results.

### 12.2 Human-quality product design — avoid generic AI-generated appearance

The finished application must look and behave like a carefully designed professional network-engineering product. It must not feel like a generic AI-generated demo, template, or chatbot wrapper.

Design and implementation expectations:

- Use a consistent visual identity, restrained color palette, clear typography, spacing, and meaningful information hierarchy.
- Prioritize network-engineering workflows, diagrams, tables, metrics, and scenario comparisons over decorative AI graphics.
- Use natural, concise, technically accurate interface language. Avoid repetitive AI-style phrases, exaggerated claims, generic marketing copy, and unnecessary emojis.
- Do not put an AI badge, chatbot, sparkle icon, or "Ask AI" element on every page. AI should appear where it provides real value.
- Avoid generic dashboard cards that show meaningless placeholder numbers. Every metric must have a defined meaning and a real data source within the application.
- Use realistic empty states, helpful validation, actionable error messages, clear loading states, and sensible defaults.
- Make topology diagrams readable and useful, with consistent node/link semantics and legends.
- Keep charts, labels, units, and status indicators technically meaningful and consistent.
- Ensure the interface is responsive and usable, not merely visually impressive in a screenshot.
- Do not use fake customer data, fabricated performance claims, or invented simulation results. Sample data must be clearly identified as sample/demo data.
- Avoid unnecessary animations, gradients, glass effects, excessive rounded cards, and visual clutter. Use them only when they support usability.
- Make the product feel cohesive across all pages; do not let each generated page look like it came from a different template.

The goal is a polished, credible engineering application with natural product language and professional UX. This is a design-quality requirement; it does not mean concealing the use of AI coding tools or misrepresenting how the product works.

### 12.3 Engineering workflow


### Rule 1 --- Read before coding

Before modifying code, inspect: - `AI_INSTRUCTIONS.md` -
`CURRENT_STATUS.md` - `docs/PROJECT_BLUEPRINT.md` -
`docs/ARCHITECTURE.md` - `docs/ROADMAP.md` - The relevant module
specifications. - Git status and current branch.

### Rule 2 --- Work in small tasks

Do not ask an AI coding tool to build the whole application in one
prompt. Implement one bounded task at a time with explicit inputs,
outputs, acceptance criteria, and tests.

### Rule 3 --- Preserve architecture

-   Do not duplicate existing functionality.
-   Do not mix UI and engineering logic.
-   Do not bypass schemas or validation.
-   Do not introduce excluded infrastructure.
-   Do not add dependencies without explaining why.
-   Do not silently change public interfaces.
-   Do not replace deterministic calculations with LLM guesses.

### Rule 4 --- Verify every task

After each task: - Run relevant tests. - Run linting and type checks
where configured. - Check imports and application startup. - Inspect
changed files and diffs. - Verify deployment compatibility. - Update
documentation and status.

### Rule 5 --- Maintain project memory

Update: - `CURRENT_STATUS.md` - `docs/ROADMAP.md` -
`docs/CHANGELOG.md` - Relevant module specifications.

Record completed work, test evidence, known issues, and the next task.

### Rule 6 --- Git discipline

-   Use feature branches for independent work.
-   Commit tested changes.
-   Avoid large unreviewed changes.
-   Do not allow multiple coding agents to modify the same working tree
    simultaneously.
-   Review and test merges.

### Rule 7 --- Evidence-based completion

Generated code is not proof of completion. A task is complete only when
its acceptance criteria pass and evidence is recorded.

### Rule 8 --- Ask before changing scope

If a task appears to require a new external service, paid service,
server, database, privileged operation, or excluded capability, stop and
propose a compliant alternative instead of implementing it.

## 13. Suggested `AI_INSTRUCTIONS.md` starter content

``` text
You are contributing to NetArchitect AI.

Before coding:
1. Read CURRENT_STATUS.md.
2. Read docs/PROJECT_BLUEPRINT.md.
3. Read relevant architecture and module documents.
4. Inspect the existing implementation and Git status.

Project mission:
Build a pure-software, agentic network architecture design,
simulation, and optimization platform.

Development method:
- This project is built through human-directed Vibe Coding.
- Work in small tasks and verify every change.
- The human project owner controls scope and major decisions.
- Inspect the real repository before assuming its structure.
- The example repository structure in the blueprint is flexible.
- You may propose and implement justified repository restructuring.
- Do not reorganize files just to match a template.

Product quality:
- Build a polished, professional network-engineering product.
- Avoid generic AI-generated dashboard aesthetics and repetitive AI wording.
- Use meaningful data, realistic states, clear diagrams, and technically accurate labels.
- Do not fabricate metrics, test results, or customer data.
- Do not hide or misrepresent the use of AI; simply make the product UX natural and professional.

Non-negotiable constraints:
- Streamlit Community Cloud Free is the deployment target.
- No physical networking equipment.
- No dedicated server.
- No Docker or Containerlab dependency.
- No privileged operations or port opening.
- No persistent background workers.
- No local persistent storage dependency.
- No mandatory paid API or database.
- No NetPilot monitoring/administration features.
- No Pentesting or SOC features.

Engineering rules:
- Keep UI, application, agent, and network-engineering layers separate.
- Use deterministic Python for network calculations.
- Validate all LLM outputs with typed schemas.
- Never execute arbitrary code generated by an LLM.
- Bound all loops, simulations, optimization runs, and retries.
- Provide Demo Mode without an LLM API key.
- Add tests for every meaningful behavior.
- Do not claim completion without passing tests.

Workflow:
1. State the task and acceptance criteria.
2. Inspect relevant files.
3. Propose a minimal implementation plan.
4. Implement only the requested task.
5. Run relevant tests and checks.
6. Report changed files and test evidence.
7. Update CURRENT_STATUS.md and relevant documentation.
8. State remaining issues and the next recommended task.

Do not change project scope or architecture silently.
```

## 14. Progress tracking and status management

Maintain `CURRENT_STATUS.md` in the repository using this template:

``` markdown
# Current Project Status

## Overall
- Current phase:
- Current task:
- Overall status: Not Started / In Progress / Blocked / Complete
- Last updated:

## Completed
- [ ] Phase 1:
- [ ] Phase 2:
- [ ] Phase 3:
- [ ] Phase 4:
- [ ] Phase 5:
- [ ] Phase 6:
- [ ] Phase 7:
- [ ] Phase 8:
- [ ] Phase 9:
- [ ] Phase 10:
- [ ] Phase 11:
- [ ] Phase 12:
- [ ] Phase 13:
- [ ] Phase 14:

## Current task
- Objective:
- Files expected to change:
- Acceptance criteria:
- Tests to run:

## Test evidence
- Commands:
- Results:
- Known failures:

## Known issues
- None / List issues.

## Next task
- Description:
- Dependencies:
```

## 15. Development priority

### P0 --- Essential

-   Topology generation.
-   IP and VLSM.
-   VLAN planning.
-   Routing.
-   Validation.
-   Digital Twin.
-   Bounded simulation.
-   Agent orchestrator.
-   Demo Mode.
-   Free-tier deployment compatibility.

### P1 --- High value

-   Multi-objective optimization.
-   Critic Agent.
-   Explainability.
-   Scenario comparison.
-   Documentation and reports.
-   Agent execution traces.

### P2 --- Advanced

-   Predictive capacity planning.
-   Additional optimization algorithms.
-   Advanced topology editing.
-   More sophisticated forecasting.
-   Advanced visual analytics.

Priorities do not override the phase dependencies. Build the
deterministic engineering foundation before relying on agents to
coordinate it.

## 16. Final definition of done

NetArchitect AI is complete when:

-   The main network engineering modules work.
-   Topology generation and editing are functional.
-   IP and VLAN plans are mathematically validated.
-   Routing and graph analysis are correct.
-   The Digital Twin supports bounded scenarios.
-   Simulation results are reproducible and clearly labeled.
-   Multiple optimization approaches can be compared against a baseline.
-   Agentic workflows use real tools and conditional task execution.
-   The Critic Agent can reject invalid designs.
-   Explanations and reports reflect validated results.
-   Demo Mode works without an LLM API.
-   The integrated Streamlit application deploys on the target free
    tier.
-   Tests, setup instructions, architecture, limitations, and status are
    documented.

**Final goal:** Deliver a reliable, explainable, software-based Agentic
Network Engineering platform that designs, simulates, validates, and
optimizes network architectures without physical networking
infrastructure.

------------------------------------------------------------------------

## 17. Recommended first execution task

Start with Phase 1 only. The coding assistant must first inspect the actual repository. If the repository already contains useful files or an established structure, preserve and build on them rather than replacing them to match the example tree.

Ask the coding assistant to: 1. Inspect the empty or existing
repository. 2. Create the minimal project skeleton. 3. Add Streamlit
startup. 4. Add dependency and secrets configuration. 5. Add
`AI_INSTRUCTIONS.md` and `CURRENT_STATUS.md`. 6. Add a basic smoke test.
7. Run the application and tests. 8. Report exact files changed and test
evidence.

Do not begin Phase 2 until Phase 1 acceptance criteria pass.
