# Current Project Status

## Overall
- Current phase: Phase 5 - Routing and Graph Analysis Engine (complete)
- Current task: Phase 5c - routing and analytics pages (complete)
- Overall status: In progress
- Last updated: 2026-11-12
- Branch: `feature/phase5-routing` (based on merged `main` commit `3a88c48`)

## Completed
- [x] Phase 1: Project Foundation and Environment
- [x] Phase 2: Requirements and Domain Modeling
- [x] Phase 3: Network Topology Engine
- [x] Phase 4: IP Addressing and VLAN Engine
- [x] Phase 5: Routing and Graph Analysis Engine
- [ ] Phase 6: Network Digital Twin
- [ ] Phase 7: Network Simulation Engine
- [ ] Phase 8: Multi-Objective Optimization Engine
- [ ] Phase 9: Agentic AI Framework
- [ ] Phase 10: Specialized AI Agents
- [ ] Phase 11: Predictive Capacity Planning
- [ ] Phase 12: Explainability and Documentation
- [ ] Phase 13: Frontend Integration and User Experience
- [ ] Phase 14: Testing, Security, and Deployment

## Task 0 evidence (verification and version control)
- `python --version`: `Python 3.11.15` (system interpreter and `.venv`).
- Phase 1-2 baseline re-verified before changes:
  - `python -m pytest -q`: `114 passed in 1.33s`
  - `python -m ruff check .`: `All checks passed!`
- Secrets scan over the working tree (excluding `.venv`, caches, `.agents`):
  no API keys, tokens, or passwords found. `.streamlit/secrets.toml.example`
  contains placeholders only. Real `.streamlit/secrets.toml` is absent.
- `.gitignore` verified to exclude `.venv/`, `.streamlit/secrets.toml`,
  `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.agents/`, and logs.
- `git init` performed; `main` created; commit
  `d24c75c Phase 1-2: foundation and domain schemas` contains the verified
  Phase 1-2 baseline (no secrets, no virtualenv, no agent scratch files).
- Working branch created: `feature/phase3-topology`.

## Phase 3a delivered - topology engine core
Location: `network/topology/` (pure Python, no Streamlit, no LLM, no I/O).

- `graph.py`
  - `to_networkx` always returns `networkx.MultiDiGraph`; directed links are
    one arc, undirected links are two reciprocal arcs tagged `directed=False`.
  - Graph metadata stores the topology name and overall directedness
    (`undirected`, `directed`, `mixed`).
  - `from_networkx` reconstructs the exact topology, including endpoint order,
    and accepts plain `Graph`/`DiGraph` inputs with typed `SchemaError` on bad
    node/link attributes.
- `operations.py`
  - `add_device`, `remove_device`, `update_device`, `add_link`, `remove_link`,
    `update_link`, `enforce_limits`.
  - Pure functions: input topology is never mutated; every result is
    re-validated.
  - Raises `DuplicateIdError`, `MissingEndpointError`, `DeviceNotFoundError`,
    `LinkNotFoundError`, `LimitsExceededError` with specific messages.
  - Device removal cascades attached links; `MAX_NODES`/`MAX_EDGES` are
    enforced on adds and via `enforce_limits`.
- `connectivity.py`
  - Frozen `ConnectivityReport` / `ConnectedComponent` Pydantic models.
  - Physical connectivity: directed links count both ways; empty topology is
    not connected; isolated devices are listed.
- `serialization.py`
  - `to_json` / `from_json`; exact round-trip (`from_json(to_json(t)) == t`
    and byte-stable re-export); limits enforced on both paths.
- `generators.py`
  - Deterministic `generate_star`, `generate_ring`, `generate_mesh`,
    `generate_tree`; counts validated against limits before construction.

