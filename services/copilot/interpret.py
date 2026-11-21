"""C1: turn one short scenario sentence into a validated :class:`Scenario`.

A deterministic parser runs first and handles the documented free-tier forms in
English and Arabic. Only sentences that parser does not recognise are handed to
the optional language model, whose draft is a typed :class:`ScenarioInterpretation`
that is audited against the current twin before a scenario is built. No scenario
is executed here; the UI runs a scenario only after the user confirms a preview.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from pydantic import ValidationError

from config.limits import MAX_COPILOT_TEXT_CHARS, MAX_LLM_REPAIR_RETRIES
from core.exceptions import (
    LLMError,
    LLMMissingKeyError,
    OversizedInputError,
    ScenarioValidationError,
)
from core.inputs import reject_unsafe_text
from core.schemas.scenario import Scenario, ScenarioType
from digital_twin import DigitalTwin
from services.llm import INTERPRET_SCENARIO, LLMProvider, PromptSpec
from simulation import validate_scenario

from .cache import CacheKey, CopilotCache, build_key
from .llm_bridge import request_structured
from .models import (
    Clarification,
    ClarificationCode,
    InterpretationResult,
    InterpretationSource,
    ScenarioIntent,
    ScenarioInterpretation,
    TwinAllowlist,
    audit_prose,
)
from .security_bridge import numeric_tokens
from .trace import PromptTrace

# Intent phrases are matched against the lowercased sentence. Arabic has no
# case, and the same phrase lists keep the two languages in parity.
_LINK_FAIL_PHRASES = (
    "fail link",
    "fail the link",
    "break link",
    "disable link",
    "link fails",
    "link is down",
    "افصل الرابط",
    "فشل الرابط",
    "عطل الرابط",
    "قطع الرابط",
    "الرابط فشل",
)
_DEVICE_FAIL_PHRASES = (
    "fail device",
    "fail node",
    "fail the device",
    "fail the node",
    "break device",
    "disable device",
    "device fails",
    "node fails",
    "device is down",
    "افصل الجهاز",
    "فشل الجهاز",
    "عطل الجهاز",
    "قطع الجهاز",
    "الجهاز فشل",
)
_TRAFFIC_PHRASES = (
    "scale traffic",
    "increase traffic",
    "boost traffic",
    "traffic by",
    "traffic increase",
    "زود حركة المرور",
    "زيادة حركة المرور",
    "رفع حركة المرور",
    "حركة المرور",
)

_NUMBER = re.compile(r"(?<![A-Za-z0-9_.-])\d+(?:\.\d+)?(?![A-Za-z0-9_.-])")

_MISSING_LINK = "Which link should fail? Name one link id from the current twin."
_MISSING_DEVICE = "Which device should fail? Name one device id from the current twin."
_MISSING_NUMBER = "What percentage should traffic be scaled by? Include a number."
_AMBIGUOUS = "More than one entity matched. Name exactly one id from the current twin."
_UNKNOWN = "That id is not in the current twin. Name a link, device, or demand that exists."
_OUT_OF_SCOPE = (
    "I can only prepare what-if scenarios such as 'fail link <id>', "
    "'fail device <id>', or 'scale traffic by <N>%'."
)
_NO_KEY = (
    "This sentence needs the optional AI interpreter. Add a Groq API key in "
    "Settings, or use a supported phrase: 'fail link <id>', 'fail device <id>', "
    "or 'scale traffic by <N>%'."
)
_UNSAFE_DRAFT = "The AI draft was rejected because it did not stay within the twin's data."
_INVALID_SCENARIO = "The interpreted scenario was rejected by the deterministic validator."


def _clarification(code: ClarificationCode, question: str) -> Clarification:
    return Clarification(code=code, question=question)


def _result(
    *,
    source: InterpretationSource,
    scenario: Scenario | None = None,
    clarifications: Sequence[Clarification] = (),
    prompt: PromptSpec = INTERPRET_SCENARIO,
    cache_hit: bool = False,
    provider_used: bool = False,
) -> InterpretationResult:
    return InterpretationResult(
        source=source,
        scenario=scenario,
        clarifications=tuple(clarifications),
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        cache_hit=cache_hit,
        provider_used=provider_used,
    )


def _whole_token_ids(text: str, ids: Sequence[str]) -> list[str]:
    """Return allowlist ids that appear as whole tokens in ``text``."""
    matches: list[str] = []
    for entity_id in ids:
        pattern = rf"(?<![\w-]){re.escape(entity_id)}(?![\w-])"
        if re.search(pattern, text):
            matches.append(entity_id)
    return matches


def _find_numbers(text: str) -> list[str]:
    return [match.group() for match in _NUMBER.finditer(text)]


def _detect_intent(text: str) -> ScenarioIntent | None:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _LINK_FAIL_PHRASES):
        return ScenarioIntent.fail_link
    if any(phrase in lowered for phrase in _DEVICE_FAIL_PHRASES):
        return ScenarioIntent.fail_device
    if any(phrase in lowered for phrase in _TRAFFIC_PHRASES):
        return ScenarioIntent.scale_traffic
    return None


def _scenario_id(kind: ScenarioIntent) -> tuple[str, str]:
    if kind is ScenarioIntent.fail_link:
        return "copilot-link-failure", "AI-assisted link failure"
    if kind is ScenarioIntent.fail_device:
        return "copilot-device-failure", "AI-assisted device failure"
    return "copilot-traffic-scale", "AI-assisted traffic scale"


def _traffic_scenario(
    percent: float,
    demand_names: Sequence[str],
) -> Scenario:
    scenario_id, name = _scenario_id(ScenarioIntent.scale_traffic)
    parameters: dict[str, object] = {"factor": percent / 100.0}
    if demand_names:
        parameters["demand_names"] = list(demand_names)
    return Scenario(
        id=scenario_id,
        name=name,
        type=ScenarioType.increased_traffic_demand,
        description=f"Copilot interpretation: scale traffic by {percent:g}%.",
        parameters=parameters,
    )


def _validated(
    twin: DigitalTwin,
    scenario: Scenario,
    *,
    prompt: PromptSpec,
    source: InterpretationSource,
    cache_hit: bool = False,
    provider_used: bool = False,
) -> InterpretationResult:
    """Validate a built scenario and return a typed result or clarification."""
    try:
        validate_scenario(twin, scenario)
    except (ScenarioValidationError, ValidationError, TypeError, ValueError):
        return _result(
            source=source,
            clarifications=(_clarification(ClarificationCode.malformed_draft, _INVALID_SCENARIO),),
            prompt=prompt,
            cache_hit=cache_hit,
            provider_used=provider_used,
        )
    return _result(
        source=source,
        scenario=scenario,
        prompt=prompt,
        cache_hit=cache_hit,
        provider_used=provider_used,
    )


def _parse_deterministic(
    text: str,
    twin: DigitalTwin,
    allowlist: TwinAllowlist,
    *,
    prompt: PromptSpec,
) -> InterpretationResult | None:
    """Return a result for a recognised form, or ``None`` to try the LLM."""
    intent = _detect_intent(text)
    if intent is None:
        return None

    if intent in (ScenarioIntent.fail_link, ScenarioIntent.fail_device):
        ids = allowlist.link_ids if intent is ScenarioIntent.fail_link else allowlist.device_ids
        code = (
            ClarificationCode.missing_link
            if intent is ScenarioIntent.fail_link
            else ClarificationCode.missing_device
        )
        missing = _MISSING_LINK if intent is ScenarioIntent.fail_link else _MISSING_DEVICE
        matches = _whole_token_ids(text, ids)
        if not matches:
            return _result(
                source=InterpretationSource.deterministic,
                clarifications=(_clarification(code, missing),),
                prompt=prompt,
            )
        if len(matches) > 1:
            return _result(
                source=InterpretationSource.deterministic,
                clarifications=(_clarification(ClarificationCode.ambiguous_entity, _AMBIGUOUS),),
                prompt=prompt,
            )
        entity_id = matches[0]
        scenario_id, name = _scenario_id(intent)
        scenario = Scenario(
            id=scenario_id,
            name=name,
            type=(
                ScenarioType.single_link_failure
                if intent is ScenarioIntent.fail_link
                else ScenarioType.node_failure
            ),
            affected_links=[entity_id] if intent is ScenarioIntent.fail_link else [],
            affected_nodes=[entity_id] if intent is ScenarioIntent.fail_device else [],
            description=f"Copilot interpretation: {intent.value} {entity_id}.",
        )
        return _validated(twin, scenario, prompt=prompt, source=InterpretationSource.deterministic)

    numbers = _find_numbers(text)
    if not numbers:
        return _result(
            source=InterpretationSource.deterministic,
            clarifications=(_clarification(ClarificationCode.missing_number, _MISSING_NUMBER),),
            prompt=prompt,
        )
    percent = float(numbers[-1])
    if percent <= 0 or percent > 10_000:
        return _result(
            source=InterpretationSource.deterministic,
            clarifications=(_clarification(ClarificationCode.missing_number, _MISSING_NUMBER),),
            prompt=prompt,
        )
    demands = _whole_token_ids(text, allowlist.demand_names)
    scenario = _traffic_scenario(percent, demands)
    return _validated(twin, scenario, prompt=prompt, source=InterpretationSource.deterministic)


def _safe_ai_text(text: str, *, sentence: str, fallback: str) -> str:
    """Return model prose only when it passes the shared prose audit."""
    if audit_prose(text, allowed_numbers=sentence):
        return fallback
    return text.strip()


def _draft_to_result(
    draft: ScenarioInterpretation,
    text: str,
    twin: DigitalTwin,
    allowlist: TwinAllowlist,
    *,
    prompt: PromptSpec,
    cache_hit: bool,
    provider_used: bool,
) -> InterpretationResult:
    """Audit a typed draft and build a scenario from deterministic data only."""
    common = {
        "prompt": prompt,
        "cache_hit": cache_hit,
        "provider_used": provider_used,
        "source": InterpretationSource.ai,
    }

    # Verbatim numeric literals are the only numbers a draft may contribute.
    allowed_numbers = frozenset(numeric_tokens(text))
    invented = [value for value in draft.numeric_literals if value not in allowed_numbers]
    if invented:
        return _result(
            clarifications=(_clarification(ClarificationCode.invented_number, _UNSAFE_DRAFT),),
            **common,
        )

    if draft.intent in (ScenarioIntent.clarify, ScenarioIntent.out_of_scope):
        question = _safe_ai_text(
            draft.question or draft.reason,
            sentence=text,
            fallback=_OUT_OF_SCOPE,
        )
        code = (
            ClarificationCode.out_of_scope
            if draft.intent is ScenarioIntent.out_of_scope
            else ClarificationCode.unknown_reference
        )
        return _result(clarifications=(_clarification(code, question),), **common)

    if draft.intent is ScenarioIntent.scale_traffic:
        if len(draft.numeric_literals) != 1:
            return _result(
                clarifications=(_clarification(ClarificationCode.missing_number, _MISSING_NUMBER),),
                **common,
            )
        percent = float(draft.numeric_literals[0])
        if percent <= 0 or percent > 10_000:
            return _result(
                clarifications=(_clarification(ClarificationCode.missing_number, _MISSING_NUMBER),),
                **common,
            )
        unknown_demands = [
            name
            for name in draft.demand_names
            if name not in allowlist.demand_names
            or not _whole_token_ids(text, [name])
        ]
        if unknown_demands:
            return _result(
                clarifications=(_clarification(ClarificationCode.unknown_reference, _UNKNOWN),),
                **common,
            )
        return _validated(
            twin,
            _traffic_scenario(percent, draft.demand_names),
            prompt=prompt,
            source=InterpretationSource.ai,
            cache_hit=cache_hit,
            provider_used=provider_used,
        )

    # Link and device failures share the same allowlist audit.
    ids = allowlist.link_ids if draft.intent is ScenarioIntent.fail_link else allowlist.device_ids
    if len(draft.entity_ids) != 1:
        code = (
            ClarificationCode.missing_link
            if draft.intent is ScenarioIntent.fail_link
            else ClarificationCode.missing_device
        )
        question = (
            _MISSING_LINK if draft.intent is ScenarioIntent.fail_link else _MISSING_DEVICE
        )
        return _result(clarifications=(_clarification(code, question),), **common)
    entity_id = draft.entity_ids[0]
    if entity_id not in ids or not _whole_token_ids(text, [entity_id]):
        return _result(
            clarifications=(_clarification(ClarificationCode.unknown_reference, _UNKNOWN),),
            **common,
        )
    scenario_id, name = _scenario_id(draft.intent)
    scenario = Scenario(
        id=scenario_id,
        name=name,
        type=(
            ScenarioType.single_link_failure
            if draft.intent is ScenarioIntent.fail_link
            else ScenarioType.node_failure
        ),
        affected_links=[entity_id] if draft.intent is ScenarioIntent.fail_link else [],
        affected_nodes=[entity_id] if draft.intent is ScenarioIntent.fail_device else [],
        description=f"Copilot interpretation: {draft.intent.value} {entity_id}.",
    )
    return _validated(
        twin,
        scenario,
        prompt=prompt,
        source=InterpretationSource.ai,
        cache_hit=cache_hit,
        provider_used=provider_used,
    )


def _cache_payload(
    text: str,
    allowlist: TwinAllowlist,
) -> dict[str, object]:
    return {
        "text": text,
        "link_ids": list(allowlist.link_ids),
        "device_ids": list(allowlist.device_ids),
        "demand_names": list(allowlist.demand_names),
        "zone_ids": list(allowlist.zone_ids),
        "intents": [intent.value for intent in ScenarioIntent],
    }


def _key(
    *,
    provider: LLMProvider,
    prompt: PromptSpec,
    payload: dict[str, object],
) -> CacheKey:
    return build_key(
        model=str(getattr(provider, "model", "") or "unknown"),
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        schema_name="ScenarioInterpretation",
        payload=payload,
    )


def _interpret_with_provider(
    text: str,
    twin: DigitalTwin,
    allowlist: TwinAllowlist,
    provider: LLMProvider,
    *,
    cache: CopilotCache | None,
    trace: PromptTrace | None,
    prompt: PromptSpec,
    max_repair_retries: int,
) -> InterpretationResult:
    payload = _cache_payload(text, allowlist)
    key = _key(provider=provider, prompt=prompt, payload=payload)

    cached = cache.get(key, ScenarioInterpretation) if cache is not None else None
    if cached is not None:
        if trace is not None:
            trace.add(
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                schema_name="ScenarioInterpretation",
                model=key.model,
                cache_hit=True,
            )
        return _draft_to_result(
            cached,
            text,
            twin,
            allowlist,
            prompt=prompt,
            cache_hit=True,
            provider_used=False,
        )

    user_content = json.dumps(
        {"sentence": text, "allowlist": payload},
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        draft_value = request_structured(
            provider,
            ScenarioInterpretation,
            system_prompt=prompt.text,
            user_content=user_content,
            max_repair_retries=max_repair_retries,
        )
    except LLMMissingKeyError:
        return _result(
            source=InterpretationSource.unavailable,
            clarifications=(_clarification(ClarificationCode.provider_unavailable, _NO_KEY),),
            prompt=prompt,
            provider_used=False,
        )
    except LLMError:
        return _result(
            source=InterpretationSource.unavailable,
            clarifications=(_clarification(ClarificationCode.provider_unavailable, _NO_KEY),),
            prompt=prompt,
            provider_used=True,
        )

    draft = ScenarioInterpretation.model_validate(draft_value)
    if cache is not None:
        cache.put(key, draft)
    if trace is not None:
        trace.add(
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            schema_name="ScenarioInterpretation",
            model=key.model,
            cache_hit=False,
        )
    return _draft_to_result(
        draft,
        text,
        twin,
        allowlist,
        prompt=prompt,
        cache_hit=False,
        provider_used=True,
    )


def interpret_scenario(
    text: str,
    twin: DigitalTwin,
    *,
    provider: LLMProvider | None = None,
    cache: CopilotCache | None = None,
    trace: PromptTrace | None = None,
    max_repair_retries: int = MAX_LLM_REPAIR_RETRIES,
    prompt: PromptSpec = INTERPRET_SCENARIO,
) -> InterpretationResult:
    """Interpret one short scenario sentence without executing it.

    Deterministic parsing always runs first. An optional provider is used only
    for sentences the parser does not recognise, and its draft is audited before
    a :class:`Scenario` is returned. Callers must show the scenario and obtain
    confirmation before running it through :func:`simulation.run_scenario`.
    """
    if not isinstance(text, str):
        raise OversizedInputError("Scenario sentence must be text.")
    cleaned = reject_unsafe_text(
        text.strip(),
        field="Scenario sentence",
        max_chars=MAX_COPILOT_TEXT_CHARS,
    )
    if not cleaned:
        return _result(
            source=InterpretationSource.deterministic,
            clarifications=(_clarification(ClarificationCode.out_of_scope, _OUT_OF_SCOPE),),
            prompt=prompt,
        )

    allowlist = TwinAllowlist.from_twin(twin)
    deterministic = _parse_deterministic(cleaned, twin, allowlist, prompt=prompt)
    if deterministic is not None:
        return deterministic

    if provider is None:
        return _result(
            source=InterpretationSource.unavailable,
            clarifications=(_clarification(ClarificationCode.provider_unavailable, _NO_KEY),),
            prompt=prompt,
        )
    return _interpret_with_provider(
        cleaned,
        twin,
        allowlist,
        provider,
        cache=cache,
        trace=trace,
        prompt=prompt,
        max_repair_retries=max_repair_retries,
    )


__all__ = ["interpret_scenario"]
