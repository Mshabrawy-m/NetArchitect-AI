"""Design-time network security analysis public API.

This package is deterministic and offline. It models policy and design
weaknesses from a digital twin; it never scans, probes, or configures a network.
"""

from .derivation import derive_default_security_model
from .models import (
    SECURITY_DISCLAIMER,
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
)
from .operations import (
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

__all__ = [
    "SECURITY_DISCLAIMER",
    "FirewallRule",
    "PolicyAction",
    "Protocol",
    "SecurityModel",
    "Service",
    "Zone",
    "ZoneType",
    "add_assumption",
    "add_rule",
    "add_service",
    "add_zone",
    "clear_security_model",
    "derive_default_security_model",
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
