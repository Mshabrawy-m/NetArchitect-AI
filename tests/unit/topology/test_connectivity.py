"""Tests for ``network.topology.connectivity``."""

from __future__ import annotations

from core.schemas.network import Topology
from network.topology.connectivity import analyze_connectivity

from .helpers import make_device, make_link


def test_empty_topology_is_not_connected() -> None:
    report = analyze_connectivity(Topology(name="empty"))

    assert report.is_connected is False
    assert report.node_count == 0
    assert report.component_count == 0
    assert report.components == ()
    assert report.isolated_device_ids == ()


def test_single_device_is_connected_but_isolated() -> None:
    topology = Topology(name="one", devices=[make_device("only")])

    report = analyze_connectivity(topology)

    assert report.is_connected is True
    assert report.component_count == 1
    assert report.components[0].device_ids == ("only",)
    assert report.isolated_device_ids == ("only",)


def test_fully_connected_star(star_topology: Topology) -> None:
    report = analyze_connectivity(star_topology)

    assert report.is_connected is True
    assert report.component_count == 1
    assert report.components[0].device_ids == ("a", "b", "hub")
    assert report.components[0].link_ids == ("l1", "l2")
    assert report.isolated_device_ids == ()
    assert report.node_count == 3
    assert report.link_count == 2


def test_multiple_components_and_isolated_devices() -> None:
    topology = Topology(
        name="split",
        devices=[
            make_device("a"),
            make_device("b"),
            make_device("c"),
            make_device("d"),
            make_device("e"),
        ],
        links=[
            make_link("ab", "a", "b"),
            make_link("cd", "c", "d"),
        ],
    )

    report = analyze_connectivity(topology)

    assert report.is_connected is False
    assert report.component_count == 3
    assert report.components[0].device_ids == ("a", "b")
    assert report.components[1].device_ids == ("c", "d")
    assert report.components[2].device_ids == ("e",)
    assert report.isolated_device_ids == ("e",)


def test_directed_links_count_for_physical_connectivity() -> None:
    topology = Topology(
        name="directed chain",
        devices=[make_device("a"), make_device("b"), make_device("c")],
        links=[
            make_link("ab", "a", "b", directed=True),
            make_link("bc", "b", "c", directed=True),
        ],
    )

    report = analyze_connectivity(topology)

    assert report.is_connected is True
    assert report.component_count == 1


def test_mixed_directedness_is_reported_connected(
    mixed_topology: Topology,
) -> None:
    report = analyze_connectivity(mixed_topology)

    assert report.is_connected is True
    assert report.isolated_device_ids == ()


def test_report_is_frozen(mixed_topology: Topology) -> None:
    report = analyze_connectivity(mixed_topology)

    try:
        report.is_connected = False  # type: ignore[misc]
    except ValueError:
        return
    raise AssertionError("ConnectivityReport should be immutable")
