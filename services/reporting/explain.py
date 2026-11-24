"""Optional AI-written explanation for a report document (Phase 11a).

The deterministic document is the source of truth. A language model may add a
short plain-language paragraph, but the paragraph is labelled AI-generated and
is rejected when it contains a numeric token that does not already appear in
the document's sourced values. This is the same numeric-token rule used by the
Phase 10 documentation agent.

The optional explanation never fails report generation: provider errors are
reported as a note and the deterministic document is returned unchanged.
"""

from __future__ import annotations

import json
import re

from config.limits import MAX_DOCUMENTATION_EXPLANATION_CHARS
from core.exceptions import LLMError, ensure_llm_status
from services.llm.models import LLMMessage, MessageRole
from services.llm.provider import LLMProvider

from .models import AIExplanation, ReportDocument

REPORT_EXPLANATION_SYSTEM_PROMPT = (
    "You explain a deterministic network-design report in plain language. "
    "Use only numbers that already appear in the report; do not invent "
    "measurements, thresholds, or device counts. Do not claim the design was "
    "measured or deployed. Keep the explanation short."
)

_PHASE10_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _phase10_numbers(text: str) -> list[float]:
    """Return numeric tokens using the Phase 10 documentation rule."""
    return [float(match.group()) for match in _PHASE10_NUMBER.finditer(text)]


def _explanation_payload(document: ReportDocument) -> dict[str, object]:
    paragraphs: list[str] = []
    table_preview: list[dict[str, object]] = []
    for section in document.sections:
        for block in section.blocks:
            kind = block.kind
            if kind == "paragraph":
                paragraphs.append(block.text)
            elif kind == "table":
                table_preview.append(
                    {
                        "title": block.title,
                        "columns": list(block.columns),
                        "rows": [list(row) for row in block.rows[:10]],
                    }
                )
    return {
        "title": document.title,
        "twin": document.twin.name,
        "sections": [section.title for section in document.sections],
        "paragraphs": paragraphs[:40],
        "tables": table_preview,
        "values": [
            {
                "label": record.label,
                "display": record.display,
                "unit": record.unit,
            }
            for record in document.values[:200]
        ],
        "labels": list(document.labels),
    }


def generate_ai_explanation(
    document: ReportDocument,
    provider: LLMProvider | None,
    *,
    max_chars: int = MAX_DOCUMENTATION_EXPLANATION_CHARS,
) -> AIExplanation:
    """Return a labelled AI explanation, or a rejection/empty result."""
    if provider is None:
        return AIExplanation()

    messages = [
        LLMMessage(
            role=MessageRole.system,
            content=REPORT_EXPLANATION_SYSTEM_PROMPT,
        ),
        LLMMessage(
            role=MessageRole.user,
            content=json.dumps(_explanation_payload(document), sort_keys=True),
        ),
    ]
    try:
        response = provider.complete(messages)
    except LLMError as error:
        return AIExplanation(
            note=ensure_llm_status(
                "The optional AI explanation was unavailable.", error
            ),
        )
    except Exception:  # noqa: BLE001 - optional prose must never fail a report
        return AIExplanation(
            note="The optional AI explanation was unavailable.",
        )

    text = (response.text or "").strip()
    if not text:
        return AIExplanation()

    allowed = {
        round(float(record.numeric), 6)
        for record in document.values
        if record.numeric is not None
    }
    if any(
        round(value, 6) not in allowed for value in _phase10_numbers(text)
    ):
        return AIExplanation(
            rejected=True,
            provider_used=True,
            note=(
                "The model explanation was rejected because it contained a "
                "number that does not match the report's sourced values; no AI "
                "text is shown."
            ),
        )

    return AIExplanation(
        text=text[:max_chars],
        provider_used=True,
    )


__all__ = [
    "REPORT_EXPLANATION_SYSTEM_PROMPT",
    "generate_ai_explanation",
]