## Phase 3b delivered - remaining generators and Topology Editor
### Generators (`network/topology/generators.py`)
- `generate_hierarchical_campus(distribution_count, access_per_distribution,
  redundant_uplinks)`:
  - Devices `(2 if redundant else 1) + D + D*A`.
  - Links `(2 if redundant else 1) * D + (2 if redundant else 1) * D*A`.
  - Single-homed: every distribution switch uplinks to the single core router.
  - Redundant: two core routers; every distribution switch dual-homes to both
    and every access switch dual-homes to two adjacent distribution switches
    (ring order). Requires `distribution_count >= 2`.
- `generate_spine_leaf(spines, leaves, full_mesh)`:
  - Devices `spines + leaves`.
  - Links `spines * leaves` when `full_mesh=True`; otherwise
    `leaves * min(spines, 2)` (each leaf dual-homes to a rotating adjacent
    spine pair, keeping the fabric connected).
- `generate_hybrid(core_nodes, access_per_core)`:
  - Composition: `generate_ring` core plus one `generate_star` cluster per ring
    node; star hubs are re-roled to `distribution`; joined by one uplink per
    ring node.
  - Devices `core_nodes * (2 + access_per_core)`.
  - Links `core_nodes * (access_per_core + 2)`.
- All three reject invalid parameters with `ValueError` and oversized requests
  with `LimitsExceededError` before building anything.

### Topology Editor (`ui/pages/topology_editor.py`, `app.py`)
- New page wired into a sidebar `st.selectbox` (`page_nav`); Dashboard and
  Topology Editor are functional, all other planned pages keep their
  placeholder state.
- Generator selection and parameters for all seven families, with generate,
  connectivity summary (devices, links, components, isolated devices), Plotly
  diagram, device/link `st.data_editor` tables, and JSON download/upload.
- UI delegates all engineering to `network.topology`; it contains no graph or
  validation logic of its own.
- One session-state key holds the model: `st.session_state["topology"]`. One
  extra key (`topology_editor_flash`) holds short-lived success messages.
- Ids are immutable; renamed id columns and invalid rows are rejected with an
  inline `st.error` and never written to state. Limit errors from the engine
  surface as readable messages.
- Deterministic diagram layout (`nx.spring_layout(seed=42)`), role-colored
  nodes, and a legend for node roles and link direction.
- App icon changed to `:material/hub:`; no emojis or decorative elements.

### Tests
- 16 new generator tests: count formulas, connectivity, degrees for
  dual-homing, invalid parameters, node/edge limit rejection, no duplicate
  ids, JSON round-trip, determinism.
- `tests/unit/ui/test_topology_editor.py`: AppTest smoke test that loads the
  app, navigates to the editor, generates a star, and asserts the resulting
  topology and chart.

## Phase 4a delivered - addressing engine
Location: `network/addressing/` (pure Python, stdlib `ipaddress` only, no
Streamlit, no LLM, no new dependencies). Engines are stateless functions that
return new typed Pydantic results.

- `cidr.py`
  - `calculate_subnet` returns `SubnetInfo` with normalized network, version,
    prefix length, IPv4 netmask and wildcard mask, network/broadcast/last
    addresses, first/last usable host, usable count, total count, and a
    `special_case` marker.
  - Documented special prefixes: IPv4 `/31` (RFC 3021, two usable, no
    broadcast) and `/32` (one usable); IPv6 `/127` (RFC 6164, two usable) and
    `/128` (one usable). Ordinary IPv6 prefixes exclude the subnet-router
    anycast address, so usable = total - 1.
  - Host bits in input strings are normalized (`10.0.0.5/24` -> `10.0.0.0/24`).
- `vlsm.py`
  - `allocate_vlsm(parent, requirements, reserved_addresses=None)` sorts
    largest-first with stable input-order ties, picks the smallest permitted
    prefix that fits `required_hosts + reserved`, and carves blocks
    sequentially so allocations never overlap and always lie inside the parent.
  - Reserved-address defaults: 3 for IPv4 (network, broadcast, gateway) and
    2 for IPv6 (anycast, gateway); minimums are 2 and 1. Allocation is capped
    at `/30` (IPv4) and `/126` (IPv6); point-to-point prefixes are available
    from the CIDR calculator but are not produced by VLSM.
  - Insufficient space raises `InsufficientAddressSpaceError` listing every
    requirement that could not be placed; no partial result and no silent
    truncation. Duplicate names, invalid reserved counts, and limits are
    rejected before allocation.
