"""Pure Pydantic models for design-time network security analysis.

This package models the *design* of zones, services, and firewall policy. It
does not scan hosts, contact devices, look up vulnerabilities, or describe
attack steps. Every output produced from these models must show
:data:`SECURITY_DISCLAIMER`.

Zone criticality is a user-set modeling assumption on a 1--5 scale. It is not a
measured property and is not a CVSS score.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.limits import (
    MAX_FIREWALL_RULES,
    MAX_SECURITY_ASSUMPTIONS,
    MAX_SERVICES,
    MAX_ZONES,
)

SECURITY_DISCLAIMER = (
    "Modeled design-time assessment. Not a vulnerability scan, penetration "
    "test or audit."
)


class ZoneType(str, Enum):
    """Stable category used by deterministic design-weakness rules."""

    untrusted_external = "untrusted_external"
    dmz = "dmz"
    server = "server"
    user = "user"
    management = "management"
    guest = "guest"
    iot = "iot"
    other = "other"


class Protocol(str, Enum):
    """Modeled transport category for one named service."""

    tcp = "tcp"
    udp = "udp"
    icmp = "icmp"
    any = "any"


class PolicyAction(str, Enum):
    """Action of a modeled firewall rule or policy default."""

    allow = "allow"
    deny = "deny"


class Zone(BaseModel):
    """One trust/function zone in the modeled design."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    type: ZoneType
    criticality: int = Field(
        ge=1,
        le=5,
        description="User-set modeling assumption from 1 (low) to 5 (high).",
    )
    member_vlan_ids: tuple[int, ...] = Field(default_factory=tuple)
    member_device_ids: tuple[str, ...] = Field(default_factory=tuple)
    expected_hosts: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional modeled host count used only by the oversized-subnet rule. "
            "When absent, no host-count inference is made."
        ),
    )

    @field_validator("member_vlan_ids", "member_device_ids")
    @classmethod
    def _canonicalize_members(cls, values: tuple[int, ...] | tuple[str, ...]):
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_zone(self) -> Zone:
        if not self.member_vlan_ids and not self.member_device_ids:
            raise ValueError(
                f"Zone {self.id!r} must name at least one VLAN id or device id"
            )
        return self


class Service(BaseModel):
    """One named service with an inclusive modeled port range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    protocol: Protocol
    port_start: int = Field(ge=0, le=65_535)
    port_end: int = Field(ge=0, le=65_535)

    @model_validator(mode="after")
    def _validate_range(self) -> Service:
        if self.port_start > self.port_end:
            raise ValueError(
                f"Service {self.name!r} has port_start {self.port_start} after "
                f"port_end {self.port_end}"
            )
        if self.protocol in {Protocol.icmp, Protocol.any} and (
            self.port_start != 0 or self.port_end != 0
        ):
            raise ValueError(
                f"Service {self.name!r} uses {self.protocol.value}; its port "
                "range must be 0-0 because ports are not modeled for it"
            )
        return self

    def matches(self, protocol: Protocol, port: int) -> bool:
        """Return whether a modeled flow matches this service."""
        if self.protocol is not Protocol.any and self.protocol is not protocol:
            return False
        if self.protocol in {Protocol.icmp, Protocol.any}:
            return True
        return self.port_start <= port <= self.port_end


class FirewallRule(BaseModel):
    """One ordered first-match firewall policy rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=0)
    src_zone: str = Field(min_length=1, max_length=64)
    dst_zone: str = Field(min_length=1, max_length=64)
    services: tuple[str, ...] = Field(default_factory=tuple)
    any_service: bool = False
    action: PolicyAction = PolicyAction.deny
    enabled: bool = True
    note: str = Field(default="", max_length=500)

    @field_validator("services")
    @classmethod
    def _canonicalize_services(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_rule(self) -> FirewallRule:
        if self.any_service and self.services:
            raise ValueError(
                f"Rule {self.id!r} cannot set any_service and name services"
            )
        if not self.any_service and not self.services:
            raise ValueError(
                f"Rule {self.id!r} must set any_service or name at least one service"
            )
        return self


class SecurityModel(BaseModel):
    """A complete, bounded, modeled security design."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    zones: tuple[Zone, ...] = Field(default_factory=tuple, max_length=MAX_ZONES)
    services: tuple[Service, ...] = Field(
        default_factory=tuple, max_length=MAX_SERVICES
    )
    rules: tuple[FirewallRule, ...] = Field(
        default_factory=tuple, max_length=MAX_FIREWALL_RULES
    )
    default_action: PolicyAction = PolicyAction.deny
    assumptions: tuple[str, ...] = Field(
        default_factory=tuple, max_length=MAX_SECURITY_ASSUMPTIONS
    )

    @model_validator(mode="after")
    def _validate_model(self) -> SecurityModel:
        zone_ids = [zone.id for zone in self.zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("Security zone ids must be unique")
        service_names = [service.name for service in self.services]
        if len(service_names) != len(set(service_names)):
            raise ValueError("Security service names must be unique")
        rule_ids = [rule.id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Firewall rule ids must be unique")
        orders = [rule.order for rule in self.rules]
        if len(orders) != len(set(orders)):
            raise ValueError("Firewall rule orders must be unique")
        return self

    @property
    def ordered_rules(self) -> tuple[FirewallRule, ...]:
        """Return enabled and disabled rules in evaluation order."""
        return tuple(sorted(self.rules, key=lambda rule: rule.order))


__all__ = [
    "SECURITY_DISCLAIMER",
    "FirewallRule",
    "PolicyAction",
    "Protocol",
    "SecurityModel",
    "Service",
    "Zone",
    "ZoneType",
]
