"""Phase 15a acceptance invariants and gap-closing tests."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from itertools import pairwise, product
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from agents import run_structured_design
from agents.planning import build_ip_plan
from agents.requirements_agent import RequirementsExtraction
from app import PAGES
from config import settings as settings_module
from core.exceptions import LLMSchemaError
from core.schemas.scenario import ScenarioType
from network.addressing import (
    AddressAssignment,
    detect_duplicate_ips,
    detect_overlaps,
)
from network.routing import (
    alternative_paths,
    build_routing_graph,
    routing_table,
    shortest_path,
)
from network.topology import (
    generate_hierarchical_campus,
    generate_ring,
    generate_spine_leaf,
    generate_star,
)
from optimization import (
    Algorithm,
    HardConstraints,
    run_optimization,
)
from security import analyze_design
from services.llm.structured import validate_structured
from services.reporting import ReportSources, build_report, check_consistency
from simulation import run_scenario
from tests.unit.agents.helpers import sample_requirements
from tests.unit.optimization.helpers import (
    settings as optimization_settings,
)
from tests.unit.optimization.helpers import (
    tiny_twin,
)
from tests.unit.security.design_helpers import hardened_design
from tests.unit.simulation.helpers import (
    diamond_twin,
    line_twin,
    make_demand,
    make_scenario,
)
from tests.unit.ui.nav_helpers import open_page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"
GENERATED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _value(document, key: str):
    return next(record for record in document.values if record.key == key)


def _rendered_text(at: AppTest) -> str:
    parts: list[str] = []
    for kind in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "info",
        "warning",
        "error",
        "success",
    ):
        parts.extend(str(item.value) for item in at.get(kind))
    for metric in at.get("metric"):
        parts.append(f"{metric.label} {metric.value}")
    return "\n".join(parts)


def _assert_graph_walk(topology, path) -> None:
    graph = build_routing_graph(topology)
    assert path.device_ids[0] == path.source
    assert path.device_ids[-1] == path.destination
    assert len(set(path.device_ids)) == len(path.device_ids)
    assert [(hop.source, hop.target) for hop in path.hops] == list(
        pairwise(path.device_ids)
    )
    for hop in path.hops:
        edge = graph[hop.source][hop.target]
        assert edge["link_id"] == hop.link_id
        assert float(edge["cost"]) == pytest.approx(hop.cost)
    assert sum(hop.cost for hop in path.hops) == pytest.approx(path.total_cost)
    assert len(path.hops) == path.hop_count


@pytest.mark.smoke
@pytest.mark.parametrize(
    "base_network",
    ("10.0.0.0/16", "172.16.0.0/16", "192.168.0.0/16"),
)
def test_generated_ip_plans_have_no_overlaps_or_duplicate_gateways(
    base_network: str,
) -> None:
    plan = build_ip_plan(sample_requirements(), base_network=base_network)

    assert plan.subnets
    assert plan.addressing is not None
    assert detect_overlaps(plan.subnets) == []
    gateways = [
        AddressAssignment(
            entity=f"gateway:{subnet.name}",
            address=subnet.network.network_address + 1,
        )
        for subnet in plan.subnets
    ]
    assert detect_duplicate_ips(gateways) == []
    assert len({subnet.vlan_id for subnet in plan.subnets}) == len(plan.subnets)


@pytest.mark.smoke
def test_every_returned_route_is_a_valid_graph_walk() -> None:
    topologies = (
        generate_star(spoke_count=4),
        generate_ring(node_count=5),
        generate_spine_leaf(spines=2, leaves=4),
        generate_hierarchical_campus(
            distribution_count=2,
            access_per_distribution=3,
        ),
    )
    checked = 0
    for topology in topologies:
        graph = build_routing_graph(topology)
        device_ids = sorted(device.id for device in topology.devices)
        for source, destination in product(device_ids, repeat=2):
            shortest = shortest_path(topology, source, destination)
            assert shortest.reachable is True
            _assert_graph_walk(topology, shortest)

            alternatives = alternative_paths(
                topology, source, destination, k=3
            )
            assert alternatives.paths
            for path in alternatives.paths:
                _assert_graph_walk(topology, path)
            checked += 1

            table = routing_table(topology, source)
            for entry in table.entries:
                edge = graph[source][entry.next_hop]
                assert edge["link_id"] == entry.link_id
                assert float(edge["cost"]) <= entry.total_cost
    assert checked >= 40


@pytest.mark.smoke
def test_failed_devices_and_links_never_appear_in_post_failure_routes() -> None:
    topology = generate_spine_leaf(spines=2, leaves=3)
    device_ids = sorted(device.id for device in topology.devices)
    link_ids = sorted(link.id for link in topology.links)

    for failed_link in link_ids:
        for source, destination in product(device_ids, repeat=2):
            if source == destination:
                continue
            path = shortest_path(
                topology, source, destination, failed_links=[failed_link]
            )
            assert failed_link not in [hop.link_id for hop in path.hops]
            alternatives = alternative_paths(
                topology,
                source,
                destination,
                k=3,
                failed_links=[failed_link],
            )
            assert all(
                failed_link not in [hop.link_id for hop in item.hops]
                for item in alternatives.paths
            )
            table = routing_table(topology, source, failed_links=[failed_link])
            assert all(entry.link_id != failed_link for entry in table.entries)

    for failed_device in device_ids:
        for source, destination in product(device_ids, repeat=2):
            if failed_device in {source, destination}:
                continue
            path = shortest_path(
                topology, source, destination, failed_devices=[failed_device]
            )
            assert failed_device not in path.device_ids
            alternatives = alternative_paths(
                topology,
                source,
                destination,
                k=3,
                failed_devices=[failed_device],
            )
            assert all(
                failed_device not in item.device_ids
                for item in alternatives.paths
            )
            table = routing_table(
                topology, source, failed_devices=[failed_device]
            )
            assert all(
                entry.next_hop != failed_device for entry in table.entries
            )


def test_simulation_post_failure_paths_exclude_failed_elements() -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    for link in twin.topology.links:
        run = run_scenario(
            twin,
            make_scenario(
                ScenarioType.single_link_failure,
                affected_links=[link.id],
            ),
        )
        assert all(link.id not in demand.link_ids for demand in run.scenario_state.demands)
    for device_id in ("b", "c"):
        run = run_scenario(
            twin,
            make_scenario(
                ScenarioType.node_failure,
                affected_nodes=[device_id],
            ),
        )
        assert all(
            device_id not in demand.path_device_ids
            for demand in run.scenario_state.demands
        )


@pytest.mark.smoke
def test_simulation_is_reproducible_and_uses_no_random_sources(monkeypatch) -> None:
    twin = diamond_twin(demands=(make_demand("a-to-d", "a", "d", 10.0),))
    scenario = make_scenario(
        ScenarioType.increased_traffic_demand,
        parameters={"factor": 1.5},
    )
    first = run_scenario(twin, scenario)
    second = run_scenario(twin, scenario)
    assert first.model_dump() == second.model_dump()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("simulation must not use a random source")

    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(random, "randint", forbidden)
    monkeypatch.setattr(np.random, "default_rng", forbidden)
    assert run_scenario(twin, scenario).model_dump() == first.model_dump()


@pytest.mark.parametrize("algorithm", list(Algorithm))
@pytest.mark.smoke
def test_optimization_dispatch_is_reproducible_for_a_fixed_seed(
    algorithm: Algorithm,
) -> None:
    config = optimization_settings(max_iterations=4, max_evaluations=200)
    first = run_optimization(tiny_twin(), config, algorithm)
    second = run_optimization(tiny_twin(), config, algorithm)
    assert first.model_dump() == second.model_dump()
    assert first.seed == config.seed


@pytest.mark.parametrize("algorithm", list(Algorithm))
def test_optimization_dispatch_never_recommends_an_infeasible_candidate(
    algorithm: Algorithm,
) -> None:
    config = optimization_settings(
        pool=(),
        constraints=HardConstraints(
            require_connectivity=True,
            min_served_demand_ratio=1.0,
        ),
        max_iterations=4,
    )
    run = run_optimization(tiny_twin(), config, algorithm)
    assert run.best is None
    assert run.candidates
    assert all(not item.evaluation.feasible for item in run.candidates)
    assert run.pareto_front == ()


@pytest.mark.smoke
def test_invalid_llm_output_cannot_bypass_the_output_schema() -> None:
    payload = json.dumps(
        {
            "organization_name": "Acme",
            "departments": [
                {"name": "Engineering", "user_count": -1},
            ],
            "total_user_count": "thirty-seven",
            "design_goals": "resilience",
        }
    )
    response = f"Here is the result:\n```json\n{payload}\n```"
    with pytest.raises(LLMSchemaError):
        validate_structured(response, RequirementsExtraction)


def test_report_values_match_the_computed_engines() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 80.0),))
    scenario_run = run_scenario(
        twin,
        make_scenario(ScenarioType.single_link_failure, affected_links=["ab"]),
    )
    document = build_report(
        ReportSources(
            twin=twin,
            scenario_run=scenario_run,
            generated_at=GENERATED_AT,
        )
    )

    assert _value(document, "architecture.device_count").numeric == len(
        twin.topology.devices
    )
    assert _value(document, "topology.total_capacity_mbps").numeric == sum(
        link.capacity_mbps for link in twin.topology.links
    )
    assert _value(document, "simulation.baseline_served").numeric == (
        scenario_run.baseline_state.served_demand_count
    )
    assert _value(document, "simulation.scenario_served").numeric == (
        scenario_run.scenario_state.served_demand_count
    )
    consistency = check_consistency(document)
    assert consistency.ok, consistency.findings
    assert consistency.checked_numbers > 0


@pytest.mark.smoke
def test_structured_design_and_all_pages_work_with_no_api_key(monkeypatch) -> None:
    for key in settings_module._SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_module, "_read_streamlit_secrets", dict)
    settings_module.get_settings.cache_clear()
    try:
        assert settings_module.get_settings().GROQ_API_KEY == ""
        workflow = run_structured_design(sample_requirements())
        assert workflow.stop_reason.value == "completed"

        for page in PAGES:
            at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
            assert not at.exception
            open_page(at, page)
            assert not at.exception
            assert at.title[0].value == page
            text = _rendered_text(at)
            if page == "AI Network Designer":
                assert "No API key is configured" in text
            if page == "Settings":
                assert "API key configured No" in text
                assert "not configured" in text
    finally:
        settings_module.get_settings.cache_clear()


def test_asset_criticality_is_documented_as_a_gate_not_a_numeric_factor() -> None:
    twin, model = hardened_design()
    low = model.model_copy(
        update={
            "zones": tuple(
                zone.model_copy(update={"criticality": 1})
                for zone in model.zones
            )
        }
    )
    medium = model.model_copy(
        update={
            "zones": tuple(
                zone.model_copy(update={"criticality": 3})
                for zone in model.zones
            )
        }
    )

    low_analysis = analyze_design(twin, model=low)
    medium_analysis = analyze_design(twin, model=medium)

    assert low_analysis.risk.model_dump() == medium_analysis.risk.model_dump()
    assert "criticality" not in low_analysis.risk.formula.lower()
    assert not any(
        "criticality" in term.label.lower() for term in low_analysis.risk.terms
    )
