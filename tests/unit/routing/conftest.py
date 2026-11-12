"""Fixtures for the Phase 5 routing unit tests.

Every graph is small enough that the expected shortest path, cost, and hop
count are computed by hand and stated in the consuming test's comments.
"""

from __future__ import annotations

import pytest

from core.schemas.network import Topology

from .helpers import build_topology, make_link


@pytest.fixture
def weighted_triangle() -> Topology:
    """a-b cost 1, b-c cost 2, a-c cost 4 (all undirected).

    Cheapest a->c: a-b-c = 1 + 2 = 3, not the direct a-c = 4.
    """
    return build_topology(
        "Weighted triangle",
        ["a", "b", "c"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bc", "b", "c", cost=2.0),
            make_link("ac", "a", "c", cost=4.0),
        ],
    )


@pytest.fixture
def unequal_diamond() -> Topology:
    """a-b 1, a-c 2, b-d 1, c-d 2.

    a->d via b = 2; via c = 4. Failing b-d forces the 4-cost path.
    """
    return build_topology(
        "Unequal diamond",
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("ac", "a", "c", cost=2.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("cd", "c", "d", cost=2.0),
        ],
    )


@pytest.fixture
def equal_cost_diamond() -> Topology:
    """a-b 1, a-c 1, b-d 1, c-d 1.

    a->d has two equal-cost paths: a-b-d and a-c-d, both cost 2.
    The tie-break rule picks the lexicographically smallest sequence, a-b-d.
    """
    return build_topology(
        "Equal-cost diamond",
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("ac", "a", "c", cost=1.0),
            make_link("bd", "b", "d", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
        ],
    )


@pytest.fixture
def line_graph() -> Topology:
    """a-b-c-d, every link cost 1 (undirected)."""
    return build_topology(
        "Line",
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("bc", "b", "c", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
        ],
    )


@pytest.fixture
def ring_graph() -> Topology:
    """r1-r2-r3-r4-r1, every link cost 1 (undirected)."""
    return build_topology(
        "Ring",
        ["r1", "r2", "r3", "r4"],
        [
            make_link("l12", "r1", "r2", cost=1.0),
            make_link("l23", "r2", "r3", cost=1.0),
            make_link("l34", "r3", "r4", cost=1.0),
            make_link("l41", "r4", "r1", cost=1.0),
        ],
    )


@pytest.fixture
def star_graph() -> Topology:
    """Hub h joined to s1, s2, s3, every link cost 1 (undirected)."""
    return build_topology(
        "Star",
        ["h", "s1", "s2", "s3"],
        [
            make_link("hs1", "h", "s1", cost=1.0),
            make_link("hs2", "h", "s2", cost=1.0),
            make_link("hs3", "h", "s3", cost=1.0),
        ],
    )


@pytest.fixture
def disconnected_graph() -> Topology:
    """{a, b} and {c, d} are separate components."""
    return build_topology(
        "Disconnected",
        ["a", "b", "c", "d"],
        [
            make_link("ab", "a", "b", cost=1.0),
            make_link("cd", "c", "d", cost=1.0),
        ],
    )


@pytest.fixture
def directed_chain() -> Topology:
    """r1 -> r2 -> r3 only; the reverse direction has no links."""
    return build_topology(
        "Directed chain",
        ["r1", "r2", "r3"],
        [
            make_link("d12", "r1", "r2", cost=1.0, directed=True),
            make_link("d23", "r2", "r3", cost=1.0, directed=True),
        ],
    )