- `validation.py`
  - `detect_overlaps` returns one `Finding` per overlapping subnet pair;
    touching blocks and mixed IP versions produce no finding.
  - `detect_duplicate_ips` returns one finding per address assigned to more
    than one entity. `validate_addressing` aggregates both into the existing
    `ValidationReport` contract.
- `utilization.py`
  - Per-subnet used/usable/remaining addresses and percent utilization, plus
    parent totals when a parent is supplied. Usage above capacity, mismatched
    versions, and subnets outside the parent are rejected.
  - All counts are prefix arithmetic; large IPv6 blocks are never enumerated.
- `tables.py` returns plain row dictionaries for UI-independent presentation.
- `config/limits.py` adds `MAX_SUBNETS = 256` and
  `MAX_HOSTS_PER_SUBNET = 1_000_000`; `core.exceptions` adds
  `InsufficientAddressSpaceError`.

## Phase 4b delivered - VLAN and DHCP
Location: `network/vlan/` (plain dict rows, UI-agnostic).

- `plan.py`
  - `plan_vlans` maps one department to one VLAN id and one subnet. IDs are
    validated against 1-4094; reserved IDs `{1, 1002, 1003, 1004, 1005}` are
    never auto-assigned, and `0`/`4095` are rejected as out of schema range.
  - Auto-assignment starts at 10 and skips reserved and already-used IDs.
    Explicit IDs are validated and checked for duplicates against both explicit
    and automatic assignments. Duplicate departments/subnet names and
    overlapping subnets are rejected with typed exceptions.
- `dhcp.py`
  - `plan_dhcp_scope` reserves the network/anycast address, gateway (default
    first usable), and IPv4 broadcast, validates caller exclusions, and derives
    the first contiguous free pool when boundaries are omitted.
  - Explicit pools must lie inside the usable range and must not include a
    gateway, reserved address, or exclusion. `validate_dhcp_scope` reports
    pool, gateway, exclusion, version, and boundary violations as `Finding`
    objects. `/32` and `/128` subnets have no DHCP pool.
- `tables.py` provides `vlan_rows`; `dhcp_scope_rows` provides one row per
  scope with pool size and exclusions.

## Phase 4c delivered - planning pages
- `ui/pages/ip_addressing.py`: CIDR calculator (IPv4/IPv6, special-prefix
  caption), VLSM planner with editable requirement table, allocation table,
  utilization progress bars, subnet-overlap checker, and CSV downloads.
- `ui/pages/vlan_dhcp.py`: editable department requirements (prefilled from
  `st.session_state["organization"]` when present), VLAN mapping table, DHCP
  scope table, validation findings, and CSV downloads.
- `ui/components.py`: shared validation-error formatting, CSV serialization,
  and findings table rendering.
- `app.py` routes `IP Addressing & Subnetting` and `VLAN & DHCP Planner`;
  sidebar and dashboard text updated. The remaining planned pages are still
  placeholders.
- Session state holds only derived results: `ip_cidr_result`,
  `addressing_result`, `addressing_check_report`, and `vlan_plan_result`.
  Topology and organization state are read, never duplicated.

## Phase 5a delivered - routing engine
Location: `network/routing/` (pure Python plus NetworkX, no Streamlit, no LLM,
no new dependencies). Every function is stateless: it takes a `Topology` and
optional failed device/link ids and returns new typed Pydantic results. The
input topology is never modified.

- Link semantics (documented in `graph.py`):
  - `Link.directed=True` adds one directed arc from `endpoints[0]` to
    `endpoints[1]`; an undirected link adds reciprocal arcs.
  - `Link.cost` is the edge weight; `capacity_mbps` is metadata only and never
    participates in path selection.
  - Parallel links between the same ordered pair collapse to the lowest
    `(cost, link_id)` tuple, so the chosen physical link is deterministic.
