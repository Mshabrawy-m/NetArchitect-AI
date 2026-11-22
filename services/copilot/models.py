"""Typed contracts for the bounded copilot features.

Every copilot output is a frozen Pydantic model. Language-model prose can only
produce :class:`ScenarioInterpretation` or :class:`AIExplanationDraft`; those
drafts are audited and converted by deterministic Python before any application
code sees a scenario, verdict, decision, or twin mutation.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.limits import (
    MAX_COPILOT_EXPLANATION_CHARS,
    MAX_COPILOT_TEXT_CHARS,
    MAX_SCENARIO_ELEMENTS,
)
from core.schemas.scenario import Scenario, ScenarioType
from digital_twin import DigitalTwin

from .security_bridge import FORBIDDEN_TERMS, numeric_tokens

_NUMERIC_LITERAL = re.compile(r"^\d+(?:\.\d+)?$")


class ScenarioIntent(str, Enum):
    """The only scenario intents a model may name."""

    fail_link = "fail_link"
    fail_device = "fail_device"
    scale_traffic = "scale_traffic"
    clarify = "clarify"
    out_of_scope = "out_of_scope"


class ScenarioInterpretation(BaseModel):
    """LLM draft for one scenario sentence; never used without an audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: ScenarioIntent
    entity_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=MAX_SCENARIO_ELEMENTS,
        description="Link or device ids copied verbatim from the sentence.",
    )
    numeric_literals: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=8,
        description="Numeric tokens copied verbatim from the sentence.",
    )
    demand_names: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=MAX_SCENARIO_ELEMENTS,
        description="Demand names copied verbatim from the sentence.",
    )
    question: str = Field(default="", max_length=MAX_COPILOT_TEXT_CHARS)
    reason: str = Field(default="", max_length=MAX_COPILOT_TEXT_CHARS)

    @field_validator("entity_ids", "numeric_literals", "demand_names")
    @classmethod
    def _bounded_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values if value.strip())
        if len(cleaned) != len(values):
            raise ValueError("Empty draft values are not allowed.")
        return cleaned

    @field_validator("numeric_literals")
    @classmethod
    def _numeric_shape(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not _NUMERIC_LITERAL.fullmatch(value):
                raise ValueError("numeric_literals must be plain numeric tokens.")
        return values


class AIExplanationDraft(BaseModel):
    """LLM draft for an optional explanation; never authoritative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_COPILOT_TEXT_CHARS)


class TwinAllowlist(BaseModel):
    """Bounded ids and intent names derived from the current twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_ids: tuple[str, ...] = Field(default_factory=tuple)
    device_ids: tuple[str, ...] = Field(default_factory=tuple)
    demand_names: tuple[str, ...] = Field(default_factory=tuple)
    zone_ids: tuple[str, ...] = Field(default_factory=tuple)
    intents: tuple[ScenarioIntent, ...] = Field(
        default_factory=lambda: tuple(ScenarioIntent)
    )
    scenario_types: tuple[ScenarioType, ...] = Field(
        default_factory=lambda: tuple(ScenarioType)
    )

    @classmethod
    def from_twin(cls, twin: DigitalTwin) -> TwinAllowlist:
        """Build the allowlist from validated twin data only."""
        from security import get_security_model

        links = sorted(
            link.id for link in twin.topology.links[:MAX_SCENARIO_ELEMENTS]
        )
        devices = sorted(
            device.id for device in twin.topology.devices[:MAX_SCENARIO_ELEMENTS]
        )
        demands = sorted(
            demand.name for demand in twin.demands[:MAX_SCENARIO_ELEMENTS]
        )
        zones = sorted(
            zone.id for zone in get_security_model(twin).zones[:MAX_SCENARIO_ELEMENTS]
        )
        return cls(
            link_ids=tuple(links),
            device_ids=tuple(devices),
            demand_names=tuple(demands),
            zone_ids=tuple(zones),
        )


class ClarificationCode(str, Enum):
    """Typed reason a scenario cannot be produced yet."""

    missing_link = "missing_link"
    missing_device = "missing_device"
    ambiguous_entity = "ambiguous_entity"
    missing_number = "missing_number"
    unknown_reference = "unknown_reference"
    invented_number = "invented_number"
    out_of_scope = "out_of_scope"
    malformed_draft = "malformed_draft"
    provider_unavailable = "provider_unavailable"


class Clarification(BaseModel):
    """One deterministic clarification or rejection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ClarificationCode
    question: str = Field(min_length=1, max_length=MAX_COPILOT_TEXT_CHARS)


class InterpretationSource(str, Enum):
    """Which path produced a result; never changes its authority."""

    deterministic = "deterministic"
    ai = "ai"
    unavailable = "unavailable"


class InterpretationResult(BaseModel):
    """A validated scenario or typed clarification, with trace metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: InterpretationSource
    scenario: Scenario | None = None
    clarifications: tuple[Clarification, ...] = Field(default_factory=tuple)
    prompt_id: str = ""
    prompt_version: str = ""
    cache_hit: bool = False
    provider_used: bool = False

    @property
    def ready(self) -> bool:
        """Return whether a validated scenario is ready for preview."""
        return self.scenario is not None


class ExplanationTarget(str, Enum):
    """The only result types an optional explanation may describe."""

    route = "route"
    finding = "finding"
    simulation = "simulation"
    optimization = "optimization"
    blast_radius = "blast_radius"
    segmentation_score = "segmentation_score"
    ospf_design = "ospf_design"
    ha_group = "ha_group"
    l2_design = "l2_design"
    wan_design = "wan_design"
    wireless_design = "wireless_design"
    qos_design = "qos_design"


class ExplanationResult(BaseModel):
    """A deterministic explanation with optional audited advisory prose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: ExplanationTarget
    target_id: str
    deterministic_text: str = Field(
        min_length=1,
        max_length=MAX_COPILOT_EXPLANATION_CHARS,
    )
    ai_text: str = Field(default="", max_length=MAX_COPILOT_EXPLANATION_CHARS)
    ai_rejection: str = Field(default="", max_length=MAX_COPILOT_TEXT_CHARS)
    prompt_id: str = ""
    prompt_version: str = ""
    cache_hit: bool = False
    provider_used: bool = False

    @property
    def has_ai(self) -> bool:
        """Return whether an audited AI paragraph is present."""
        return bool(self.ai_text)


def audit_prose(text: str, *, allowed_numbers: str) -> str:
    """Return a rejection reason for unsafe model prose, or an empty string.

    The numeric and out-of-scope checks are the same vocabulary used by the
    security agent's explanation auditor.
    """
    allowed = frozenset(numeric_tokens(allowed_numbers))
    invented = [token for token in numeric_tokens(text) if token not in allowed]
    if invented:
        return "The AI text contained a number that was not in the computed facts."
    lowered = text.lower()
    if any(term in lowered for term in FORBIDDEN_TERMS):
        return "The AI text contained out-of-scope content."
    return ""


__all__ = [
    "AIExplanationDraft",
    "Clarification",
    "ClarificationCode",
    "ExplanationResult",
    "ExplanationTarget",
    "InterpretationResult",
    "InterpretationSource",
    "ScenarioIntent",
    "ScenarioInterpretation",
    "TwinAllowlist",
    "audit_prose",
]
