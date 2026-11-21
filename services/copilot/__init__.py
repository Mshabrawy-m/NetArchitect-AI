"""Optional copilot features with deterministic engines as the source of truth.

This package imports no Streamlit. It provides typed interpretation, bounded
caching and tracing, deterministic suggestions and explanations, and a session
decision log. Language-model prose is validated and audited before it reaches
any application code.
"""

from __future__ import annotations

from .cache import CacheKey, CopilotCache, build_key, input_hash
from .interpret import interpret_scenario
from .llm_bridge import request_structured
from .models import (
    AIExplanationDraft,
    Clarification,
    ClarificationCode,
    InterpretationResult,
    InterpretationSource,
    ScenarioIntent,
    ScenarioInterpretation,
    TwinAllowlist,
    audit_prose,
)
from .suggest import (
    CandidateProposal,
    SecurityProposal,
    Suggestion,
    SuggestionKind,
    SuggestionReport,
    apply_suggestion,
    suggest,
)
from .trace import PromptTrace, PromptTraceRecord

__all__ = [
    "AIExplanationDraft",
    "CacheKey",
    "CandidateProposal",
    "Clarification",
    "ClarificationCode",
    "CopilotCache",
    "InterpretationResult",
    "InterpretationSource",
    "PromptTrace",
    "PromptTraceRecord",
    "ScenarioIntent",
    "ScenarioInterpretation",
    "SecurityProposal",
    "Suggestion",
    "SuggestionKind",
    "SuggestionReport",
    "TwinAllowlist",
    "apply_suggestion",
    "audit_prose",
    "build_key",
    "input_hash",
    "interpret_scenario",
    "request_structured",
    "suggest",
]