- `paths.py`
  - `shortest_path` returns a typed `RoutePath` (`device_ids`, `hops`,
    `total_cost`, `hop_count`, `reachable`, `reason`). Unreachable pairs return
    `reachable=False` instead of raising; unknown devices raise
    `DeviceNotFoundError`, unknown failure ids raise `LinkNotFoundError` /
    `DeviceNotFoundError`.
  - Equal-cost paths break ties by the lexicographically smallest device-id
    sequence. Source = destination is reachable with an empty path, cost 0,
    and 0 hops.
  - `alternative_paths` enumerates simple paths (Yen) over distinct device
    sequences, ordered by total cost then device sequence, bounded by
    `MAX_ALTERNATIVE_PATHS`.
  - `routing_table` returns one deterministic next-hop entry per reachable
    destination, excluding the source.
  - `reachability_matrix` returns a directed boolean matrix with per-ordered-
    pair counts; `component_summary` reports weak/strong components and
    isolated devices.
- `tables.py` exposes UI-agnostic `path_rows`, `alternative_rows`,
  `routing_table_rows`, and `reachability_rows`.
- `config/limits.py` adds `MAX_ALTERNATIVE_PATHS = 10`; `MAX_NODES` bounds the
  graph size and the documented complexity (Dijkstra per source).

## Phase 5b delivered - structural analysis engine
Location: `network/analysis/` (pure Python plus NetworkX, no Streamlit, no LLM,
no new dependencies). All metrics are design-time structural indicators, not
measurements of traffic, latency, utilization, or availability.

- Analysis basis (documented in `graph.py`): a simple undirected projection
  where a link contributes one edge regardless of `directed`, and parallel
  links collapse into one edge that keeps all link ids and the lowest cost.
- `metrics.py`
  - Degree centrality (parallel links count once) and betweenness centrality
    (weighted by `Link.cost`).
  - Connected components and isolated devices; hop-based diameter reported per
    component with `overall_diameter=None` when disconnected.
  - Articulation points and bridges, each with the component count and any
    newly isolated devices after removal. A pair joined by parallel links is
    never reported as a single-link failure.
  - `METRIC_DEFINITIONS` exports the exact wording used by the UI.
- `spof.py`: `SpofReport` combining critical devices and critical links with
  the baseline component count.
- `findings.py`: `Finding` results with stable codes `spof_device` and
  `spof_link` (critical), plus `topology_disconnected` and `isolated_device`
  warnings.
- `redundancy.py`: node-disjoint paths on the direction-aware routing graph;
  edge-disjoint paths via a unit-capacity physical-link gadget so parallel
  links count separately and an undirected link carries at most one path.
- `report.py`: `analyze_topology` computes the full `AnalysisReport` in one
  pass; `tables.py` provides UI-agnostic rows.

## Phase 5c delivered - routing and analytics pages
- `ui/pages/routing_analysis.py`:
  - Source/destination selectors, k-alternative slider, failure selector for
    devices and links, shortest path with cost and hop count, ranked
    alternatives, routing table, and a directed reachability matrix.
  - With failures active, the page shows before/after reachability and a
    next-hop/cost comparison with `unchanged` / `rerouted` / `new` /
    `unreachable` status.
  - Plotly topology view highlights the current path, keeps the baseline path
    dashed when it changes, and marks failed entities in red.
  - Every table has a CSV download; the page derives results on each rerun and
    stores no engine output in session state beyond widget keys.
- `ui/pages/network_analytics.py`:
  - Summary metrics, degree and weighted-betweenness bar charts with tables,
    connected components, per-component diameters, critical devices/links,
    SPOF summary and findings, and per-pair path redundancy.
  - An expandable "Metric definitions" section renders `METRIC_DEFINITIONS`
    verbatim and states that values are structural, not measured.
  - CSV downloads for every table.
