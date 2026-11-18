"""Stateless first-match policy evaluation tests."""

from __future__ import annotations

from security import (
    PolicyAction,
    Protocol,
    SecurityModel,
    ZoneType,
    evaluate_policy,
)

from .helpers import make_rule, make_service, make_zone


def _four_rule_model() -> SecurityModel:
    """Build four ordered rules that separate first-match from fallback behavior."""
    return SecurityModel(
        zones=(
            make_zone("z-user", vlan_id=10),
            make_zone("z-server", zone_type=ZoneType.server, vlan_id=20),
        ),
        services=(
            make_service("http"),
            make_service("dns", protocol="udp", port_start=53, port_end=53),
        ),
        rules=(
            make_rule(
                "r1-deny-web",
                order=0,
                src_zone="z-user",
                dst_zone="z-server",
                services=("http",),
                action=PolicyAction.deny,
            ),
            make_rule(
                "r2-allow-web",
                order=1,
                src_zone="z-user",
                dst_zone="z-server",
                services=("http",),
                action=PolicyAction.allow,
            ),
            make_rule(
                "r3-allow-dns",
                order=2,
                src_zone="z-user",
                dst_zone="z-server",
                services=("dns",),
                action=PolicyAction.allow,
            ),
            make_rule(
                "r4-disabled-any",
                order=3,
                src_zone="z-user",
                dst_zone="z-server",
                services=(),
                any_service=True,
                action=PolicyAction.allow,
                enabled=False,
            ),
        ),
        default_action=PolicyAction.deny,
    )


def test_four_rule_first_match_and_default_deny() -> None:
    model = _four_rule_model()

    http = evaluate_policy(model, "z-user", "z-server", Protocol.tcp, 80)
    assert http.action is PolicyAction.deny
    assert http.matched_rule_id == "r1-deny-web"
    assert "First matching rule" in http.reason

    dns = evaluate_policy(model, "z-user", "z-server", Protocol.udp, 53)
    assert dns.action is PolicyAction.allow
    assert dns.matched_rule_id == "r3-allow-dns"

    unmatched = evaluate_policy(model, "z-user", "z-server", Protocol.tcp, 9999)
    assert unmatched.action is PolicyAction.deny
    assert unmatched.matched_rule_id == ""
    assert "default action deny" in unmatched.reason

    intra_zone = evaluate_policy(model, "z-user", "z-user", Protocol.tcp, 80)
    assert intra_zone.action is PolicyAction.allow
    assert intra_zone.matched_rule_id == ""
    assert "Intra-zone" in intra_zone.reason


def test_default_allow_applies_only_after_no_rule_matches() -> None:
    model = _four_rule_model().model_copy(update={"default_action": PolicyAction.allow})

    http = evaluate_policy(model, "z-user", "z-server", Protocol.tcp, 80)
    assert http.action is PolicyAction.deny
    assert http.matched_rule_id == "r1-deny-web"

    unmatched = evaluate_policy(model, "z-user", "z-server", Protocol.tcp, 9999)
    assert unmatched.action is PolicyAction.allow
    assert unmatched.matched_rule_id == ""
    assert "default action allow" in unmatched.reason
