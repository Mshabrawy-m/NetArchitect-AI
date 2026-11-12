"""Public API of the digital-twin model.

Import from ``digital_twin`` rather than from the individual modules.

The digital twin is a software model of a design: topology, addressing, VLAN
plan, DHCP scopes, traffic demands, and modeled operational state. It is not a
live copy of real equipment. Operations are immutable-style and snapshots are
frozen deep copies.
"""

from .adapters import (
    FailureSelection,
    analysis_arguments,
    failed_entities,
    routing_arguments,
    validate_engine_twin,
)
from .models import (
    TWIN_SCHEMA_VERSION,
    DeviceState,
    DigitalTwin,
    LinkState,
    OperationalState,
    TwinMetadata,
    effective_device_state,
    effective_link_state,
)
from .operations import (
    add_assumption,
    add_demand,
    apply_failure,
    remove_demand,
    restore_entities,
    set_addressing_plan,
    set_assumptions,
    set_demands,
    set_device_state,
    set_dhcp_scopes,
    set_link_capacity,
    set_link_cost,
    set_link_state,
    set_operational_states,
    set_topology,
    set_vlan_plan,
)
from .serialization import from_json, json_size_bytes, to_json
from .snapshots import (
    CapacityChange,
    CostChange,
    DemandChange,
    Snapshot,
    SnapshotStore,
    StateChange,
    TwinDiff,
    create_snapshot,
    diff_twins,
)
from .validation import addressing_subnets, validate_twin

__all__ = [
    "TWIN_SCHEMA_VERSION",
    "CapacityChange",
    "CostChange",
    "DemandChange",
    "DeviceState",
    "DigitalTwin",
    "FailureSelection",
    "LinkState",
    "OperationalState",
    "Snapshot",
    "SnapshotStore",
    "StateChange",
    "TwinDiff",
    "TwinMetadata",
    "add_assumption",
    "add_demand",
    "addressing_subnets",
    "analysis_arguments",
    "apply_failure",
    "create_snapshot",
    "diff_twins",
    "effective_device_state",
    "effective_link_state",
    "failed_entities",
    "from_json",
    "json_size_bytes",
    "remove_demand",
    "restore_entities",
    "routing_arguments",
    "set_addressing_plan",
    "set_assumptions",
    "set_demands",
    "set_device_state",
    "set_dhcp_scopes",
    "set_link_capacity",
    "set_link_cost",
    "set_link_state",
    "set_operational_states",
    "set_topology",
    "set_vlan_plan",
    "to_json",
    "validate_engine_twin",
    "validate_twin",
]