- `app.py` wires `Routing Analysis` and `Network Analytics` into navigation and
  updates the sidebar/dashboard availability text; no other placeholder page
  is changed.

## Test evidence (Phase 5)
- Unit tests:
  - `tests/unit/routing/` (50 tests): hand-computed weighted triangle (a-b-c
    costs 3 vs direct 4), equal-cost diamond tie-break (`a-b-d` before
    `a-c-d`), line, ring, star, disconnected, and directed-asymmetry cases;
    failure cases; generated star/ring/campus/spine-leaf topologies; every
    returned path re-walked against the graph so cost equals the summed link
    costs; limit enforcement.
  - `tests/unit/analysis/` (41 tests): hand-computed degree/betweenness on a
    line, cost-weighted betweenness on the triangle, component and diameter
    behaviour including disconnected topologies, articulation points,
    bridges, parallel-link handling, node-/edge-disjoint counts (including a
    directed asymmetry and parallel-link edge redundancy), SPOF findings, and
    the `MAX_NODES` bound.
  - `tests/unit/ui/test_analysis_pages.py` (4 tests): AppTest smoke tests for
    both pages, including the empty state and a failure scenario on the
    routing page.
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `377 passed in 3.54s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- Public domain schemas were not changed in Phase 5.
- Headless app verification (port 8554, `--server.address 127.0.0.1`,
  `--server.enableAgentApi true`):
  - `/_stcore/health`: HTTP 200 (`ok`); root page: HTTP 200.
  - Generated a star in the Topology Editor (Devices 7, Links 6, Components 1,
    Isolated devices 0), then opened Routing Analysis: Cost 1.00, Hops 1,
    Baseline cost 1.00, Status reachable, with path table, alternatives,
    routing table, reachability matrix, downloads, and a Plotly chart.
  - Failed `star-hub` with destination `star-spoke-01`: Cost `unreachable`,
    Hops `-`, Baseline cost 1.00, Status `unreachable`, no app exception.
  - Network Analytics: Devices 7, Links 6, Components 1, Diameter (hops) 2,
    SPOF entities 7, Node-disjoint paths 1, Edge-disjoint paths 1; centrality
    bar charts, tables, findings, and downloads rendered without exception.

## Test evidence (Phase 4)
- Unit tests: `tests/unit/addressing/` (39 tests) and `tests/unit/vlan/`
  (36 tests) cover known-answer CIDR cases (`/24`, `/26`, `/30`, `/31`,
  `/32`, class-A splits, IPv6 `/64`, `/127`, `/128`), the classic
  192.168.1.0/24 VLSM example with hand-computed prefixes and host ranges,
  insufficient space, reserved-address edges, duplicate names/IPs, overlap,
  utilization, DHCP pool boundary violations, and the property that allocated
  subnets never overlap and stay inside the parent.
- UI smoke tests: `tests/unit/ui/test_planning_pages.py` uses AppTest to
  navigate to both pages, run CIDR/VLSM/overlap checks, build a VLAN and DHCP
  plan, and confirm a malformed parent surfaces an error without writing state.
- Full suite and lint results are recorded below.

## Test evidence (Phase 4c)
- Commands:
  - `& ".venv\Scripts\python.exe" -m pytest -q`
  - `& ".venv\Scripts\python.exe" -m ruff check .`
- Results:
  - `282 passed in 2.39s`
  - `All checks passed!`
- Headless app verification (port 8552, `--server.address 127.0.0.1`,
  `--server.enableAgentApi true`):
  - `/_stcore/health`: HTTP 200 (`ok`); root page: HTTP 200.
  - Agent API: navigated to both Phase 4 pages and drove them with no app
    exceptions. IP page metrics included prefix `/24`, 256 total addresses,
    254 usable hosts; VLSM produced 5 subnets, 248 addresses allocated, 8
    remaining; the overlap checker reported 1 finding. VLAN page reported
    `Planned 5 VLANs and 5 DHCP scopes`, 305 pool addresses, and no overlap or
    DHCP violations.
  - Visual appearance was not inspected in a browser; see Known issues.

## Test evidence (Phase 3b)
- Commands:
  - `& ".venv\Scripts\python.exe" -m pytest -q`
  - `& ".venv\Scripts\python.exe" -m ruff check .`
- Results:
  - `204 passed in 1.83s` (188 from Phase 3a + 16 new)
  - `All checks passed!`
- Headless app verification (port 8552, `--server.enableAgentApi true`):
  - `/_stcore/health`: HTTP 200; root page: HTTP 200.
  - Agent API: navigated to Topology Editor and generated a star with 0
    exceptions; metrics `Devices 7`, `Links 6`, `Components 1`,
    `Isolated devices 0`.
  - Server log contained no warnings beyond PowerShell's stderr formatting of
    Streamlit's startup line.

## Test evidence (Phase 3a)
- Commands:
  - `& ".venv\Scripts\python.exe" -m pytest tests/ -q`
  - `& ".venv\Scripts\python.exe" -m ruff check .`
- Results:
  - `188 passed in 1.28s` (114 existing + 74 new topology tests)
  - `All checks passed!`
- Known failures: none.

## Known issues
- Environment uses Python 3.11.15; the blueprint targets Python 3.12. All
  checks pass on 3.11.15. Non-blocking; revisit if a 3.12-only feature is
  required.
- `MAX_EDGES=2000` bounds a full mesh at 63 nodes (2016 links would exceed
  the limit); oversized mesh requests fail cleanly by design. A full
  spine-leaf mesh is bounded similarly (for example 50 spines x 41 leaves).
- Name collisions are only detected for ids; generator-supplied custom
  prefixes/hub ids that collide with generated ids fail through `Topology`
  validation, not a generator-specific error.
- Visual appearance of the editor (colors, legend placement, Plotly rendering
  in a browser) was not inspected manually. Verified only through AppTest, the
  Streamlit agent API, and HTTP status checks; no browser screenshot was
  taken.
- The table editors use a form plus an Apply button. Because `st.data_editor`
  keeps its own widget state, a rejected edit remains visible in the table
  until the user corrects or reloads it; the model itself is never changed.
- Phase 4 pages were verified through AppTest, the Streamlit agent API, and
  HTTP status checks only. Colors, spacing, progress-bar rendering, table
  sizing, and CSV download behaviour were not inspected in a real browser; no
  screenshots were taken.
- The VLSM allocator deliberately never produces point-to-point prefixes
  (`/31`, `/32`, `/127`, `/128`); use the CIDR calculator or DHCP planner for
  those. This avoids allocating a block with no assignable host address.
- The VLAN/DHCP page's "Reserved addresses per subnet" input accepts values
  below the engine minimum (IPv4 needs at least 2); such a submission is
  rejected by the engine with an inline error rather than clamped silently.
- DHCP planning requires at least one assignable address after reserved
  addresses, so `/32` (IPv4) and `/128` (IPv6) subnets raise a clear error
  instead of producing an empty scope.
- Phase 5 routing and analytics pages were verified through AppTest, the
  Streamlit agent API, and HTTP status checks only. A real-browser pass
  (Plotly path highlighting, horizontal bar-chart rendering, table sizing,
  CSV download behaviour) was not performed; no screenshots were taken.
- Structural analysis ignores link direction and collapses parallel links by
  design. Directed reachability questions belong to the routing page; the
  analytics page intentionally reports physical connectivity.
- Edge-disjoint path counts model each physical link as one capacity unit, so
  they indicate path-count redundancy, not available bandwidth or failure
  independence beyond single-link removal.
- Betweenness centrality uses `Link.cost`, while degree and diameter are
  hop-based. The definitions expander states this, but mixed-weight topologies
  can make centrality rankings differ from hop-count intuition.

## Next task
- Phase 6: Network Digital Twin. Not started.
