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
from core.schemas.validation import Finding, Severity

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


class DisclosedModel(BaseModel):
    """Base for every security output. The label cannot be edited away."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disclaimer: str = SECURITY_DISCLAIMER

    @field_validator("disclaimer")
    @classmethod
    def _require_exact_disclaimer(cls, value: str) -> str:
        if value != SECURITY_DISCLAIMER:
            raise ValueError("Security outputs must carry the exact disclaimer")
        return value


class FindingCategory(str, Enum):
    """Origin of a typed security finding."""

    policy = "policy"
    design = "design"


class RiskLevel(str, Enum):
    """Modeled risk band derived from the visible score arithmetic."""

    low = "low"
    moderate = "moderate"
    elevated = "elevated"
    high = "high"


class SecurityPosture(str, Enum):
    """Overall posture derived from findings and modeled risk."""

    hardened = "hardened"
    needs_review = "needs_review"
    high_risk = "high_risk"


class FlowVerdict(str, Enum):
    """Deterministic outcome of one end-to-end flow check."""

    allowed = "allowed"
    no_route = "no_route"
    policy_denied = "policy_denied"
    unassigned_zone = "unassigned_zone"


class SecurityFinding(DisclosedModel):
    """Typed finding with stable code, provenance, and remediation."""

    code: str = Field(min_length=1)
    category: FindingCategory
    severity: Severity
    affected_entities: tuple[str, ...] = Field(default_factory=tuple)
    explanation: str
    remediation: str
    evidence: tuple[str, ...] = Field(default_factory=tuple)
    proposal_src_zone: str = ""
    proposal_dst_zone: str = ""

    def to_validation_finding(self) -> Finding:
        """Wrap this finding in the application's standard finding type."""
        return Finding(
            severity=self.severity,
            code=self.code,
            affected_entities=list(self.affected_entities),
            explanation=self.explanation,
            remediation=self.remediation,
        )


class CatalogRule(DisclosedModel):
    """One fixed design-weakness catalog entry."""

    id: str = Field(min_length=1)
    title: str
    trigger: str
    base_severity: Severity
    remediation: str


class FlowRequest(DisclosedModel):
    """One modeled flow between two devices in the twin."""

    id: str = Field(min_length=1)
    source_device_id: str = Field(min_length=1)
    destination_device_id: str = Field(min_length=1)
    protocol: Protocol
    port: int = Field(default=0, ge=0, le=65_535)

    @model_validator(mode="after")
    def _validate_port(self) -> FlowRequest:
        if self.protocol in {Protocol.icmp, Protocol.any} and self.port != 0:
            raise ValueError(
                f"Flow {self.id!r} uses {self.protocol.value}; its port must be 0"
            )
        return self


class PolicyDecision(DisclosedModel):
    """Result of stateless first-match policy evaluation."""

    source_zone: str
    destination_zone: str
    protocol: Protocol
    port: int
    action: PolicyAction
    matched_rule_id: str = ""
    reason: str


class ZoneTransition(DisclosedModel):
    """One zone boundary crossed by a routed flow."""

    index: int = Field(ge=1)
    from_zone: str
    to_zone: str
    from_device: str
    to_device: str
    decision: PolicyDecision


class FlowCheckResult(DisclosedModel):
    """Routing plus policy outcome for one modeled flow."""

    request: FlowRequest
    verdict: FlowVerdict
    route_reachable: bool
    policy_permitted: bool
    source_zone: str = ""
    destination_zone: str = ""
    device_path: tuple[str, ...] = Field(default_factory=tuple)
    zone_transitions: tuple[ZoneTransition, ...] = Field(default_factory=tuple)
    reason: str


class RiskTerm(DisclosedModel):
    """One visible contribution to the modeled risk score."""

    label: str
    value: int
    basis: str


class RiskAssessment(DisclosedModel):
    """Deterministic risk score with hand-checkable arithmetic."""

    score: int = Field(ge=0)
    level: RiskLevel
    formula: str
    terms: tuple[RiskTerm, ...] = Field(default_factory=tuple)


class SecuritySummary(DisclosedModel):
    """Counts, highest severity, and overall posture for one analysis."""

    zone_count: int = Field(ge=0)
    service_count: int = Field(ge=0)
    rule_count: int = Field(ge=0)
    default_action: PolicyAction
    finding_counts: dict[str, int] = Field(default_factory=dict)
    highest_severity: Severity | None = None
    posture: SecurityPosture


class ProposedRule(DisclosedModel):
    """A rule offered for explicit user acceptance, never auto-applied."""

    id: str = Field(min_length=1)
    src_zone: str = Field(min_length=1)
    dst_zone: str = Field(min_length=1)
    services: tuple[str, ...] = Field(default_factory=tuple)
    any_service: bool = False
    action: PolicyAction = PolicyAction.deny
    reason: str
    based_on_finding: str

    @model_validator(mode="after")
    def _validate_service_mode(self) -> ProposedRule:
        if self.any_service and self.services:
            raise ValueError("A proposed rule cannot combine any_service with services")
        if not self.any_service and not self.services:
            raise ValueError("A proposed rule must name a service or use any_service")
        return self


class ProposalSet(DisclosedModel):
    """Bounded set of proposed policy changes."""

    rules: tuple[ProposedRule, ...] = Field(
        default_factory=tuple, max_length=MAX_FIREWALL_RULES
    )


class TemplateDocument(DisclosedModel):
    """Vendor-neutral, data-only policy intent. No device syntax or commands."""

    title: str
    lines: tuple[str, ...] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def _require_template_header(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value[0] != "TEMPLATE - not applied to any device":
            raise ValueError("Template first line must identify it as unapplied")
        return value

    def text(self) -> str:
        """Return template lines as newline-delimited text."""
        return "\n".join(self.lines)


class SecurityAnalysis(DisclosedModel):
    """Complete deterministic design-time security assessment."""

    model: SecurityModel
    findings: tuple[SecurityFinding, ...] = Field(default_factory=tuple)
    flow_checks: tuple[FlowCheckResult, ...] = Field(default_factory=tuple)
    summary: SecuritySummary
    risk: RiskAssessment
    proposals: ProposalSet
    template: TemplateDocument


__all__ = [
    "SECURITY_DISCLAIMER",
    "CatalogRule",
    "DisclosedModel",
    "FindingCategory",
    "FirewallRule",
    "FlowCheckResult",
    "FlowRequest",
    "FlowVerdict",
    "PolicyAction",
    "PolicyDecision",
    "ProposalSet",
    "ProposedRule",
    "Protocol",
    "RiskAssessment",
    "RiskLevel",
    "RiskTerm",
    "SecurityAnalysis",
    "SecurityFinding",
    "SecurityModel",
    "SecurityPosture",
    "SecuritySummary",
    "Service",
    "TemplateDocument",
    "Zone",
    "ZoneTransition",
    "ZoneType",
]
