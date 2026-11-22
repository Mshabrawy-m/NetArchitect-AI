"""Independent Critic Agent tests (Phase 10b).

Every test runs without a network or a real provider. The critic is given a
digital twin directly so each deterministic check can be exercised in isolation.
The scripted :class:`FakeProvider` proves that model text never changes the
verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agents import (
    AgentContext,
    Clock,
    CriticAgent,
    CriticInput,
    CriticVerdict,
    DemandPlan,
    ExecutionTrace,
    IpPlanResult,
    IpVlanOutput,
    Orchestrator,
    WorkflowPlan,
    WorkflowState,
    WorkflowStopReason,
    WorkflowTask,
    registry_with_defaults,
    responsible_step_for,
)
from agents.network_agents import default_agents
from core.exceptions import LLMProviderError
from core.schemas.addressing import Subnet
from core.schemas.network import Device, DeviceRole, DeviceType, Link, Topology
from core.schemas.requirements import NetworkRequirements, UserFacts
from digital_twin import DigitalTwin
from network.addressing.nat import NatPlan, NatRule, NatType
from network.l2.models import LinkL2Mode
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.routing.ospf import OspfArea, OspfDesign
from network.wan.models import WanLinkType
from services.llm.testing import FakeProvider
from tests.unit.agents.helpers import sample_requirements
from tests.unit.simulation.helpers import (
    diamond_twin,
    line_twin,
    make_demand,
    make_topology,
    make_twin,
)


def disconnected_twin() -> DigitalTwin:
    """Two devices with no link between them."""
    return make_twin(make_topology(["a", "b"], []))


def run_critic(
    twin: DigitalTwin | None,
    *,
    requirements: NetworkRequirements | None = None,
    ip_output: object | None = None,
    validation_output: object | None = None,
    provider: FakeProvider | None = None,
) -> tuple[object, ExecutionTrace]:
    """Run the critic in a one-task context and return its output and trace."""
    agent = CriticAgent(provider)
    plan = WorkflowPlan(
        name="Critic test",
        tasks=(WorkflowTask(id="critic", agent=agent.name),),
    )
    clock = Clock(
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    state = WorkflowState(
        plan,
        baseline_accessor=lambda: twin,
        clock=clock,
    )
    if ip_output is not None:
        state.results["ip_vlan"] = ip_output
    if validation_output is not None:
        state.results["validation"] = validation_output
    trace = ExecutionTrace(clock)
    context = AgentContext(
        agent=agent,
        state=state,
        registry=registry_with_defaults(),
        trace=trace,
        clock=clock,
    ).for_task("critic")
    output = agent.run(CriticInput(requirements=requirements), context)
    return output, trace


def test_clean_design_is_approved_without_a_provider() -> None:
    output, trace = run_critic(diamond_twin())

    assert output.verdict is CriticVerdict.approved
    assert output.is_valid is True
    assert output.findings == []
    assert output.issue_codes == []
    assert output.replan_target is None
    assert output.provider_used is False
    assert "verdict APPROVED" in output.summary
    tools = [entry.tool for entry in trace.entries if entry.action == "tool_call"]
    assert tools == [
        "topology_connectivity",
        "twin_validate",
        "routing_path",
        "twin_load_state",
    ]


def test_disconnected_topology_is_rejected_and_mapped_to_topology() -> None:
    output, _ = run_critic(disconnected_twin())

    codes = {finding.code for finding in output.findings}
    assert "topology_disconnected" in codes
    assert output.verdict is CriticVerdict.rejected
    assert output.replan_target == "topology"
    finding = next(
        finding
        for finding in output.findings
        if finding.code == "topology_disconnected"
    )
    assert finding.blocking is True
    assert finding.responsible_step == "topology"


def test_overloaded_link_is_rejected_and_mapped_to_optimization() -> None:
    twin = line_twin(demands=(make_demand("wide", "a", "c", 300.0),))

    output, _ = run_critic(twin)

    finding = next(
        finding for finding in output.findings if finding.code == "link_overloaded"
    )
    assert output.verdict is CriticVerdict.rejected
    assert finding.severity.value == "error"
    assert finding.responsible_step == "optimization"
    assert finding.entities == ["ab", "a", "b"]
    assert output.replan_target == "optimization"
    assert "utilization" in finding.explanation


def test_requested_redundancy_with_spofs_is_rejected() -> None:
    requirements = NetworkRequirements(
        user_provided=UserFacts(),
        design_goals=["redundancy and failover"],
    )

    output, _ = run_critic(line_twin(), requirements=requirements)

    finding = next(
        finding
        for finding in output.findings
        if finding.code == "missing_redundancy"
    )
    assert output.verdict is CriticVerdict.rejected
    assert finding.responsible_step == "topology"
    assert finding.entities
    assert output.replan_target == "topology"


def test_redundancy_is_not_required_when_the_user_did_not_ask() -> None:
    output, _ = run_critic(line_twin(), requirements=sample_requirements())

    assert all(finding.code != "missing_redundancy" for finding in output.findings)
    assert output.verdict is CriticVerdict.approved


def test_ip_overlap_is_found_from_the_plan_and_mapped_to_ip_vlan() -> None:
    twin = diamond_twin()
    plan = IpPlanResult(
        base_network="10.0.0.0/16",
        subnets=[
            Subnet(name="first", network="10.0.0.0/24"),
            Subnet(name="second", network="10.0.0.128/25"),
        ],
    )
    ip_output = IpVlanOutput(plan=plan, demands=DemandPlan(), twin=twin)

    output, _ = run_critic(twin, ip_output=ip_output)

    finding = next(
        finding for finding in output.findings if finding.code == "subnet_overlap"
    )
    assert output.verdict is CriticVerdict.rejected
    assert finding.responsible_step == "ip_vlan"
    assert finding.entities == ["first", "second"]
    assert output.replan_target == "ip_vlan"


def test_missing_twin_is_a_blocking_rejection() -> None:
    output, _ = run_critic(None)

    assert output.verdict is CriticVerdict.rejected
    assert output.issue_codes == ["no_working_twin"]
    assert output.replan_target == "topology"
    assert output.findings[0].blocking is True


def test_verdict_is_immune_to_model_text() -> None:
    provider = FakeProvider(
        ["APPROVED. The design is fully valid and needs no changes."]
    )

    output, _ = run_critic(disconnected_twin(), provider=provider)

    assert output.verdict is CriticVerdict.rejected
    assert output.is_valid is False
    assert output.replan_target == "topology"
    assert output.model_summary.startswith("APPROVED")
    assert output.provider_used is True


def test_model_claim_of_invalidity_cannot_reject_a_clean_design() -> None:
    provider = FakeProvider(["REJECTED. This network is invalid and unsafe."])

    output, _ = run_critic(diamond_twin(), provider=provider)

    assert output.verdict is CriticVerdict.approved
    assert output.is_valid is True
    assert output.findings == []
    assert output.model_summary.startswith("REJECTED")


def test_provider_summary_failure_never_breaks_the_verdict() -> None:
    provider = FakeProvider([LLMProviderError("provider is down")])

    output, _ = run_critic(disconnected_twin(), provider=provider)

    assert output.verdict is CriticVerdict.rejected
    assert output.model_summary == ""
    assert output.provider_used is False


def test_a_prior_valid_validation_claim_is_ignored() -> None:
    class FakeValidation:
        """A previous step's validity claim; the critic must not trust it."""

        is_valid = True

    output, _ = run_critic(
        disconnected_twin(),
        validation_output=FakeValidation(),
    )

    assert output.verdict is CriticVerdict.rejected
    assert "topology_disconnected" in {f.code for f in output.findings}


