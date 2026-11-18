"""Immutable-style operations on a modeled security policy.

Every function returns a NEW twin. The input twin and its security model are
never mutated. Removing a zone or service referenced by a rule is rejected
instead of silently changing the policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from core.exceptions import DuplicateIdError, SchemaError

from .derivation import derive_default_security_model

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin.models import DigitalTwin

from .models import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
)

_UNSET = object()


def get_security_model(twin: DigitalTwin) -> SecurityModel:
    """Return the stored model or a deterministic derived default."""
    return twin.security if twin.security is not None else derive_default_security_model(twin)


def _with_model(twin: DigitalTwin, model: SecurityModel) -> DigitalTwin:
    # Imported lazily so ``digital_twin.models`` can import ``security.models``
    # without a module-level cycle through the security package API.
    from digital_twin.models import TWIN_SCHEMA_VERSION

    metadata = twin.metadata.model_copy(
        update={"schema_version": TWIN_SCHEMA_VERSION}
    )
    return twin.model_copy(update={"security": model, "metadata": metadata})


def _replace_model(
    twin: DigitalTwin,
    model: SecurityModel,
    *,
    message: str = "Invalid security model edit",
) -> DigitalTwin:
    """Revalidate a copied model, then attach it to a NEW twin.

    ``model_copy`` bypasses Pydantic validators, so every edit must round-trip
    through ``model_validate`` before it can become the stored design.
    """
    try:
        validated = SecurityModel.model_validate(model.model_dump())
    except ValidationError as error:
        raise SchemaError(f"{message}: {error}") from error
    return _with_model(twin, validated)


def set_security_model(twin: DigitalTwin, model: SecurityModel) -> DigitalTwin:
    """Return a NEW twin carrying ``model`` as its security design."""
    return _replace_model(twin, model, message="Invalid security model")


def ensure_security_model(twin: DigitalTwin) -> DigitalTwin:
    """Return a NEW twin with stored or derived security data."""
    model = twin.security if twin.security is not None else derive_default_security_model(twin)
    return _replace_model(
        twin, model, message="Invalid stored security model"
    )


def clear_security_model(twin: DigitalTwin) -> DigitalTwin:
    """Return a NEW twin with ``security=None``; topology data is unchanged."""
    return twin.model_copy(update={"security": None})


def add_zone(twin: DigitalTwin, zone: Zone) -> DigitalTwin:
    """Add one zone to a NEW twin."""
    model = get_security_model(twin)
    if any(item.id == zone.id for item in model.zones):
        raise DuplicateIdError(f"Security zone id already exists: {zone.id!r}")
    return _replace_model(twin, model.model_copy(update={"zones": model.zones + (zone,)}))


def update_zone(
    twin: DigitalTwin,
    zone_id: str,
    *,
    name: str | object = _UNSET,
    zone_type: ZoneType | object = _UNSET,
    criticality: int | object = _UNSET,
    member_vlan_ids: tuple[int, ...] | object = _UNSET,
    member_device_ids: tuple[str, ...] | object = _UNSET,
    expected_hosts: int | None | object = _UNSET,
) -> DigitalTwin:
    """Return a NEW twin with one zone's edited fields."""
    model = get_security_model(twin)
    zones: list[Zone] = []
    found = False
    for zone in model.zones:
        if zone.id != zone_id:
            zones.append(zone)
            continue
        found = True
        changes: dict[str, Any] = {}
        if name is not _UNSET:
            changes["name"] = name
        if zone_type is not _UNSET:
            changes["type"] = zone_type
        if criticality is not _UNSET:
            changes["criticality"] = criticality
        if member_vlan_ids is not _UNSET:
            changes["member_vlan_ids"] = member_vlan_ids
        if member_device_ids is not _UNSET:
            changes["member_device_ids"] = member_device_ids
        if expected_hosts is not _UNSET:
            changes["expected_hosts"] = expected_hosts
        zones.append(zone.model_copy(update=changes))
    if not found:
        raise SchemaError(f"Unknown security zone id: {zone_id!r}")
    return _replace_model(twin, model.model_copy(update={"zones": tuple(zones)}))


def remove_zone(twin: DigitalTwin, zone_id: str) -> DigitalTwin:
    """Remove one zone, rejecting removal while rules still reference it."""
    model = get_security_model(twin)
    referenced = [
        rule.id
        for rule in model.rules
        if rule.src_zone == zone_id or rule.dst_zone == zone_id
    ]
    if referenced:
        raise SchemaError(
            f"Zone {zone_id!r} is referenced by rules: {', '.join(referenced)}"
        )
    if not any(zone.id == zone_id for zone in model.zones):
        raise SchemaError(f"Unknown security zone id: {zone_id!r}")
    zones = tuple(zone for zone in model.zones if zone.id != zone_id)
    return _replace_model(twin, model.model_copy(update={"zones": zones}))


def add_service(twin: DigitalTwin, service: Service) -> DigitalTwin:
    """Add one named service to a NEW twin."""
    model = get_security_model(twin)
    if any(item.name == service.name for item in model.services):
        raise DuplicateIdError(f"Security service name already exists: {service.name!r}")
    return _replace_model(
        twin, model.model_copy(update={"services": model.services + (service,)})
    )


