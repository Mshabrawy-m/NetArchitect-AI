"""Structured-output extraction and schema validation.

Invalid output never reaches application code: it is either repaired with the
provider under a bounded retry count or rejected with a typed error.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from core.exceptions import (
    InputError,
    LLMMalformedResponseError,
    LLMSchemaError,
    MalformedInputError,
)
from core.inputs import parse_json_text, validate_text_size

_MALFORMED = object()

ModelT = TypeVar("ModelT", bound=BaseModel)


def extract_json(text: str) -> Any:
    """Return the first JSON value in ``text``.

    Models often wrap JSON in prose or a fenced code block. The decoder scans
    for the first object or array and ignores surrounding text, but it never
    evaluates code.
    """
    stripped = validate_text_size(text, label="LLM response").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            stripped = "\n".join(lines[1:]).removesuffix("```").strip()

    def bounded_decode(candidate: str) -> Any:
        try:
            return parse_json_text(candidate, label="LLM response")
        except MalformedInputError:
            return _MALFORMED
        except InputError as error:
            raise LLMMalformedResponseError(str(error)) from error

    first = bounded_decode(stripped)
    if first is not _MALFORMED:
        return first

    for index, character in enumerate(stripped):
        if character not in "{[":
            continue
        value = bounded_decode(stripped[index:])
        if value is not _MALFORMED:
            return value
    raise LLMMalformedResponseError(
        "The LLM response did not contain a JSON object or array."
    )


def describe_validation_error(error: ValidationError) -> str:
    """Return a compact, value-free description of a schema failure."""
    details = [
        f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
        for item in error.errors()[:5]
    ]
    return "; ".join(details)


def validate_structured(text: str, schema: type[ModelT]) -> ModelT:
    """Parse and validate ``text`` into ``schema``.

    Raises :class:`~core.exceptions.LLMSchemaError` on any failure so callers
    see one typed error regardless of whether JSON parsing or field validation
    failed.
    """
    try:
        payload = extract_json(text)
    except LLMMalformedResponseError as error:
        raise LLMSchemaError(str(error)) from error
    try:
        return schema.model_validate(payload)
    except ValidationError as error:
        raise LLMSchemaError(
            f"Structured output did not match {schema.__name__}: "
            f"{describe_validation_error(error)}"
        ) from error


def schema_instruction(schema: type[BaseModel]) -> str:
    """Return the system instruction prepended for structured requests."""
    return (
        "Return only one JSON object with no prose or code fences. "
        f"The object must validate against the {schema.__name__} schema."
    )


def repair_instruction(schema: type[BaseModel], issue: str) -> str:
    """Return the repair message sent after a schema failure."""
    return (
        "Your previous response was rejected by schema validation. "
        f"Fix the following issue and return the corrected JSON object only: {issue}"
    )


__all__ = [
    "describe_validation_error",
    "extract_json",
    "repair_instruction",
    "schema_instruction",
    "validate_structured",
]
