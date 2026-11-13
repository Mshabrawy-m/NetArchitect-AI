"""Single session-state accessor for the digital twin and derived UI results.

The baseline twin lives under exactly one session key (``TWIN_KEY``). Pages and
tests must not read or write that key directly; they use the functions here.

Legacy sessions that still hold a bare ``Topology`` in ``st.session_state[
"topology"]`` are migrated once, on first access, into a twin. The legacy key is
removed so the model never exists twice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st

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
from network.vlan.plan import VlanPlanResult
from simulation import ScenarioHistory, ScenarioRun

TWIN_KEY = "digital_twin"
SNAPSHOTS_KEY = "digital_twin_snapshots"
SIMULATION_HISTORY_KEY = "simulation_history"
LEGACY_TOPOLOGY_KEY = "topology"
FLASH_KEY = "topology_editor_flash"

CIDR_KEY = "ip_cidr_result"
VLSM_KEY = "addressing_result"
CHECK_KEY = "addressing_check_report"

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


def create_twin_snapshot(label: str) -> Snapshot:
    """Capture the current baseline twin into the bounded snapshot store."""
    twin = get_twin()
    if twin is None:
        raise ValueError("No digital twin is loaded.")
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