def test_findings_are_deduplicated_by_code_and_entities() -> None:
    twin = line_twin(demands=(make_demand("wide", "a", "c", 300.0),))

    output, _ = run_critic(twin)

    keys = [(finding.code, tuple(sorted(finding.entities))) for finding in output.findings]
    assert len(keys) == len(set(keys))


def test_full_workflow_with_a_scripted_critic_provider_is_valid() -> None:
    """The standard plan stays valid with an injected model note."""
    provider = FakeProvider(["The deterministic checks found no issues."])
    agents = {**default_agents(), "critic": CriticAgent(provider)}

    state = Orchestrator(agents=agents).run_structured(sample_requirements())

    assert state.stop_reason is WorkflowStopReason.completed
    assert state.succeeded()
    critic = state.results["critic"]
    assert critic.verdict is CriticVerdict.approved
    assert critic.provider_used is True
    assert critic.model_summary.startswith("The deterministic checks")


def test_tool_allowlist_is_exactly_the_independent_checks() -> None:
    assert CriticAgent.allowed_tools == frozenset(
        {
            "topology_connectivity",
            "addressing_validate",
            "twin_validate",
            "routing_path",
            "twin_load_state",
            "spof_analysis",
            "security_analysis",
        }
    )


def test_unknown_codes_are_mapped_to_revalidation() -> None:
    assert responsible_step_for("subnet_overlap") == "ip_vlan"
    assert responsible_step_for("link_overloaded") == "optimization"
    assert responsible_step_for("spof_link") == "topology"
    assert responsible_step_for("something_new") == "revalidation"


