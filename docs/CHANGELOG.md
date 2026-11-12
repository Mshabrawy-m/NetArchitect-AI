# Changelog

All notable changes to NetArchitect AI are recorded here. Dates are ISO-8601.

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
