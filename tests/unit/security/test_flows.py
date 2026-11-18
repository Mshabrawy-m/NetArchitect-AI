"""End-to-end flow checks: no route versus policy denial."""

from __future__ import annotations

from digital_twin import set_topology
from security import (
    FlowRequest,
    FlowVerdict,
    Protocol,
    analyze_design,
    check_flow,
)

from .design_helpers import hardened_design


def _request(request_id: str, source: str, destination: str) -> FlowRequest:
    return FlowRequest(
        id=request_id,
        source_device_id=source,
        destination_device_id=destination,
        protocol=Protocol.tcp,
        port=80,
    )


def test_policy_denied_flow_has_a_route_but_fails_policy() -> None:
    twin, model = hardened_design()
    request = _request("user-to-mgmt", "user-sw", "mgmt-sw")

    result = check_flow(twin, model, request)

    assert result.verdict is FlowVerdict.policy_denied
    assert result.route_reachable is True
    assert result.policy_permitted is False
    assert result.source_zone == "z-user"
    assert result.destination_zone == "z-mgmt"
    assert result.device_path == ("user-sw", "fw-1", "mgmt-sw")
    assert len(result.zone_transitions) == 2
    assert all(
        transition.decision.action.value == "deny"
        for transition in result.zone_transitions
    )
    assert "Policy denied at" in result.reason
    assert result.disclaimer == (
        "Modeled design-time assessment. Not a vulnerability scan, penetration "
        "test or audit."
    )


def test_no_route_flow_is_distinct_from_policy_denial() -> None:
    twin, model = hardened_design()
    isolated_topology = twin.topology.model_copy(
        update={
            "links": tuple(
                link
                for link in twin.topology.links
                if "iot-sw" not in link.endpoints
            )
        }
    )
    isolated_twin = set_topology(twin, isolated_topology)
    request = _request("user-to-iot", "user-sw", "iot-sw")

    result = check_flow(isolated_twin, model, request)
    analysis = analyze_design(isolated_twin, model=model, flows=(request,))

    assert result.verdict is FlowVerdict.no_route
    assert result.route_reachable is False
    assert result.policy_permitted is False
    assert result.device_path == ()
    assert result.zone_transitions == ()
    assert "No directed path" in result.reason
    assert analysis.flow_checks == (result,)
    assert "POLICY-FLOW-DENIED" not in {
        finding.code for finding in analysis.findings
    }


def test_flow_denial_appears_as_a_policy_finding() -> None:
    twin, model = hardened_design()
    request = _request("user-to-mgmt", "user-sw", "mgmt-sw")

    analysis = analyze_design(twin, model=model, flows=(request,))
    finding = next(
        item for item in analysis.findings if item.code == "POLICY-FLOW-DENIED"
    )

    assert finding.affected_entities == ("user-to-mgmt",)
    assert finding.category.value == "policy"
    assert finding.evidence
    assert "user-to-mgmt" in finding.explanation
