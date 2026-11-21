"""Single session-state accessor for the digital twin and derived UI results.

The baseline twin lives under exactly one session key (``TWIN_KEY``). Pages and
tests must not read or write that key directly; they use the functions here.
Modeled security flow checks are likewise kept behind bounded accessors.

Bounded derived results (failure sweeps, routing-mode comparisons, sensitivity
reports, and Pareto rerankings) use typed tuple accessors so session memory
stays small on the free tier.

Legacy sessions that still hold a bare ``Topology`` in ``st.session_state[
"topology"]`` are migrated once, on first access, into a twin. The legacy key is
removed so the model never exists twice.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

import streamlit as st

from capacity import CapacityHistory, CapacityRun
from config.limits import (
    MAX_OPTIMIZATION_RUNS,
    MAX_SCENARIOS,
    MAX_SECURITY_FLOW_CHECKS,
)
from core.schemas.addressing import AddressingPlan, DhcpScope
from core.schemas.network import Topology
from core.schemas.routing import TrafficDemand
from core.schemas.validation import ValidationReport
from digital_twin import (
    DigitalTwin,
    Snapshot,
    SnapshotStore,
    TwinMetadata,
    create_snapshot,
    set_addressing_plan,
    set_topology,
)
from digital_twin import (
    set_demands as twin_set_demands,
)
from digital_twin import (
    set_dhcp_scopes as twin_set_dhcp_scopes,
)
from digital_twin import (
    set_operational_states as twin_set_operational_states,
)
from digital_twin import (
    set_vlan_plan as twin_set_vlan_plan,
)
from forecasting import ForecastRun, TimeSeries
from network.addressing import VlsmResult
from network.vlan.plan import VlanPlanResult
from optimization import (
    OptimizationHistory,
    OptimizationRun,
    ParetoReranking,
    SensitivityReport,
)
from security import FlowRequest
from services.llm import RequestBudget

if TYPE_CHECKING:  # pragma: no cover - typing only; copilot import stays lazy
    from services.copilot import (
        CopilotCache,
        DecisionKind,
        DecisionLog,
        DecisionRecord,
        PromptTrace,
    )
from simulation import (
    FailureSweepResult,
    RoutingModeComparison,
    ScenarioHistory,
    ScenarioRun,
)

TWIN_KEY = "digital_twin"
SNAPSHOTS_KEY = "digital_twin_snapshots"
SIMULATION_HISTORY_KEY = "simulation_history"
OPTIMIZATION_HISTORY_KEY = "optimization_history"
# OptimizationRun has no persisted twin fingerprint. This bounded map records
# the source fingerprint at run creation, keyed by the run's canonical content.
OPTIMIZATION_SOURCE_FINGERPRINTS_KEY = "optimization_source_fingerprints"

# Bounded derived results from the simulation and optimization engines.
SIMULATION_SWEEPS_KEY = "simulation_failure_sweeps"
SIMULATION_MODE_COMPARISONS_KEY = "simulation_mode_comparisons"
SIMULATION_SWEEP_CURSOR_KEY = "simulation_sweep_cursor"
OPTIMIZATION_SENSITIVITY_KEY = "optimization_sensitivity_reports"
OPTIMIZATION_RERANKINGS_KEY = "optimization_rerankings"
OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY = "optimization_rerank_source_fingerprints"
SIMULATION_SWEEP_ENTRIES = MAX_SCENARIOS
SIMULATION_MODE_COMPARISON_ENTRIES = 4
OPTIMIZATION_SENSITIVITY_ENTRIES = MAX_OPTIMIZATION_RUNS
OPTIMIZATION_RERANKING_ENTRIES = MAX_OPTIMIZATION_RUNS

CAPACITY_SERIES_KEY = "capacity_series"
CAPACITY_FORECAST_KEY = "capacity_forecast"
CAPACITY_HISTORY_KEY = "capacity_history"
SECURITY_FLOWS_KEY = "security_flow_requests"
LEGACY_TOPOLOGY_KEY = "topology"
FLASH_KEY = "topology_editor_flash"

LLM_SESSION_KEY = "llm_session_api_key"
LLM_BUDGET_KEY = "llm_request_budget"
COPILOT_CACHE_KEY = "copilot_response_cache"
COPILOT_TRACE_KEY = "copilot_prompt_trace"
COPILOT_DECISIONS_KEY = "copilot_decisions"

CIDR_KEY = "ip_cidr_result"
VLSM_KEY = "addressing_result"
CHECK_KEY = "addressing_check_report"

# The subnet check result is a plain ValidationReport, so the UI keeps a bounded
# map from report content to the twin fingerprint it was checked against.
CHECK_FINGERPRINT_KEY = "addressing_check_source_fingerprints"
CHECK_FINGERPRINT_ENTRIES = 4

REPORT_TIME_KEY = "report_generated_at"
REPORT_TIME_ENTRIES = 4

_UNSET = object()
_DEFAULT_TWIN_NAME = "Working design"
_T = TypeVar("_T")


def session_get(key: str, default: Any = None) -> Any:
    """Return one session value (pages never touch ``st.session_state``)."""
    return st.session_state.get(key, default)


def session_set(key: str, value: Any) -> None:
    """Set one session value (pages never touch ``st.session_state``)."""
    st.session_state[key] = value


def session_pop(key: str, default: Any = None) -> Any:
    """Pop one session value (pages never touch ``st.session_state``)."""
    return st.session_state.pop(key, default)


def session_has(key: str) -> bool:
    """Return whether a session key exists."""
    return key in st.session_state


def session_delete(key: str) -> None:
    """Delete a session key if it exists."""
    st.session_state.pop(key, None)


def _bounded_tuple_values(
    key: str,
    item_type: type[_T],
    limit: int,
    *,
    create: bool = False,
) -> tuple[_T, ...]:
    """Return typed, capped values without mutating any stored model."""
    value = st.session_state.get(key, _UNSET)
    if isinstance(value, (tuple, list)):
        typed = tuple(item for item in value if isinstance(item, item_type))
        stored = typed[-limit:] if limit > 0 else ()
    else:
        stored = ()
    if create and (not isinstance(value, tuple) or stored != value):
        st.session_state[key] = stored
    return stored


def _bounded_tuple_peek(
    key: str,
    item_type: type[_T],
    limit: int,
) -> tuple[_T, ...]:
    """Read a bounded derived-result tuple without creating an empty key."""
    return _bounded_tuple_values(key, item_type, limit)


def _bounded_tuple_get(
    key: str,
    item_type: type[_T],
    limit: int,
) -> tuple[_T, ...]:
    """Return a bounded derived-result tuple, creating an empty store if needed."""
    return _bounded_tuple_values(key, item_type, limit, create=True)


def _bounded_tuple_add(
    key: str,
    item: _T,
    item_type: type[_T],
    limit: int,
) -> _T:
    """Append one typed item last, trimming the oldest items past the cap."""
    if not isinstance(item, item_type):
        raise TypeError(f"{key} accepts only {item_type.__name__} values.")
    values = _bounded_tuple_values(key, item_type, limit)
    st.session_state[key] = (*values, item)[-limit:] if limit > 0 else ()
    return item


def _bounded_tuple_clear(key: str) -> None:
    """Remove one bounded derived-result store."""
    session_delete(key)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_twin(topology: Topology | None = None) -> DigitalTwin:
    topology = topology or Topology(name="No topology loaded")
    return DigitalTwin(
        metadata=TwinMetadata(name=topology.name, created_at=_now()),
        topology=topology,
    )


def get_twin() -> DigitalTwin | None:
    """Return the baseline twin, migrating a legacy topology once if needed."""
    twin = st.session_state.get(TWIN_KEY)
    if isinstance(twin, DigitalTwin):
        session_delete(LEGACY_TOPOLOGY_KEY)
        return twin

    legacy = st.session_state.get(LEGACY_TOPOLOGY_KEY)
    if isinstance(legacy, Topology):
        migrated = _new_twin(legacy)
        st.session_state[TWIN_KEY] = migrated
        session_delete(LEGACY_TOPOLOGY_KEY)
        return migrated
    return None


def peek_twin() -> DigitalTwin | None:
    """Return the baseline twin without migrating or creating session state."""
    twin = st.session_state.get(TWIN_KEY)
    return twin if isinstance(twin, DigitalTwin) else None


def replace_twin(twin: DigitalTwin) -> DigitalTwin:
    """Store and return a replacement baseline twin."""
    st.session_state[TWIN_KEY] = twin
    session_delete(LEGACY_TOPOLOGY_KEY)
    return twin


def get_topology() -> Topology | None:
    """Return the baseline topology from the twin, if a twin exists."""
    twin = get_twin()
    return twin.topology if twin is not None else None


def replace_topology(topology: Topology) -> DigitalTwin:
    """Replace the twin topology while preserving dependent parts.

    Addressing, VLAN, DHCP, demand, and state data are kept. The Digital Twin
    page and Topology Editor report stale references instead of pruning them.
    """
    twin = get_twin()
    updated = _new_twin(topology) if twin is None else set_topology(twin, topology)
    return replace_twin(updated)


def get_addressing() -> AddressingPlan | None:
    """Return the twin addressing plan, if present."""
    twin = get_twin()
    return twin.addressing if twin is not None else None


def set_addressing(addressing: AddressingPlan | None) -> DigitalTwin:
    """Replace the twin addressing plan, creating a twin when needed."""
    twin = get_twin() or _new_twin()
    return replace_twin(set_addressing_plan(twin, addressing))


def get_vlan_plan() -> VlanPlanResult | None:
    """Return the department-to-VLAN plan, if present."""
    twin = get_twin()
    return twin.vlan_plan if twin is not None else None


def set_vlan_plan(vlan_plan: VlanPlanResult | None) -> DigitalTwin:
    """Replace the department-to-VLAN plan, creating a twin when needed."""
    twin = get_twin() or _new_twin()
    return replace_twin(twin_set_vlan_plan(twin, vlan_plan))


def get_dhcp_scopes() -> tuple[DhcpScope, ...]:
    """Return the twin DHCP scopes (empty when no twin exists)."""
    twin = get_twin()
    return twin.dhcp_scopes if twin is not None else ()


def set_dhcp_scopes(scopes: tuple[DhcpScope, ...]) -> DigitalTwin:
    """Replace the twin DHCP scopes, creating a twin when needed."""
    twin = get_twin() or _new_twin()
    return replace_twin(twin_set_dhcp_scopes(twin, scopes))


def get_demands() -> tuple[TrafficDemand, ...]:
    """Return the twin traffic demands (empty when no twin exists)."""
    twin = get_twin()
    return twin.demands if twin is not None else ()


def set_demands(demands: tuple[TrafficDemand, ...]) -> DigitalTwin:
    """Replace the twin traffic demands, creating a twin when needed."""
    twin = get_twin() or _new_twin()
    return replace_twin(twin_set_demands(twin, demands))


def set_operational_states(
    *,
    down_devices: tuple[str, ...] = (),
    down_links: tuple[str, ...] = (),
) -> DigitalTwin:
    """Replace modeled failures on the baseline twin."""
    twin = get_twin()
    if twin is None:
        raise ValueError("No digital twin is loaded.")
    updated = twin_set_operational_states(
        twin,
        down_devices=down_devices,
        down_links=down_links,
    )
    return replace_twin(updated)


def set_planning(
    *,
    addressing: AddressingPlan | None | object = _UNSET,
    vlan_plan: VlanPlanResult | None | object = _UNSET,
    dhcp_scopes: tuple[DhcpScope, ...] | object = _UNSET,
) -> DigitalTwin:
    """Update any combination of addressing, VLAN plan, and DHCP scopes."""
    twin = get_twin() or _new_twin()
    if addressing is not _UNSET:
        twin = set_addressing_plan(twin, addressing)  # type: ignore[arg-type]
    if vlan_plan is not _UNSET:
        twin = twin_set_vlan_plan(twin, vlan_plan)  # type: ignore[arg-type]
    if dhcp_scopes is not _UNSET:
        twin = twin_set_dhcp_scopes(twin, dhcp_scopes)  # type: ignore[arg-type]
    return replace_twin(twin)


def peek_addressing_result() -> VlsmResult | None:
    """Return the last VLSM result without creating an empty session key."""
    value = st.session_state.get(VLSM_KEY)
    return value if isinstance(value, VlsmResult) else None


def peek_vlsm_result() -> VlsmResult | None:
    """Alias for :func:`peek_addressing_result`."""
    return peek_addressing_result()


def peek_addressing_check() -> ValidationReport | None:
    """Return the last subnet check report without creating a session key."""
    value = st.session_state.get(CHECK_KEY)
    return value if isinstance(value, ValidationReport) else None


def _check_report_key(report: ValidationReport) -> str:
    return hashlib.sha256(report.model_dump_json().encode("utf-8")).hexdigest()


def set_addressing_check_source_fingerprint(
    report: ValidationReport,
    fingerprint: str,
) -> str:
    """Remember which twin revision produced one subnet check report."""
    mapping = st.session_state.get(CHECK_FINGERPRINT_KEY)
    if not isinstance(mapping, dict):
        mapping = {}
    mapping[_check_report_key(report)] = fingerprint
    while len(mapping) > CHECK_FINGERPRINT_ENTRIES:
        del mapping[next(iter(mapping))]
    st.session_state[CHECK_FINGERPRINT_KEY] = mapping
    return fingerprint


def peek_addressing_check_fingerprint(report: ValidationReport) -> str:
    """Return the recorded source fingerprint, or an empty string if unknown."""
    mapping = st.session_state.get(CHECK_FINGERPRINT_KEY)
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(_check_report_key(report), "")
    return value if isinstance(value, str) else ""


def get_snapshot_store() -> SnapshotStore:
    """Return the session snapshot store, creating it when needed."""
    store = st.session_state.get(SNAPSHOTS_KEY)
    if not isinstance(store, SnapshotStore):
        store = SnapshotStore()
        st.session_state[SNAPSHOTS_KEY] = store
    return store


def get_snapshots() -> tuple[Snapshot, ...]:
    """Return retained snapshots in creation order."""
    return get_snapshot_store().snapshots


def peek_snapshots() -> tuple[Snapshot, ...]:
    """Return retained snapshots without creating an empty store."""
    store = st.session_state.get(SNAPSHOTS_KEY)
    return store.snapshots if isinstance(store, SnapshotStore) else ()


def create_twin_snapshot(label: str) -> Snapshot:
    """Capture the current baseline twin into the bounded snapshot store."""
    twin = get_twin()
    if twin is None:
        raise ValueError("No digital twin is loaded.")
    snapshot = create_snapshot(twin, label)
    get_snapshot_store().add(snapshot)
    return snapshot


def save_twin_snapshot(twin: DigitalTwin, label: str) -> Snapshot:
    """Capture ``twin`` into the bounded snapshot store without replacing it.

    Optimization results use this to save a derived design as a snapshot while
    leaving the baseline twin untouched.
    """
    snapshot = create_snapshot(twin, label)
    get_snapshot_store().add(snapshot)
    return snapshot


def delete_snapshot(index: int) -> Snapshot:
    """Remove one retained snapshot by index."""
    return get_snapshot_store().remove(index)


def clear_snapshots() -> None:
    """Remove every retained snapshot."""
    get_snapshot_store().clear()


def get_simulation_history() -> ScenarioHistory:
    """Return the session scenario history, creating it when needed."""
    history = st.session_state.get(SIMULATION_HISTORY_KEY)
    if not isinstance(history, ScenarioHistory):
        history = ScenarioHistory()
        st.session_state[SIMULATION_HISTORY_KEY] = history
    return history


def get_simulation_runs() -> tuple[ScenarioRun, ...]:
    """Return retained scenario runs in creation order."""
    return get_simulation_history().runs


def peek_simulation_runs() -> tuple[ScenarioRun, ...]:
    """Return retained scenario runs without creating an empty history."""
    history = st.session_state.get(SIMULATION_HISTORY_KEY)
    return history.runs if isinstance(history, ScenarioHistory) else ()


def add_simulation_run(run: ScenarioRun) -> ScenarioRun:
    """Append a scenario run to the bounded session history."""
    get_simulation_history().add(run)
    return run


def remove_simulation_run(index: int) -> ScenarioRun:
    """Remove one retained scenario run by index."""
    return get_simulation_history().remove(index)


def clear_simulation_history() -> None:
    """Remove every retained scenario run."""
    get_simulation_history().clear()


def add_simulation_sweep(result: FailureSweepResult) -> FailureSweepResult:
    """Append one failure sweep result to the bounded session store."""
    return _bounded_tuple_add(
        SIMULATION_SWEEPS_KEY,
        result,
        FailureSweepResult,
        SIMULATION_SWEEP_ENTRIES,
    )


def peek_simulation_sweeps() -> tuple[FailureSweepResult, ...]:
    """Return stored failure sweeps without creating an empty session key."""
    return _bounded_tuple_peek(
        SIMULATION_SWEEPS_KEY,
        FailureSweepResult,
        SIMULATION_SWEEP_ENTRIES,
    )


def get_simulation_sweeps() -> tuple[FailureSweepResult, ...]:
    """Return stored failure sweeps, creating an empty store when needed."""
    return _bounded_tuple_get(
        SIMULATION_SWEEPS_KEY,
        FailureSweepResult,
        SIMULATION_SWEEP_ENTRIES,
    )


def clear_simulation_sweeps() -> None:
    """Remove every stored failure sweep result."""
    _bounded_tuple_clear(SIMULATION_SWEEPS_KEY)


def add_mode_comparison(result: RoutingModeComparison) -> RoutingModeComparison:
    """Append one routing-mode comparison to the bounded session store."""
    return _bounded_tuple_add(
        SIMULATION_MODE_COMPARISONS_KEY,
        result,
        RoutingModeComparison,
        SIMULATION_MODE_COMPARISON_ENTRIES,
    )


def peek_mode_comparisons() -> tuple[RoutingModeComparison, ...]:
    """Return stored mode comparisons without creating an empty session key."""
    return _bounded_tuple_peek(
        SIMULATION_MODE_COMPARISONS_KEY,
        RoutingModeComparison,
        SIMULATION_MODE_COMPARISON_ENTRIES,
    )


def get_mode_comparisons() -> tuple[RoutingModeComparison, ...]:
    """Return stored mode comparisons, creating an empty store when needed."""
    return _bounded_tuple_get(
        SIMULATION_MODE_COMPARISONS_KEY,
        RoutingModeComparison,
        SIMULATION_MODE_COMPARISON_ENTRIES,
    )


def clear_mode_comparisons() -> None:
    """Remove every stored routing-mode comparison."""
    _bounded_tuple_clear(SIMULATION_MODE_COMPARISONS_KEY)


def set_sweep_cursor(key: str, value: int) -> int:
    """Store one non-negative sweep cursor, keeping the most recent keys only."""
    if not isinstance(key, str):
        raise TypeError("A sweep cursor key must be a string.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("A sweep cursor value must be an integer.")
    if value < 0:
        raise ValueError("A sweep cursor value must be non-negative.")
    cursor = st.session_state.get(SIMULATION_SWEEP_CURSOR_KEY)
    cleaned = (
        {
            name: position
            for name, position in cursor.items()
            if isinstance(name, str)
            and isinstance(position, int)
            and not isinstance(position, bool)
            and position >= 0
        }
        if isinstance(cursor, dict)
        else {}
    )
    cleaned[key] = value
    while len(cleaned) > SIMULATION_SWEEP_ENTRIES:
        del cleaned[next(iter(cleaned))]
    st.session_state[SIMULATION_SWEEP_CURSOR_KEY] = cleaned
    return value


def get_sweep_cursor(key: str, default: int = 0) -> int:
    """Return one stored sweep cursor, or ``default`` when it is unknown."""
    if not isinstance(key, str):
        raise TypeError("A sweep cursor key must be a string.")
    if isinstance(default, bool) or not isinstance(default, int) or default < 0:
        raise ValueError("The default sweep cursor must be a non-negative integer.")
    cursor = st.session_state.get(SIMULATION_SWEEP_CURSOR_KEY)
    if not isinstance(cursor, dict):
        return default
    value = cursor.get(key, default)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def clear_sweep_cursor() -> None:
    """Remove every stored sweep cursor."""
    session_delete(SIMULATION_SWEEP_CURSOR_KEY)


def get_optimization_history() -> OptimizationHistory:
    """Return the session optimization history, creating it when needed."""
    history = st.session_state.get(OPTIMIZATION_HISTORY_KEY)
    if not isinstance(history, OptimizationHistory):
        history = OptimizationHistory()
        st.session_state[OPTIMIZATION_HISTORY_KEY] = history
    return history


def get_optimization_runs() -> tuple[OptimizationRun, ...]:
    """Return retained optimization runs in creation order."""
    return get_optimization_history().runs


def peek_optimization_runs() -> tuple[OptimizationRun, ...]:
    """Return retained optimization runs without creating an empty history."""
    history = st.session_state.get(OPTIMIZATION_HISTORY_KEY)
    return history.runs if isinstance(history, OptimizationHistory) else ()


def _optimization_run_key(run: OptimizationRun) -> str:
    """Return a stable content key for one optimization run."""
    return hashlib.sha256(run.model_dump_json().encode("utf-8")).hexdigest()


def set_optimization_source_fingerprint(run: OptimizationRun, fingerprint: str) -> str:
    """Remember which twin revision produced one optimization run."""
    mapping = st.session_state.get(OPTIMIZATION_SOURCE_FINGERPRINTS_KEY)
    if not isinstance(mapping, dict):
        mapping = {}
    mapping[_optimization_run_key(run)] = fingerprint
    while len(mapping) > MAX_OPTIMIZATION_RUNS:
        del mapping[next(iter(mapping))]
    st.session_state[OPTIMIZATION_SOURCE_FINGERPRINTS_KEY] = mapping
    return fingerprint


def get_optimization_source_fingerprint(run: OptimizationRun) -> str:
    """Return the recorded source fingerprint, or an empty string if unknown."""
    mapping = st.session_state.get(OPTIMIZATION_SOURCE_FINGERPRINTS_KEY)
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(_optimization_run_key(run), "")
    return value if isinstance(value, str) else ""


def peek_optimization_source_fingerprint(run: OptimizationRun) -> str:
    """Read-only alias used by progress reporting; creates no session state."""
    return get_optimization_source_fingerprint(run)


def add_optimization_run(
    run: OptimizationRun,
    source_fingerprint: str = "",
) -> OptimizationRun:
    """Append an optimization run and record its source twin fingerprint."""
    get_optimization_history().add(run)
    if source_fingerprint:
        set_optimization_source_fingerprint(run, source_fingerprint)
    return run


def remove_optimization_run(index: int) -> OptimizationRun:
    """Remove one retained optimization run by index."""
    runs = get_optimization_runs()
    if 0 <= index < len(runs):
        mapping = st.session_state.get(OPTIMIZATION_SOURCE_FINGERPRINTS_KEY)
        if isinstance(mapping, dict):
            mapping.pop(_optimization_run_key(runs[index]), None)
    return get_optimization_history().remove(index)


def clear_optimization_history() -> None:
    """Remove every retained optimization run and source fingerprint."""
    st.session_state.pop(OPTIMIZATION_SOURCE_FINGERPRINTS_KEY, None)
    get_optimization_history().clear()


def add_sensitivity_report(report: SensitivityReport) -> SensitivityReport:
    """Append one sensitivity report to the bounded session store."""
    return _bounded_tuple_add(
        OPTIMIZATION_SENSITIVITY_KEY,
        report,
        SensitivityReport,
        OPTIMIZATION_SENSITIVITY_ENTRIES,
    )


def peek_sensitivity_reports() -> tuple[SensitivityReport, ...]:
    """Return stored sensitivity reports without creating an empty session key."""
    return _bounded_tuple_peek(
        OPTIMIZATION_SENSITIVITY_KEY,
        SensitivityReport,
        OPTIMIZATION_SENSITIVITY_ENTRIES,
    )


def get_sensitivity_reports() -> tuple[SensitivityReport, ...]:
    """Return stored sensitivity reports, creating an empty store when needed."""
    return _bounded_tuple_get(
        OPTIMIZATION_SENSITIVITY_KEY,
        SensitivityReport,
        OPTIMIZATION_SENSITIVITY_ENTRIES,
    )


def clear_sensitivity_reports() -> None:
    """Remove every stored sensitivity report."""
    _bounded_tuple_clear(OPTIMIZATION_SENSITIVITY_KEY)


def add_reranking(reranking: ParetoReranking) -> ParetoReranking:
    """Append one Pareto reranking to the bounded session store."""
    return _bounded_tuple_add(
        OPTIMIZATION_RERANKINGS_KEY,
        reranking,
        ParetoReranking,
        OPTIMIZATION_RERANKING_ENTRIES,
    )


def peek_rerankings() -> tuple[ParetoReranking, ...]:
    """Return stored rerankings without creating an empty session key."""
    return _bounded_tuple_peek(
        OPTIMIZATION_RERANKINGS_KEY,
        ParetoReranking,
        OPTIMIZATION_RERANKING_ENTRIES,
    )


def get_rerankings() -> tuple[ParetoReranking, ...]:
    """Return stored rerankings, creating an empty store when needed."""
    return _bounded_tuple_get(
        OPTIMIZATION_RERANKINGS_KEY,
        ParetoReranking,
        OPTIMIZATION_RERANKING_ENTRIES,
    )


def _rerank_key(reranking: ParetoReranking) -> str:
    """Return a stable content key for one Pareto reranking."""
    return hashlib.sha256(reranking.model_dump_json().encode("utf-8")).hexdigest()


def set_rerank_source_fingerprint(reranking: ParetoReranking, fingerprint: str) -> str:
    """Remember which source run produced one Pareto reranking."""
    if not isinstance(reranking, ParetoReranking):
        raise TypeError("A reranking must be a ParetoReranking.")
    if not isinstance(fingerprint, str):
        raise TypeError("A source fingerprint must be a string.")
    mapping = st.session_state.get(OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY)
    cleaned = (
        {
            key: value
            for key, value in mapping.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if isinstance(mapping, dict)
        else {}
    )
    cleaned[_rerank_key(reranking)] = fingerprint
    while len(cleaned) > OPTIMIZATION_RERANKING_ENTRIES:
        del cleaned[next(iter(cleaned))]
    st.session_state[OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY] = cleaned
    return fingerprint


def get_rerank_source_fingerprint(reranking: ParetoReranking) -> str:
    """Return the recorded source fingerprint, or an empty string if unknown."""
    if not isinstance(reranking, ParetoReranking):
        raise TypeError("A reranking must be a ParetoReranking.")
    mapping = st.session_state.get(OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY)
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(_rerank_key(reranking), "")
    return value if isinstance(value, str) else ""


def peek_rerank_source_fingerprint(reranking: ParetoReranking) -> str:
    """Read-only alias used by progress reporting; creates no session state."""
    return get_rerank_source_fingerprint(reranking)


def clear_rerankings() -> None:
    """Remove every stored reranking and its source fingerprint map."""
    session_delete(OPTIMIZATION_RERANK_SOURCE_FINGERPRINTS_KEY)
    _bounded_tuple_clear(OPTIMIZATION_RERANKINGS_KEY)


def get_capacity_series() -> tuple[TimeSeries, ...]:
    """Return the current capacity-planning input series."""
    value = st.session_state.get(CAPACITY_SERIES_KEY)
    return value if isinstance(value, tuple) else ()


def peek_capacity_series() -> tuple[TimeSeries, ...]:
    """Return capacity input series without creating an empty session key."""
    return get_capacity_series()


def set_capacity_series(series: tuple[TimeSeries, ...]) -> tuple[TimeSeries, ...]:
    """Replace the bounded set of capacity-planning input series."""
    st.session_state[CAPACITY_SERIES_KEY] = tuple(series)
    return get_capacity_series()


def get_capacity_forecast() -> ForecastRun | None:
    """Return the last generated forecast run, if any."""
    value = st.session_state.get(CAPACITY_FORECAST_KEY)
    return value if isinstance(value, ForecastRun) else None


def peek_capacity_forecast() -> ForecastRun | None:
    """Return the last forecast run without creating an empty session key."""
    return get_capacity_forecast()


def set_capacity_forecast(run: ForecastRun) -> ForecastRun:
    """Store one completed forecast run for the Capacity tab."""
    st.session_state[CAPACITY_FORECAST_KEY] = run
    return run


def get_capacity_history() -> CapacityHistory:
    """Return the session capacity history, creating it when needed."""
    history = st.session_state.get(CAPACITY_HISTORY_KEY)
    if not isinstance(history, CapacityHistory):
        history = CapacityHistory()
        st.session_state[CAPACITY_HISTORY_KEY] = history
    return history


def get_capacity_runs() -> tuple[CapacityRun, ...]:
    """Return retained capacity runs in creation order."""
    return get_capacity_history().runs


def peek_capacity_runs() -> tuple[CapacityRun, ...]:
    """Return retained capacity runs without creating an empty history."""
    history = st.session_state.get(CAPACITY_HISTORY_KEY)
    return history.runs if isinstance(history, CapacityHistory) else ()


def add_capacity_run(run: CapacityRun) -> CapacityRun:
    """Append a capacity run to the bounded session history."""
    get_capacity_history().add(run)
    return run


def remove_capacity_run(index: int) -> CapacityRun:
    """Remove one retained capacity run by index."""
    return get_capacity_history().remove(index)


def clear_capacity_history() -> None:
    """Remove every retained capacity run."""
    get_capacity_history().clear()


def get_security_flows() -> tuple[FlowRequest, ...]:
    """Return bounded, typed modeled flow checks without creating a session key."""
    value = session_get(SECURITY_FLOWS_KEY, ())
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(
        item for item in value if isinstance(item, FlowRequest)
    )[:MAX_SECURITY_FLOW_CHECKS]


def peek_security_flows() -> tuple[FlowRequest, ...]:
    """Return modeled flow checks without creating an empty session key."""
    return get_security_flows()


def set_security_flows(flows: tuple[FlowRequest, ...] | list[FlowRequest]) -> tuple[FlowRequest, ...]:
    """Replace the bounded set of modeled flow checks."""
    cleaned = tuple(
        item for item in flows if isinstance(item, FlowRequest)
    )[:MAX_SECURITY_FLOW_CHECKS]
    session_set(SECURITY_FLOWS_KEY, cleaned)
    return cleaned


def add_security_flow(flow: FlowRequest) -> tuple[FlowRequest, ...]:
    """Add or replace one flow check, enforcing the session bound."""
    if not isinstance(flow, FlowRequest):
        raise TypeError("A security flow check must be a FlowRequest.")
    existing = [item for item in get_security_flows() if item.id != flow.id]
    if len(existing) + 1 > MAX_SECURITY_FLOW_CHECKS:
        raise ValueError(
            f"The security session limit is {MAX_SECURITY_FLOW_CHECKS} flow checks."
        )
    updated = (*existing, flow)
    session_set(SECURITY_FLOWS_KEY, updated)
    return updated


def remove_security_flow(index: int) -> FlowRequest:
    """Remove one flow check by its displayed index."""
    flows = get_security_flows()
    if not isinstance(index, int) or not 0 <= index < len(flows):
        raise IndexError("No flow check is selected for removal.")
    removed = flows[index]
    session_set(SECURITY_FLOWS_KEY, flows[:index] + flows[index + 1 :])
    return removed


def clear_security_flows() -> None:
    """Remove every modeled flow check from this session."""
    session_delete(SECURITY_FLOWS_KEY)


def peek_report_times() -> dict[str, datetime]:
    """Return a copy of the prepared report timestamps, creating no session key."""
    timestamps = st.session_state.get(REPORT_TIME_KEY)
    if not isinstance(timestamps, dict):
        return {}
    return {
        key: value
        for key, value in timestamps.items()
        if isinstance(key, str) and isinstance(value, datetime)
    }


def report_generated_at(fingerprint: str) -> datetime:
    """Return a stable report timestamp for one twin fingerprint.

    The same twin revision keeps the timestamp it was first prepared with, so
    rebuilding the report on a later rerun does not change its contents. A new
    twin revision gets a new timestamp. Only the most recent fingerprints are
    remembered to keep session state bounded.
    """
    timestamps = st.session_state.get(REPORT_TIME_KEY)
    if not isinstance(timestamps, dict):
        timestamps = {}
    value = timestamps.get(fingerprint)
    if isinstance(value, datetime):
        return value
    moment = _now()
    timestamps[fingerprint] = moment
    while len(timestamps) > REPORT_TIME_ENTRIES:
        del timestamps[next(iter(timestamps))]
    st.session_state[REPORT_TIME_KEY] = timestamps
    return moment


def get_llm_session_key() -> str:
    """Return the session-only API key, or an empty string.

    The key is held in Streamlit session state for this browser tab only. It is
    never written to disk, logs, traces, URLs, or any rendered output.
    """
    value = st.session_state.get(LLM_SESSION_KEY, "")
    return value.strip() if isinstance(value, str) else ""


def set_llm_session_key(value: str) -> None:
    """Set the session-only API key (trimmed); an empty value clears it."""
    key = value.strip()
    if key:
        st.session_state[LLM_SESSION_KEY] = key
    else:
        session_delete(LLM_SESSION_KEY)


def clear_llm_session_key() -> None:
    """Remove the session-only API key."""
    session_delete(LLM_SESSION_KEY)


def get_llm_budget() -> RequestBudget:
    """Return the session LLM request budget, creating it when needed."""
    budget = st.session_state.get(LLM_BUDGET_KEY)
    if not isinstance(budget, RequestBudget):
        budget = RequestBudget()
        st.session_state[LLM_BUDGET_KEY] = budget
    return budget


def reset_llm_budget() -> RequestBudget:
    """Clear the session LLM counters and return the same budget object."""
    budget = get_llm_budget()
    budget.reset()
    return budget


def get_copilot_cache() -> CopilotCache:
    """Return the session copilot cache, creating it when needed."""
    from services.copilot import CopilotCache

    cache = st.session_state.get(COPILOT_CACHE_KEY)
    if not isinstance(cache, CopilotCache):
        cache = CopilotCache()
        st.session_state[COPILOT_CACHE_KEY] = cache
    return cache


def reset_copilot_cache() -> CopilotCache:
    """Clear cached copilot responses without changing the LLM budget."""
    cache = get_copilot_cache()
    cache.clear()
    return cache


def get_copilot_trace() -> PromptTrace:
    """Return the session prompt trace, creating it when needed."""
    from services.copilot import PromptTrace

    trace = st.session_state.get(COPILOT_TRACE_KEY)
    if not isinstance(trace, PromptTrace):
        trace = PromptTrace()
        st.session_state[COPILOT_TRACE_KEY] = trace
    return trace


def peek_copilot_trace() -> PromptTrace:
    """Return a prompt trace view without creating a session key."""
    from services.copilot import PromptTrace

    trace = st.session_state.get(COPILOT_TRACE_KEY)
    return trace if isinstance(trace, PromptTrace) else PromptTrace()


def get_copilot_decisions() -> DecisionLog:
    """Return the session decision log, creating it when needed."""
    from services.copilot import DecisionLog

    log = st.session_state.get(COPILOT_DECISIONS_KEY)
    if not isinstance(log, DecisionLog):
        log = DecisionLog()
        st.session_state[COPILOT_DECISIONS_KEY] = log
    return log


def peek_copilot_decisions() -> DecisionLog:
    """Return a decision-log view without creating a session key."""
    from services.copilot import DecisionLog

    log = st.session_state.get(COPILOT_DECISIONS_KEY)
    return log if isinstance(log, DecisionLog) else DecisionLog()


def record_decision(
    *,
    kind: DecisionKind | str,
    subject_id: str,
    title: str,
    page: str,
    source_fingerprint: str = "",
    result_fingerprint: str = "",
    details: tuple[tuple[str, str], ...] = (),
) -> DecisionRecord:
    """Append one explicitly confirmed decision with an injected timestamp."""
    from services.copilot import DecisionKind

    return get_copilot_decisions().add(
        kind=DecisionKind(kind),
        subject_id=subject_id,
        title=title,
        page=page,
        source_fingerprint=source_fingerprint,
        result_fingerprint=result_fingerprint,
        details=details,
    )


def clear_copilot_decisions() -> None:
    """Remove the session decision log."""
    session_delete(COPILOT_DECISIONS_KEY)
