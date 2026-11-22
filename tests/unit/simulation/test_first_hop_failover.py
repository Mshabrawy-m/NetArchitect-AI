"""L4 tests for additive, default-off modeled first-hop failover reporting."""

from __future__ import annotations

import json

from digital_twin import DeviceState, OperationalState
from digital_twin.serialization import to_json
from network.routing import HaGroup, HaMember
from simulation import SimulationAssumptions, evaluate, twin_fingerprint

from .helpers import make_demand, make_link, make_topology, make_twin


def _campus_twin(*, ha: bool = True) -> object:
    topology = make_topology(
        ["host", "r1", "r2", "server"],
        [
            make_link("host-r1", "host", "r1", cost=1.0),
            make_link("host-r2", "host", "r2", cost=2.0),
            make_link("r1-server", "r1", "server", cost=1.0),
            make_link("r2-server", "r2", "server", cost=2.0),
        ],
    )
    twin = make_twin(
        topology,
        (make_demand("users", "host", "server", 10.0),),
        device_states=(DeviceState(device_id="r1", state=OperationalState.down),),
    )
    if not ha:
        return twin
    group = HaGroup(
        id="users-gw",
        name="Users gateway",
        virtual_ip="10.0.1.1",
        subnet="10.0.1.0/24",
        vlan_id=10,
        members=(
            HaMember(device_id="r1", priority=150, vlan_ids=(10,)),
            HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
        ),
    )
    return twin.model_copy(update={"ha_groups": (group,)})


def test_default_evaluation_is_byte_identical_and_additive_fields_absent() -> None:
    twin = _campus_twin()
    legacy = _campus_twin(ha=False)
    state = evaluate(twin)

    assert state.first_hop_failovers == ()
    payload = state.model_dump_json()
    assert "first_hop_failovers" not in payload
    assert "enable_first_hop_failover" not in state.assumptions.model_dump_json()
    # All legacy fields are identical with and without the additive HA design.
    assert state.model_dump(exclude={"twin"}) == evaluate(legacy).model_dump(
        exclude={"twin"}
    )


def test_failed_active_rehomes_to_next_highest_priority_member() -> None:
    twin = _campus_twin()
    state = evaluate(twin, SimulationAssumptions(enable_first_hop_failover=True))

    assert len(state.first_hop_failovers) == 1
    failover = state.first_hop_failovers[0]
    # Hand: without failures, host->r1 (cost 1) ->server (cost 1) totals 2,
    # cheaper than host->r2 (2) ->server (2) totals 4, so r1 is first hop.
    assert failover.before_path_device_ids == ("host", "r1", "server")
    assert failover.before_link_ids == ("host-r1", "r1-server")
    # Hand: r1 is modeled down; r2 (priority 100) is the only live member.
    assert failover.after_path_device_ids == ("host", "r2", "server")
    assert failover.after_link_ids == ("host-r2", "r2-server")
    assert (failover.failed_active, failover.next_active) == ("r1", "r2")
    assert failover.group_id == "users-gw"
    assert failover.demand_name == "users"
    assert "not simulated packets" in failover.note.lower()
    # Additive view must not alter legacy demand path or link loads.
    assert state.demands[0].path_device_ids == ("host", "r2", "server")
    assert {"host-r2", "r2-server"} <= {link.link_id for link in state.links}


def test_no_groups_or_no_active_failure_means_no_report() -> None:
    legacy = _campus_twin(ha=False)
    enabled = SimulationAssumptions(enable_first_hop_failover=True)
    assert evaluate(legacy, enabled).first_hop_failovers == ()

    healthy = _campus_twin(ha=True)
    healthy = healthy.model_copy(update={"device_states": ()})
    assert evaluate(healthy, enabled).first_hop_failovers == ()


def test_equal_priority_successor_uses_lexicographic_tie_break() -> None:
    twin = _campus_twin()
    group = twin.ha_groups[0].model_copy(
        update={
            "members": (
                HaMember(device_id="r1", priority=100, vlan_ids=(10,)),
                HaMember(device_id="r2", priority=100, vlan_ids=(10,)),
            )
        }
    )
    tied = twin.model_copy(update={"ha_groups": (group,)})
    state = evaluate(tied, SimulationAssumptions(enable_first_hop_failover=True))
    # Hand: r1 is down; r2 is the lexicographically lowest live member at 100.
    assert [item.next_active for item in state.first_hop_failovers] == ["r2"]


def test_empty_ha_groups_are_omitted_from_legacy_twin_bytes() -> None:
    legacy = _campus_twin(ha=False)
    payload = to_json(legacy)
    assert "ha_groups" not in json.loads(payload)
    restored = evaluate(legacy)
    assert twin_fingerprint(legacy) == restored.twin.fingerprint
    assert restored.twin.fingerprint == evaluate(
        type(legacy).model_validate(json.loads(payload))
    ).twin.fingerprint
