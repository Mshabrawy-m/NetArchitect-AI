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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.limits import (
    MAX_FIREWALL_RULES,
    MAX_SERVICES,
    MAX_ZONES,
)
from core.schemas.security import (
    FirewallRule,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
)
from core.schemas.validation import Finding, Severity

SECURITY_DISCLAIMER = (
    "Modeled design-time assessment. Not a vulnerability scan, penetration "
    "test or audit."
)


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


POLICY_REACHABILITY_NOTE = (
    "Modeled policy reachability between design zones. It is a design-time "
    "policy model, not an attack path, exploit chain, or scan of a live network."
)


class ReachabilityCell(DisclosedModel):
    """One zone x zone x service cell of the modeled reachability matrix."""

    source_zone: str
    destination_zone: str
    service: str
    policy_permitted: bool
    route_exists: bool
    routing_modeled: bool
    reachable: bool
    reason: str


class ReachabilityMatrix(DisclosedModel):
    """Complete zone x zone x service modeled policy reachability matrix."""

    zones: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_ZONES)
    services: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_SERVICES)
    cells: tuple[ReachabilityCell, ...] = Field(default_factory=tuple)

    def cell(
        self, source_zone: str, destination_zone: str, service: str
    ) -> ReachabilityCell | None:
        """Return one matrix cell, or ``None`` for an unknown triple."""
        return next(
            (
                cell
                for cell in self.cells
                if cell.source_zone == source_zone
                and cell.destination_zone == destination_zone
                and cell.service == service
            ),
            None,
        )

    def is_reachable(self, source_zone: str, destination_zone: str, service: str) -> bool:
        """Return whether the modeled policy and route permit one triple."""
        cell = self.cell(source_zone, destination_zone, service)
        return bool(cell and cell.reachable)


class BlastRadius(DisclosedModel):
    """Bounded modeled closure of policy reachability from one origin zone."""

    origin_zone: str
    origin_zone_type: ZoneType
    directly_reachable: tuple[str, ...] = Field(default_factory=tuple)
    closure_zones: tuple[str, ...] = Field(default_factory=tuple)
    max_criticality_reached: int = Field(ge=0)
    exposure: bool = False
    hop_count: int = Field(ge=0)


class ReachabilityReport(DisclosedModel):
    """Zone reachability and bounded blast radius for one modeled design."""

    note: str = POLICY_REACHABILITY_NOTE
    matrix: ReachabilityMatrix
    blast_radii: tuple[BlastRadius, ...] = Field(default_factory=tuple)
    exposure_findings: tuple[SecurityFinding, ...] = Field(default_factory=tuple)
    hop_limit: int = Field(ge=0)


POLICY_OPTIMIZER_NOTE = (
    "Modeled policy optimization. Proposals are inert until explicitly applied "
    "to a new twin; no device configuration or command is generated."
)


class RuleChange(DisclosedModel):
    """One inert rule-level edit used to realize an optimizer proposal."""

    op: Literal["remove", "replace", "set_default"]
    target_rule_id: str = ""
    new_rule: FirewallRule | None = None
    new_default_action: PolicyAction | None = None

    @model_validator(mode="after")
    def _validate_change(self) -> RuleChange:
        if self.op == "remove" and not self.target_rule_id:
            raise ValueError("A remove change must name a rule")
        if self.op == "replace" and (not self.target_rule_id or self.new_rule is None):
            raise ValueError("A replace change must name a rule and supply its replacement")
        if (
            self.op == "replace"
            and self.new_rule is not None
            and self.new_rule.id != self.target_rule_id
        ):
            raise ValueError("A replacement rule must keep the target rule id")
        if self.op == "set_default" and self.new_default_action is None:
            raise ValueError("A set_default change must supply the new default action")
        return self


class OptimizationKind(str, Enum):
    """Stable categories of deterministic policy optimization."""

    merge_duplicates = "merge_duplicates"
    remove_shadowed = "remove_shadowed"
    remove_redundant = "remove_redundant"
    reorder_specifics = "reorder_specifics"
    tighten_any = "tighten_any"
    explicit_default_deny = "explicit_default_deny"


class DecisionProof(DisclosedModel):
    """Full finite decision-table comparison between two modeled policies."""

    cases_checked: int = Field(ge=0)
    differing_cases: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    equivalent: bool
    method: str


class OptimizationProposal(DisclosedModel):
    """One inert, selectable policy optimization with its equivalence proof."""

    id: str
    kind: OptimizationKind
    title: str
    explanation: str
    affected_rule_ids: tuple[str, ...] = Field(default_factory=tuple)
    behavior_preserving: bool
    proof: DecisionProof
    changes: tuple[RuleChange, ...] = Field(min_length=1)


class OptimizationPlan(DisclosedModel):
    """Bounded set of deterministic proposals for one modeled policy."""

    note: str = POLICY_OPTIMIZER_NOTE
    model: SecurityModel
    baseline_default_action: PolicyAction
    cases_checked: int = Field(ge=0)
    proposals: tuple[OptimizationProposal, ...] = Field(default_factory=tuple)


MICROSEGMENTATION_NOTE = (
    "Modeled design-time zero-trust microsegmentation. Suggestions are inert "
    "rule additions derived only from demand-implied needs; they are not device "
    "configuration and do not describe an attack path or exploit chain."
)