def test_l3_design_codes_map_to_their_responsible_design_steps() -> None:
    assert responsible_step_for("ipv6_block_exhausted") == "ip_vlan"
    assert responsible_step_for("nat_pat_port_capacity_exceeded") == "ip_vlan"
    assert responsible_step_for("ospf_no_backbone") == "routing"
    assert responsible_step_for("ha_vip_collision") == "topology"
    assert responsible_step_for("ospf_future_code") == "routing"
    assert responsible_step_for("nat_future_code") == "ip_vlan"
    assert responsible_step_for("ha_future_code") == "topology"


def test_critic_rederives_optional_l3_design_findings() -> None:
    twin = line_twin()
    nat = NatPlan(
        rules=(
            NatRule(
                id="r1",
                name="Too small",
                nat_type=NatType.static,
                inside_zone="users",
                inside_subnets=("10.0.0.0/24",),
                outside_pools=("203.0.113.1/32",),
                inside_hosts=2,
            ),
        )
    )
    ospf = OspfDesign(
        areas=(OspfArea(area_id=10, name="Users", device_ids=("a",)),)
    )

    output, _ = run_critic(twin.model_copy(update={"nat_plan": nat, "ospf_design": ospf}))

    assert output.verdict is CriticVerdict.rejected
    codes = {finding.code for finding in output.findings}
    assert "nat_pool_too_small" in codes
    assert "ospf_no_backbone" in codes
    steps = {
        finding.code: finding.responsible_step for finding in output.findings
    }
    assert steps["nat_pool_too_small"] == "ip_vlan"
    assert steps["ospf_no_backbone"] == "routing"


