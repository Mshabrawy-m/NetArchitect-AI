"""Bounded structured-output bridge for optional copilot language calls.

The provider is asked for native JSON matching a fixed Pydantic schema. When a
provider does not populate ``structured``, the same text goes through the
existing extract-and-validate helper. Schema failures are repaired at most
``max_repair_retries`` times. The schema is always chosen by application code;
model output can never widen it.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from config.limits import MAX_LLM_REPAIR_RETRIES
from core.exceptions import LLMSchemaError
from services.llm import LLMMessage, LLMProvider, MessageRole, validate_structured
from services.llm.structured import repair_instruction, schema_instruction


def request_structured(
    provider: LLMProvider,
    schema: type[BaseModel],
    *,
    system_prompt: str,
    user_content: str,
    max_repair_retries: int = MAX_LLM_REPAIR_RETRIES,
) -> BaseModel:
    """Return one schema-valid model from a bounded provider exchange."""
    messages: list[LLMMessage] = [
        LLMMessage(
            role=MessageRole.system,
            content=f"{system_prompt}\n{schema_instruction(schema)}",
        ),
        LLMMessage(role=MessageRole.user, content=user_content),
    ]
    last_error: LLMSchemaError | None = None
    for attempt in range(max(0, int(max_repair_retries)) + 1):
        if attempt and last_error is not None:
            messages = [
                *messages,
                LLMMessage(
                    role=MessageRole.user,
                    content=repair_instruction(schema, str(last_error)),
                ),
            ]
        try:
            response = provider.complete(messages, schema=schema)
        except LLMSchemaError as error:
            last_error = error
            continue
        try:
            if response.structured is not None:
                return schema.model_validate(response.structured)
            return validate_structured(response.text, schema)
        except (ValidationError, LLMSchemaError) as error:
            last_error = LLMSchemaError(str(error))
            continue
    if last_error is None:  # pragma: no cover - loop always runs once
        raise LLMSchemaError("No structured response was produced.")
    raise last_error


__all__ = ["request_structured"]
