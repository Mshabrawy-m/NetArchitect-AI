"""Bounded route-walk and failure invariants."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from network.routing import shortest_path
from tests.property.config import BOUNDED
from tests.unit.routing.helpers import build_topology, make_link


@st.composite
def _scenarios(draw):
    devices = draw(
        st.lists(st.sampled_from("abcdef"), min_size=2, max_size=6, unique=True)
    )
    raw_links = draw(
        st.lists(
            st.tuples(
                st.integers(0, len(devices) - 1),
                st.integers(0, len(devices) - 1),
                st.integers(1, 5),
                st.booleans(),
            ),
            max_size=8,
        )
    )
    links = [
        make_link(
            f"l{index}",
            devices[first],
            devices[second],
            cost=float(cost),
            directed=directed,
        )
        for index, (first, second, cost, directed) in enumerate(raw_links)
        if first != second
    ]
    topology = build_topology("property topology", list(devices), links)
    failed_devices = draw(
        st.lists(st.sampled_from(devices), max_size=len(devices))
    )
    failed_links = (
        draw(st.lists(st.sampled_from([link.id for link in links]), max_size=len(links)))
        if links
        else []
    )
    source = draw(st.sampled_from(devices))
    destination = draw(st.sampled_from(devices))
    return topology, source, destination, failed_devices, failed_links


@BOUNDED
@given(scenario=_scenarios())
def test_shortest_paths_are_valid_walks_that_respect_failures(scenario) -> None:
    topology, source, destination, failed_devices, failed_links = scenario
    path = shortest_path(
        topology,
        source,
        destination,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    repeat = shortest_path(
        topology,
        source,
        destination,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    assert path.model_dump() == repeat.model_dump()
    assert path.source == source
    assert path.destination == destination

    if not path.reachable:
        assert path.device_ids == []
        assert path.hops == []
        assert path.total_cost == 0.0
        assert path.hop_count == 0
        assert path.reason
        return

    failed_device_set = set(failed_devices)
    failed_link_set = set(failed_links)
    links = {link.id: link for link in topology.links}

    assert all(device not in failed_device_set for device in path.device_ids)
    assert path.hop_count == len(path.hops)
    assert path.total_cost == sum(hop.cost for hop in path.hops)

    if source == destination:
        assert path.device_ids == [source]
        assert path.hops == []
        return

    assert path.device_ids[0] == source
    assert path.device_ids[-1] == destination
    assert len(path.device_ids) == path.hop_count + 1
    for start, end, hop in zip(path.device_ids, path.device_ids[1:], path.hops):
        assert (hop.source, hop.target) == (start, end)
        assert hop.link_id not in failed_link_set
        link = links[hop.link_id]
        assert hop.cost == float(link.cost)
        if link.directed:
            assert (start, end) == link.endpoints
        else:
            assert {start, end} == set(link.endpoints)