class RuleAddition(DisclosedModel):
    """One inert modeled rule addition with its design-time reason."""

    rule: FirewallRule
    reason: str


class MicrosegmentationProposal(DisclosedModel):
    """Inert microsegmentation suggestion for one high-criticality zone."""

    id: str
    zone_id: str
    title: str
    explanation: str
    new_rules: tuple[RuleAddition, ...] = Field(min_length=1)
    allow_pairs: tuple[str, ...] = Field(default_factory=tuple)
    default_deny_requested: bool = False
    before_score: int = Field(ge=0, le=100)
    after_score: int = Field(ge=0, le=100)
    before_reachable_count: int = Field(ge=0)
    after_reachable_count: int = Field(ge=0)
    before_max_criticality_reached: int = Field(ge=0)
    after_max_criticality_reached: int = Field(ge=0)


class MicrosegmentationPlan(DisclosedModel):
    """Bounded inert microsegmentation suggestions for one modeled design."""

    note: str = MICROSEGMENTATION_NOTE
    model: SecurityModel
    flows_modeled: int = Field(ge=0)
    proposals: tuple[MicrosegmentationProposal, ...] = Field(default_factory=tuple)


DESIGN_CHECKLIST_VERSION = "1.0"

_DESIGN_CHECKLIST_NOTE = (
    "Design checklist aligned with common practice (design-level). Statuses are "
    "derived only from modeled facts; not-modeled is used when the design model "
    "has no fact for an item. No compliance or certification is claimed."
)


class ChecklistStatus(str, Enum):
    """The only three statuses a design checklist item may have."""

    pass_ = "pass"
    fail = "fail"
    not_modeled = "not-modeled"


class DesignChecklistItem(DisclosedModel):
    """One fixed, versioned checklist item with a linked rule and evidence."""

    id: str
    text: str
    rule_linkage: tuple[str, ...] = Field(default_factory=tuple)
    status: ChecklistStatus
    evidence: tuple[str, ...] = Field(default_factory=tuple)


class DesignChecklist(DisclosedModel):
    """Fixed design checklist result for one modeled design."""

    version: str = DESIGN_CHECKLIST_VERSION
    note: str = _DESIGN_CHECKLIST_NOTE
    items: tuple[DesignChecklistItem, ...]
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    not_modeled_count: int = Field(ge=0)


class SegmentationInput(DisclosedModel):
    """One visible weighted contribution to the segmentation score."""

    name: str
    subscore: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0)
    detail: str


class SegmentationScore(DisclosedModel):
    """Visible 0--100 segmentation score for one modeled design."""

    score: int = Field(ge=0, le=100)
    formula: str
    inputs: tuple[SegmentationInput, ...]
    allowed_count: int = Field(ge=0)
    needed_count: int = Field(ge=0)
    excess_count: int = Field(ge=0)
    need_coverage: float = Field(ge=0.0, le=1.0)
    violation_weight: float = Field(ge=0.0)
    total_weight: float = Field(ge=0.0)
    max_shared_vlan_fraction: float = Field(ge=0.0, le=1.0)
    trust_ranks: dict[str, int] = Field(default_factory=dict)
    zone_count: int = Field(ge=0)
    note: str = POLICY_REACHABILITY_NOTE


class SecurityAnalysis(DisclosedModel):
    """Complete deterministic design-time security assessment."""

    model: SecurityModel
    findings: tuple[SecurityFinding, ...] = Field(default_factory=tuple)
    flow_checks: tuple[FlowCheckResult, ...] = Field(default_factory=tuple)
    summary: SecuritySummary
    risk: RiskAssessment
    proposals: ProposalSet
    template: TemplateDocument
    # Additive optional fields. Legacy analysis JSON without these keys still
    # parses, and twin JSON/fingerprints are unaffected.
    reachability: ReachabilityReport | None = None
    segmentation: SegmentationScore | None = None
    optimizer: OptimizationPlan | None = None
    microsegmentation: MicrosegmentationPlan | None = None
    checklist: DesignChecklist | None = None


__all__ = [
    "DESIGN_CHECKLIST_VERSION",
    "MICROSEGMENTATION_NOTE",
    "POLICY_OPTIMIZER_NOTE",
    "POLICY_REACHABILITY_NOTE",
    "SECURITY_DISCLAIMER",
    "BlastRadius",
    "CatalogRule",
    "ChecklistStatus",
    "DecisionProof",
    "DesignChecklist",
    "DesignChecklistItem",
    "DisclosedModel",
    "FindingCategory",
    "FirewallRule",
    "FlowCheckResult",
    "FlowRequest",
    "FlowVerdict",
    "MicrosegmentationPlan",
    "MicrosegmentationProposal",
    "OptimizationKind",
    "OptimizationPlan",
    "OptimizationProposal",
    "PolicyAction",
    "PolicyDecision",
    "ProposalSet",
    "ProposedRule",
    "Protocol",
    "ReachabilityCell",
    "ReachabilityMatrix",
    "ReachabilityReport",
    "RiskAssessment",
    "RiskLevel",
    "RiskTerm",
    "RuleAddition",
    "RuleChange",
    "SecurityAnalysis",
    "SecurityFinding",
    "SecurityModel",
    "SecurityPosture",
    "SecuritySummary",
    "SegmentationInput",
    "SegmentationScore",
    "Service",
    "TemplateDocument",
    "Zone",
    "ZoneTransition",
    "ZoneType",
]
