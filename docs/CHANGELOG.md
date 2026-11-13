# Changelog

All notable changes to NetArchitect AI are recorded here. Dates are ISO-8601.

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
