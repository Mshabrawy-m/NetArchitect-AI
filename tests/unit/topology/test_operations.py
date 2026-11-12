"""Tests for pure editing operations in ``network.topology.operations``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.exceptions import (
    DeviceNotFoundError,
    DuplicateIdError,
    LimitsExceededError,
    LinkNotFoundError,
    MissingEndpointError,
)
from core.schemas.network import DeviceRole, DeviceType, Topology
from network.topology.operations import (
    add_device,
    add_link,
    enforce_limits,
    remove_device,
    remove_link,
    update_device,
    update_link,
)

from .helpers import make_device, make_link


def _topology() -> Topology:
    return Topology(
        name="ops",
        devices=[make_device("r1"), make_device("r2")],
        links=[make_link("l1", "r1", "r2")],
    )


def test_add_device_returns_new_object_and_keeps_original() -> None:
    topology = _topology()
    updated = add_device(topology, make_device("r3"))

    assert updated is not topology
    assert [device.id for device in updated.devices] == ["r1", "r2", "r3"]
    assert [device.id for device in topology.devices] == ["r1", "r2"]


def test_add_device_rejects_duplicate_id() -> None:
    with pytest.raises(DuplicateIdError, match="Device id 'r1' already exists"):
        add_device(_topology(), make_device("r1"))


def test_add_link_returns_new_object_and_keeps_original() -> None:
    topology = _topology()
    updated = add_link(topology, make_link("l2", "r2", "r1", cost=9.0))

    assert updated is not topology
    assert [link.id for link in updated.links] == ["l1", "l2"]
    assert [link.id for link in topology.links] == ["l1"]


def test_add_link_rejects_duplicate_id() -> None:
    with pytest.raises(DuplicateIdError, match="Link id 'l1' already exists"):
        add_link(_topology(), make_link("l1", "r1", "r2"))


def test_add_link_rejects_missing_first_endpoint() -> None:
    with pytest.raises(MissingEndpointError, match="'ghost'"):
        add_link(_topology(), make_link("l2", "ghost", "r1"))


def test_add_link_rejects_missing_second_endpoint() -> None:
    with pytest.raises(MissingEndpointError, match="'ghost'"):
        add_link(_topology(), make_link("l2", "r1", "ghost"))


def test_remove_device_cascades_attached_links() -> None:
    updated = remove_device(_topology(), "r2")

    assert [device.id for device in updated.devices] == ["r1"]
    assert updated.links == []


def test_remove_device_rejects_unknown_id() -> None:
    with pytest.raises(DeviceNotFoundError, match="'ghost' does not exist"):
        remove_device(_topology(), "ghost")


def test_remove_link_keeps_devices() -> None:
    updated = remove_link(_topology(), "l1")

    assert updated.links == []
    assert [device.id for device in updated.devices] == ["r1", "r2"]


def test_remove_link_rejects_unknown_id() -> None:
    with pytest.raises(LinkNotFoundError, match="'ghost' does not exist"):
        remove_link(_topology(), "ghost")


def test_update_device_changes_only_provided_fields() -> None:
    updated = update_device(
        _topology(),
        "r1",
        role=DeviceRole.edge,
        site="site-2",
    )

    device = updated.devices[0]
    assert device.role is DeviceRole.edge
    assert device.site == "site-2"
    assert device.type is DeviceType.router


def test_update_device_rejects_unknown_id() -> None:
    with pytest.raises(DeviceNotFoundError):
        update_device(_topology(), "ghost", role=DeviceRole.edge)


def test_update_link_changes_only_provided_fields() -> None:
    updated = update_link(_topology(), "l1", capacity_mbps=2500.0, directed=True)

    link = updated.links[0]
    assert link.capacity_mbps == 2500.0
    assert link.directed is True
    assert link.cost == 1.0
    assert link.endpoints == ("r1", "r2")


def test_update_link_rejects_unknown_id() -> None:
    with pytest.raises(LinkNotFoundError):
        update_link(_topology(), "ghost", cost=2.0)


def test_update_link_rejects_new_missing_endpoint() -> None:
    with pytest.raises(MissingEndpointError):
        update_link(_topology(), "l1", endpoints=("r1", "ghost"))


def test_update_link_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValidationError):
        update_link(_topology(), "l1", capacity_mbps=0.0)


def test_enforce_limits_allows_topology_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("network.topology.operations.MAX_NODES", 2)
    monkeypatch.setattr("network.topology.operations.MAX_EDGES", 1)
    assert enforce_limits(_topology()) == _topology()


def test_enforce_limits_rejects_too_many_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("network.topology.operations.MAX_NODES", 1)
    with pytest.raises(LimitsExceededError, match="2 devices; the limit is 1"):
        enforce_limits(_topology())


def test_enforce_limits_rejects_too_many_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("network.topology.operations.MAX_EDGES", 0)
    with pytest.raises(LimitsExceededError, match="1 links; the limit is 0"):
        enforce_limits(_topology())


def test_add_device_rejects_at_node_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("network.topology.operations.MAX_NODES", 2)
    with pytest.raises(LimitsExceededError, match="Cannot add device 'r3'"):
        add_device(_topology(), make_device("r3"))


def test_add_link_rejects_at_edge_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("network.topology.operations.MAX_EDGES", 1)
    with pytest.raises(LimitsExceededError, match="Cannot add link 'l2'"):
        add_link(_topology(), make_link("l2", "r1", "r2"))


def test_operations_do_not_mutate_nested_objects() -> None:
    topology = _topology()
    original_links = list(topology.links)

    update_device(topology, "r1", site="site-9")
    remove_device(topology, "r1")

    assert topology.links == original_links
    assert topology.devices[0].site == "site-1"


def test_revalidated_result_keeps_referential_integrity() -> None:
    topology = _topology()
    updated = remove_device(topology, "r1")

    assert all(
        endpoint in {device.id for device in updated.devices}
        for link in updated.links
        for endpoint in link.endpoints
    )
