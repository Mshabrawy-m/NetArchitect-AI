"""Single session-state accessor for the digital twin and derived UI results.

The baseline twin lives under exactly one session key (``TWIN_KEY``). Pages and
tests must not read or write that key directly; they use the functions here.

Legacy sessions that still hold a bare ``Topology`` in ``st.session_state[
"topology"]`` are migrated once, on first access, into a twin. The legacy key is
removed so the model never exists twice.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from capacity import CapacityHistory, CapacityRun
from config.limits import MAX_OPTIMIZATION_RUNS
from core.schemas.addressing import AddressingPlan, DhcpScope
from core.schemas.network import Topology
from core.schemas.routing import TrafficDemand
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
from network.vlan.plan import VlanPlanResult
from optimization import OptimizationHistory, OptimizationRun
from services.llm import RequestBudget
from simulation import ScenarioHistory, ScenarioRun

TWIN_KEY = "digital_twin"
SNAPSHOTS_KEY = "digital_twin_snapshots"
SIMULATION_HISTORY_KEY = "simulation_history"
OPTIMIZATION_HISTORY_KEY = "optimization_history"
# OptimizationRun has no persisted twin fingerprint. This bounded map records
# the source fingerprint at run creation, keyed by the run's canonical content.
OPTIMIZATION_SOURCE_FINGERPRINTS_KEY = "optimization_source_fingerprints"
CAPACITY_SERIES_KEY = "capacity_series"
CAPACITY_FORECAST_KEY = "capacity_forecast"
CAPACITY_HISTORY_KEY = "capacity_history"
LEGACY_TOPOLOGY_KEY = "topology"
FLASH_KEY = "topology_editor_flash"

LLM_SESSION_KEY = "llm_session_api_key"
LLM_BUDGET_KEY = "llm_request_budget"

CIDR_KEY = "ip_cidr_result"
VLSM_KEY = "addressing_result"
CHECK_KEY = "addressing_check_report"

REPORT_TIME_KEY = "report_generated_at"
REPORT_TIME_ENTRIES = 4

_UNSET = object()
_DEFAULT_TWIN_NAME = "Working design"


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
