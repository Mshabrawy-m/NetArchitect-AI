# Changelog

All notable changes to NetArchitect AI are recorded here. Dates are ISO-8601.

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
