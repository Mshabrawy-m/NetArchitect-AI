"""S2: visible, deterministic 0--100 segmentation score tests."""

from __future__ import annotations

import security.segmentation as segmentation_module
from core.schemas.routing import TrafficDemand
from security import (
    BROADCAST_WEIGHT,
    DEFAULT_WEIGHT,
    LEAST_PRIVILEGE_WEIGHT,
    SECURITY_DISCLAIMER,
    TRUST_WEIGHT,
    FlowRequest,
    PolicyAction,
    Protocol,
    SecurityAnalysis,
    SecurityModel,
    analyze_design,
    score_segmentation,
)
from tests.unit.digital_twin.helpers import make_twin

from .helpers import make_rule
from .test_reachability import _chain_twin, _four_zone_model


def test_formula_docstring_documents_every_input() -> None:
    doc = segmentation_module.__doc__
    assert doc is not None
    for token in (
        "0--100",
        "S_default",
        "S_least",
        "S_trust",
        "S_broadcast",
        "allowed",
        "needed",
        "excess",
        "criticality",
        "broadcast",
        "c/5",
        "0.25",
        "0.30",
        "0.15",
    ):
        assert token in doc, f"formula docstring is missing {token!r}"


def test_score_is_bounded_and_inputs_are_hand_checkable() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    score = score_segmentation(twin, model)

    assert 0 <= score.score <= 100
    assert len(score.inputs) == 4
    assert sum(item.weight for item in score.inputs) == 1.0
    assert abs(sum(item.contribution for item in score.inputs) - score.score / 100) < 0.01
    assert score.disclaimer == SECURITY_DISCLAIMER
    assert all(
        abs(item.subscore * item.weight - item.contribution) < 1e-6
        for item in score.inputs
    )

    # Expected by hand: default deny 1.0, no modeled need so excess=3/1 -> 0,
    # six violating lower->higher closure pairs weighted 4.0/7.8, no shared
    # VLAN -> 1.0. 0.25 + 0 + 0.30*(1-4/7.8) + 0.15 = 0.54615 -> 55.
    assert score.score == 55
    assert score.allowed_count == 3
    assert score.needed_count == 0
    assert score.excess_count == 3
    assert score.violation_weight == 4.0
    assert score.total_weight == 7.8
    assert score.max_shared_vlan_fraction == 0.0


def test_weights_are_fixed_and_sum_to_one() -> None:
    assert DEFAULT_WEIGHT + LEAST_PRIVILEGE_WEIGHT + TRUST_WEIGHT + BROADCAST_WEIGHT == 1.0


def test_deny_rule_is_monotonic() -> None:
    twin, base = _chain_twin(), _four_zone_model()
    flat = base.model_copy(
        update={"rules": (), "default_action": PolicyAction.allow}
    )
    pairs = (
        ("z-ext", "z-guest"),
        ("z-guest", "z-app"),
        ("z-app", "z-db"),
        ("z-ext", "z-app"),
    )
    scores = [score_segmentation(twin, flat).score]
    rules = ()
    for index, (source, destination) in enumerate(pairs):
        rules += (
            make_rule(
                f"deny-{index}",
                order=index,
                src_zone=source,
                dst_zone=destination,
                action=PolicyAction.deny,
                services=("http",),
            ),
        )
        scores.append(score_segmentation(twin, flat.model_copy(update={"rules": rules})).score)

    assert scores == sorted(scores)
    assert scores[-1] >= scores[0]


def test_higher_criticality_on_reached_zone_lowers_score() -> None:
    twin, model = _chain_twin(), _four_zone_model()
    baseline = score_segmentation(twin, model)
    raised_zones = tuple(
        zone.model_copy(update={"criticality": 5})
        if zone.id in {"z-app", "z-db"}
        else zone
        for zone in model.zones
    )
    raised = score_segmentation(twin, model.model_copy(update={"zones": raised_zones}))

    assert raised.violation_weight > baseline.violation_weight
    assert raised.score <= baseline.score


def test_modeled_needs_reduce_excess_and_raise_score() -> None:
    twin, model = _chain_twin(), _four_zone_model()
    baseline = score_segmentation(twin, model)
    flows = (
        FlowRequest(
            id="f1",
            source_device_id="d-ext",
            destination_device_id="d-guest",
            protocol=Protocol.tcp,
            port=80,
        ),
    )
    twin_with_demand = make_twin(
        topology=twin.topology,
        demands=(
            TrafficDemand(
                name="guest-to-app",
                source="d-guest",
                destination="d-app",
                bandwidth_mbps=10.0,
            ),
        ),
    )

    scored = score_segmentation(twin_with_demand, model, flows=flows)

    assert scored.needed_count == 2
    assert scored.excess_count < baseline.excess_count
    assert scored.score >= baseline.score


def test_shared_vlan_lowers_broadcast_subscore() -> None:
    twin, model = _chain_twin(), _four_zone_model()
    flat_vlans = tuple(zone.model_copy(update={"member_vlan_ids": (10,)}) for zone in model.zones)

    scored = score_segmentation(twin, model.model_copy(update={"zones": flat_vlans}))

    assert scored.max_shared_vlan_fraction == 1.0
    assert scored.inputs[-1].subscore == 0.0


def test_analysis_integration_and_legacy_json() -> None:
    twin, model = _chain_twin(), _four_zone_model()

    analysis = analyze_design(twin, model=model)
    assert analysis.segmentation == score_segmentation(
        twin, model, matrix=analysis.reachability.matrix
    )

    payload = analysis.model_dump()
    payload.pop("segmentation")
    legacy = SecurityAnalysis.model_validate(payload)
    assert legacy.segmentation is None


def test_empty_model_scores_safely() -> None:
    twin = make_twin(demands=())
    model = SecurityModel()

    scored = score_segmentation(twin, model)

    assert 0 <= scored.score <= 100
    assert scored.zone_count == 0
    assert scored.trust_ranks == {}
    assert scored.total_weight == 0.0
