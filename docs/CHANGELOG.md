# Changelog

All notable changes to NetArchitect AI are recorded here. Dates are ISO-8601.

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