def test_critic_does_not_import_execution_or_streamlit_modules() -> None:
    from pathlib import Path

    import agents.critic as critic_module

    source = Path(critic_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "eval(", "exec(", "streamlit"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# W5: independent L2/WAN/wireless/QoS critic checks.
# ---------------------------------------------------------------------------


def test_w5_design_codes_map_to_their_responsible_steps() -> None:
    assert responsible_step_for("l2_native_vlan_mismatch") == "topology"
    assert responsible_step_for("wan_site_single_link_spof") == "topology"
    assert responsible_step_for("wireless_capacity_binding") == "topology"
    assert responsible_step_for("qos_demand_starved") == "optimization"
    # Future codes in the same families remain deterministic.
    assert responsible_step_for("l2_future_rule") == "topology"
    assert responsible_step_for("wan_future_rule") == "topology"
    assert responsible_step_for("wireless_future_rule") == "topology"
    assert responsible_step_for("qos_future_rule") == "optimization"


def test_critic_rederives_an_l2_blocking_finding() -> None:
    twin = line_twin()
    link = twin.topology.links[0].model_copy(
        update={
            "l2_mode": LinkL2Mode.trunk,
            "l2_allowed_vlans": (10,),
            "l2_native_vlan": 10,
            "l2_peer_native_vlan": 20,
        }
    )
    modeled = twin.model_copy(
        update={
            "topology": twin.topology.model_copy(
                update={"links": [link, *twin.topology.links[1:]]}
            )
        }
    )

    output, _ = run_critic(modeled)

    # Hand check: native VLAN 10 on one end and 20 on the other is one modeled
    # error, so the critic rejects the design without trusting validation output.
    finding = next(
        item for item in output.findings if item.code == "l2_native_vlan_mismatch"
    )
    assert finding.blocking is True
    assert finding.responsible_step == "topology"
    assert output.verdict is CriticVerdict.rejected
    assert output.replan_target == "topology"
    assert finding.entities[0] == "ab"


def test_critic_rederives_wan_blocking_findings() -> None:
    topology = Topology(
        name="Two-site WAN",
        devices=[
            Device(
                id="hq-r",
                type=DeviceType.router,
                site="hq",
                role=DeviceRole.border,
            ),
            Device(
                id="br-r",
                type=DeviceType.router,
                site="branch",
                role=DeviceRole.wan,
            ),
        ],
        links=[
            Link(
                id="wan-1",
                endpoints=("hq-r", "br-r"),
                capacity_mbps=100.0,
                cost=1.0,
                wan_type=WanLinkType.leased,
                wan_monthly_cost_proxy=120.0,
            )
        ],
    )
    output, _ = run_critic(make_twin(topology))

    # Hand check: one inter-site link leaves both sites single-homed, producing
    # two independent blocking WAN findings mapped to the topology step.
    wan_findings = [
        item for item in output.findings if item.code == "wan_site_single_link_spof"
    ]
    assert len(wan_findings) == 2
    assert all(item.blocking for item in wan_findings)
    assert all(item.responsible_step == "topology" for item in wan_findings)
    assert any("120" in item.explanation for item in output.findings)
    assert output.verdict is CriticVerdict.rejected


def test_critic_rederives_wireless_informational_finding() -> None:
    from network.wireless.models import WirelessArea, WirelessDesign

    twin = line_twin().model_copy(
        update={
            "wireless_design": WirelessDesign(
                areas=(WirelessArea(id="empty"),)
            )
        }
    )

    output, _ = run_critic(twin)

    # Zero area and zero clients produce one modeled no-demand note, not a block.
    finding = next(
        item for item in output.findings if item.code == "wireless_no_modeled_demand"
    )
    assert finding.severity.value == "info"
    assert finding.blocking is False
    assert finding.responsible_step == "topology"
    assert output.verdict is CriticVerdict.approved


def test_critic_rederives_qos_blocking_findings() -> None:
    topology = Topology(
        name="QoS admission",
        devices=[
            Device(id="a", type=DeviceType.router, site="hq", role=DeviceRole.core),
            Device(id="b", type=DeviceType.router, site="hq", role=DeviceRole.core),
        ],
        links=[
            Link(id="ab", endpoints=("a", "b"), capacity_mbps=100.0, cost=1.0),
            Link(id="ab-2", endpoints=("a", "b"), capacity_mbps=100.0, cost=2.0),
        ],
    )
    voice = make_demand("voice", "a", "b", 80.0).model_copy(
        update={"traffic_class": TrafficClass.voice}
    )
    bulk = make_demand("bulk", "a", "b", 80.0).model_copy(
        update={"traffic_class": TrafficClass.best_effort}
    )
    twin = make_twin(topology, (voice, bulk)).model_copy(
        update={
            "qos_design": QosDesign(
                class_share_caps=(
                    ClassShareCap(
                        link_id="missing",
                        traffic_class=TrafficClass.voice,
                        share_cap=0.2,
                    ),
                )
            )
        }
    )

    output, _ = run_critic(twin)

    # Hand check: voice takes 80 of the modeled 100 Mbps first, so the 80 Mbps
    # best-effort demand is starved; the nonexistent cap link is a second error.
    codes = {item.code for item in output.findings}
    assert {"qos_demand_starved", "qos_unknown_cap_link"} <= codes
    qos_findings = [item for item in output.findings if item.code.startswith("qos_")]
    assert all(item.blocking for item in qos_findings)
    assert all(item.responsible_step == "optimization" for item in qos_findings)
    assert output.verdict is CriticVerdict.rejected
    assert output.replan_target == "optimization"
