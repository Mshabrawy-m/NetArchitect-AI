"""NEW-twin security operations and reference-integrity tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.limits import MAX_ZONES
from core.exceptions import DuplicateIdError, SchemaError
from digital_twin import DigitalTwin, from_json, to_json
from security import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    ZoneType,
    add_assumption,
    add_rule,
    add_service,
    add_zone,
    clear_security_model,
    ensure_security_model,
    get_security_model,
    remove_rule,
    remove_service,
    remove_zone,
    reorder_rules,
    set_default_action,
    set_security_model,
    update_rule,
    update_service,
    update_zone,
)

from .helpers import make_rule, make_service, make_zone, simple_secured_twin


def test_ensure_and_clear_never_mutate_the_input_twin() -> None:
    twin = simple_secured_twin()
    stored_model = twin.security

    ensured = ensure_security_model(twin)
    assert ensured is not twin
    assert ensured.security == stored_model
    assert twin.security is stored_model

    cleared = clear_security_model(twin)
    assert cleared is not twin
    assert cleared.security is None
    assert twin.security is stored_model
    assert cleared.topology == twin.topology
    assert "security" not in to_json(cleared)


def test_zone_service_and_rule_edits_return_new_twins() -> None:
    twin = simple_secured_twin()
    original_model = twin.security
    assert original_model is not None

    zoned = add_zone(twin, make_zone("z-audit", zone_type=ZoneType.other, vlan_id=99))
    assert zoned is not twin
    assert twin.security is original_model
    assert [zone.id for zone in get_security_model(zoned).zones][-1] == "z-audit"

    updated_zone = update_zone(
        zoned, "z-audit", criticality=5, expected_hosts=24
    )
    audit_zone = next(
        zone for zone in get_security_model(updated_zone).zones if zone.id == "z-audit"
    )
    assert audit_zone.criticality == 5
    assert audit_zone.expected_hosts == 24
    assert get_security_model(zoned).zones[-1].expected_hosts is None

    serviced = add_service(
        updated_zone, make_service("ssh", port_start=22, port_end=22)
    )
    updated_service = update_service(serviced, "ssh", protocol=Protocol.tcp)
    assert "ssh" in {service.name for service in get_security_model(updated_service).services}
    assert "ssh" not in {service.name for service in get_security_model(updated_zone).services}

    ruled = add_rule(
        updated_service,
        make_rule("allow-ssh", order=1, services=("ssh",), dst_zone="z-mgmt"),
    )
    updated_rule = update_rule(
        ruled, "allow-ssh", action=PolicyAction.deny, enabled=False
    )
    rule = next(
        item
        for item in get_security_model(updated_rule).rules
        if item.id == "allow-ssh"
    )
    assert rule.action is PolicyAction.deny
    assert rule.enabled is False
    assert next(
        item for item in get_security_model(ruled).rules if item.id == "allow-ssh"
    ).action is PolicyAction.allow

    reordered = reorder_rules(updated_rule, ("allow-ssh", "allow-web"))
    assert [item.order for item in get_security_model(reordered).ordered_rules] == [0, 1]
    assert [item.id for item in get_security_model(reordered).ordered_rules] == [
        "allow-ssh",
        "allow-web",
    ]

    defaulted = set_default_action(reordered, PolicyAction.allow)
    assert get_security_model(defaulted).default_action is PolicyAction.allow
    assert get_security_model(reordered).default_action is PolicyAction.deny

    assumed = add_assumption(defaulted, "Assumption added through a bounded edit.")
    assert "Assumption added through a bounded edit." in get_security_model(assumed).assumptions
    assert get_security_model(defaulted).assumptions == ()


def test_duplicate_ids_orders_are_rejected() -> None:
    twin = simple_secured_twin()

    with pytest.raises(DuplicateIdError, match="zone id already exists"):
        add_zone(twin, make_zone("z-user", vlan_id=11))
    with pytest.raises(DuplicateIdError, match="service name already exists"):
        add_service(twin, make_service("http"))
    with pytest.raises(DuplicateIdError, match="rule id already exists"):
        add_rule(twin, make_rule("allow-web", order=1))
    with pytest.raises(SchemaError, match="rule order already exists"):
        add_rule(twin, make_rule("allow-other", order=0))


def test_removing_referenced_zone_or_service_is_rejected() -> None:
    twin = simple_secured_twin()

    with pytest.raises(SchemaError, match="referenced by rules"):
        remove_zone(twin, "z-user")
    with pytest.raises(SchemaError, match="referenced by rules"):
        remove_service(twin, "http")

    without_rule = remove_rule(twin, "allow-web")
    assert get_security_model(without_rule).rules == ()
    assert twin.security is not None and twin.security.rules != ()

    without_zone = remove_zone(without_rule, "z-user")
    assert "z-user" not in {
        zone.id for zone in get_security_model(without_zone).zones
    }
    without_service = remove_service(without_rule, "http")
    assert "http" not in {
        service.name for service in get_security_model(without_service).services
    }


def test_operations_enforce_bounds_after_copy() -> None:
    twin: DigitalTwin = set_security_model(make_empty(), SecurityModel())
    model = get_security_model(twin)
    zones = tuple(
        make_zone(f"z-{index}", vlan_id=index + 1) for index in range(MAX_ZONES)
    )
    full = set_security_model(twin, model.model_copy(update={"zones": zones}))

    with pytest.raises(SchemaError, match="Invalid security model edit"):
        add_zone(full, make_zone("z-overflow", vlan_id=MAX_ZONES + 1))


def test_invalid_edit_is_rejected_without_changing_the_twin() -> None:
    twin = simple_secured_twin()
    before = to_json(twin)

    with pytest.raises(SchemaError, match="Invalid security model edit"):
        update_zone(twin, "z-user", criticality=99)
    with pytest.raises(ValidationError):
        FirewallRule(
            id="invalid", order=0, src_zone="a", dst_zone="b", services=(), any_service=False
        )

    assert to_json(twin) == before
    assert from_json(before) == twin


def make_empty() -> DigitalTwin:
    """Return a twin with no stored security model."""
    from tests.unit.digital_twin.helpers import make_twin

    return make_twin()