def update_service(
    twin: DigitalTwin,
    service_name: str,
    *,
    protocol: Protocol | object = _UNSET,
    port_start: int | object = _UNSET,
    port_end: int | object = _UNSET,
) -> DigitalTwin:
    """Return a NEW twin with one service's edited fields."""
    model = get_security_model(twin)
    services: list[Service] = []
    found = False
    for service in model.services:
        if service.name != service_name:
            services.append(service)
            continue
        found = True
        changes: dict[str, Any] = {}
        if protocol is not _UNSET:
            changes["protocol"] = protocol
        if port_start is not _UNSET:
            changes["port_start"] = port_start
        if port_end is not _UNSET:
            changes["port_end"] = port_end
        services.append(service.model_copy(update=changes))
    if not found:
        raise SchemaError(f"Unknown security service: {service_name!r}")
    return _replace_model(
        twin, model.model_copy(update={"services": tuple(services)})
    )


def remove_service(twin: DigitalTwin, service_name: str) -> DigitalTwin:
    """Remove one service, rejecting removal while rules still reference it."""
    model = get_security_model(twin)
    referenced = [
        rule.id for rule in model.rules if service_name in rule.services
    ]
    if referenced:
        raise SchemaError(
            f"Service {service_name!r} is referenced by rules: {', '.join(referenced)}"
        )
    if not any(service.name == service_name for service in model.services):
        raise SchemaError(f"Unknown security service: {service_name!r}")
    services = tuple(
        service for service in model.services if service.name != service_name
    )
    return _replace_model(twin, model.model_copy(update={"services": services}))


def add_rule(twin: DigitalTwin, rule: FirewallRule) -> DigitalTwin:
    """Add one rule to a NEW twin."""
    model = get_security_model(twin)
    if any(item.id == rule.id for item in model.rules):
        raise DuplicateIdError(f"Firewall rule id already exists: {rule.id!r}")
    if any(item.order == rule.order for item in model.rules):
        raise SchemaError(f"Firewall rule order already exists: {rule.order}")
    rules = tuple(sorted((*model.rules, rule), key=lambda item: item.order))
    return _replace_model(twin, model.model_copy(update={"rules": rules}))


def update_rule(
    twin: DigitalTwin,
    rule_id: str,
    *,
    order: int | object = _UNSET,
    src_zone: str | object = _UNSET,
    dst_zone: str | object = _UNSET,
    services: tuple[str, ...] | object = _UNSET,
    any_service: bool | object = _UNSET,
    action: PolicyAction | object = _UNSET,
    enabled: bool | object = _UNSET,
    note: str | object = _UNSET,
) -> DigitalTwin:
    """Return a NEW twin with one rule's edited fields."""
    model = get_security_model(twin)
    rules: list[FirewallRule] = []
    found = False
    for rule in model.rules:
        if rule.id != rule_id:
            rules.append(rule)
            continue
        found = True
        changes: dict[str, Any] = {}
        for field, value in (
            ("order", order),
            ("src_zone", src_zone),
            ("dst_zone", dst_zone),
            ("services", services),
            ("any_service", any_service),
            ("action", action),
            ("enabled", enabled),
            ("note", note),
        ):
            if value is not _UNSET:
                changes[field] = value
        rules.append(rule.model_copy(update=changes))
    if not found:
        raise SchemaError(f"Unknown firewall rule id: {rule_id!r}")
    candidate = model.model_copy(update={"rules": tuple(rules)})
    return _replace_model(twin, candidate, message="Invalid firewall rule edit")


def remove_rule(twin: DigitalTwin, rule_id: str) -> DigitalTwin:
    """Remove one rule from a NEW twin."""
    model = get_security_model(twin)
    if not any(rule.id == rule_id for rule in model.rules):
        raise SchemaError(f"Unknown firewall rule id: {rule_id!r}")
    rules = tuple(rule for rule in model.rules if rule.id != rule_id)
    return _replace_model(twin, model.model_copy(update={"rules": rules}))


def reorder_rules(twin: DigitalTwin, ordered_rule_ids: tuple[str, ...]) -> DigitalTwin:
    """Replace rule order using the supplied complete id sequence."""
    model = get_security_model(twin)
    existing = {rule.id: rule for rule in model.rules}
    supplied = set(ordered_rule_ids)
    if supplied != set(existing):
        raise SchemaError("Reorder must name every firewall rule exactly once")
    if len(ordered_rule_ids) != len(supplied):
        raise SchemaError("Reorder contains duplicate firewall rule ids")
    rules = tuple(
        existing[rule_id].model_copy(update={"order": index})
        for index, rule_id in enumerate(ordered_rule_ids)
    )
    return _replace_model(twin, model.model_copy(update={"rules": rules}))


def set_default_action(twin: DigitalTwin, action: PolicyAction) -> DigitalTwin:
    """Set the explicit modeled default action on a NEW twin."""
    model = get_security_model(twin)
    return _replace_model(twin, model.model_copy(update={"default_action": action}))


def add_assumption(twin: DigitalTwin, assumption: str) -> DigitalTwin:
    """Append one security modeling assumption to a NEW twin."""
    model = get_security_model(twin)
    return _replace_model(
        twin,
        model.model_copy(update={"assumptions": model.assumptions + (assumption,)}),
    )


__all__ = [
    "add_assumption",
    "add_rule",
    "add_service",
    "add_zone",
    "clear_security_model",
    "ensure_security_model",
    "get_security_model",
    "remove_rule",
    "remove_service",
    "remove_zone",
    "reorder_rules",
    "set_default_action",
    "set_security_model",
    "update_rule",
    "update_service",
    "update_zone",
]
