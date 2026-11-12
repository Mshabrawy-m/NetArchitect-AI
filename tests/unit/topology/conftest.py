"""Shared topology fixtures for the Phase 3 unit tests."""

from __future__ import annotations

import pytest

from core.schemas.network import DeviceRole, DeviceType, Topology

from .helpers import make_device, make_link


@pytest.fixture
def mixed_topology() -> Topology:
    """Three devices joined by one undirected and one directed link.

    The undirected link's endpoints are deliberately in reverse alphabetical
    order to prove that exact endpoint order survives a graph round-trip.
    """
    return Topology(
        name="Mixed test topology",
        devices=[
            make_device("r1"),
            make_device("r2", DeviceType.switch, DeviceRole.distribution),
            make_device("h1", DeviceType.host, DeviceRole.access),
        ],
        links=[
            make_link("l-undirected", "r2", "r1", cost=2.5),
            make_link("l-directed", "r1", "h1", directed=True),
        ],
    )


@pytest.fixture
def star_topology() -> Topology:
    """A connected three-device star."""
    return Topology(
        name="Star test topology",
        devices=[make_device("hub"), make_device("a"), make_device("b")],
        links=[
            make_link("l1", "hub", "a"),
            make_link("l2", "hub", "b"),
        ],
    )
