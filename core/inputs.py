"""Guarded parsing for untrusted input at application boundaries.

This module is intentionally small and dependency-free. It caps payload size,
JSON nesting, object width, string length, identifier shape, and numeric
magnitude *before* a schema sees the data. Rejections are typed
(:mod:`core.exceptions`) and never include the rejected secret value in the
message.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from config.limits import (
    MAX_CSV_INPUT_BYTES,
    MAX_IDENTIFIER_CHARS,
    MAX_INPUT_BYTES,
    MAX_INPUT_NUMERIC_MAGNITUDE,
    MAX_INPUT_STRING_CHARS,
    MAX_JSON_DEPTH,
    MAX_JSON_OBJECT_KEYS,
)
from core.exceptions import (
    InputError,
    InvalidInputError,
    MalformedInputError,
    OversizedInputError,
    UnsafeInputError,
)

# Fields whose values are machine identifiers rather than free-form prose.
_IDENTIFIER_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "device_id",
        "link_id",
        "source",
        "destination",
        "from_zone",
        "to_zone",
        "series_id",
        "name",
        "site",
        "department",
        "vlan_name",
        "organization_name",
        "title",
    }
)

# Fields whose values are lists of identifiers.
_IDENTIFIER_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "endpoints",
        "affected_devices",
        "affected_links",
        "affected_nodes",
        "device_ids",
        "link_ids",
        "failed_devices",
        "failed_links",
    }
)

# Bidirectional and zero-width controls can reorder or hide text without
# changing its visible bytes, so they are rejected in every untrusted string.
_FORMAT_CONTROLS: frozenset[int] = frozenset(
    {
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        0x200B,
        0x200C,
        0x200D,
        0xFEFF,
    }
)

# Path-like identifiers are rejected. A single slash inside a prose label is
# allowed because network names and provenance keys legitimately use it.
_PATH_LIKE = re.compile(
    r"(?:\.\.[\\/]|(?:\A[A-Za-z]:[\\/])|(?:\A[\\/])|(?:\A~[\\/])|%2e%2e)",
    re.IGNORECASE,
)


def _byte_length(text: str) -> int:
    return len(text.encode("utf-8"))


def validate_text_size(
    text: str,
    *,
    label: str,
    max_bytes: int = MAX_INPUT_BYTES,
) -> str:
    """Return ``text`` after checking its type and UTF-8 byte size."""
    if not isinstance(text, str):
        raise InvalidInputError(f"{label} must be text.")
    size = _byte_length(text)
    if size > max_bytes:
        raise OversizedInputError(
            f"{label} is {size} bytes; the limit is {max_bytes}."
        )
    return text


def reject_unsafe_text(
    value: str,
    *,
    field: str = "Text",
    max_chars: int = MAX_INPUT_STRING_CHARS,
    allow_path: bool = True,
) -> str:
    """Reject control, bidi, zero-width, and optionally path-like text."""
    if not isinstance(value, str):
        raise InvalidInputError(f"{field} must be text.")
    if len(value) > max_chars:
        raise OversizedInputError(
            f"{field} is {len(value)} characters; the limit is {max_chars}."
        )
    for character in value:
        code = ord(character)
        if code < 32 and character not in "\t\n\r":
            raise UnsafeInputError(f"{field} contains a control character.")
        if code == 127 or code in _FORMAT_CONTROLS:
            raise UnsafeInputError(f"{field} contains a hidden formatting character.")
    if not allow_path and _PATH_LIKE.search(value):
        raise UnsafeInputError(f"{field} must not look like a file path.")
    return value


def validate_identifier(value: str, *, field: str = "Identifier") -> str:
    """Return a bounded, visible, non-path-like identifier string."""
    reject_unsafe_text(
        value,
        field=field,
        max_chars=MAX_IDENTIFIER_CHARS,
        allow_path=False,
    )
    if not value.strip():
        raise InvalidInputError(f"{field} must not be empty.")
    return value


def validate_csv_input(
    data: bytes | str,
    *,
    label: str = "CSV input",
    max_bytes: int = MAX_CSV_INPUT_BYTES,
) -> str:
    """Decode and cap untrusted CSV bytes before any row parsing."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise MalformedInputError(f"{label} is not valid UTF-8.") from error
    else:
        text = data
    validate_text_size(text, label=label, max_bytes=max_bytes)
    reject_unsafe_text(text, field=label, max_chars=max_bytes, allow_path=True)
    return text


def _scan_json_depth(text: str, *, label: str) -> None:
    """Check bracket nesting in one linear pass outside JSON strings."""
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise OversizedInputError(
                    f"{label} nesting exceeds {MAX_JSON_DEPTH} levels."
                )
        elif character in "]}":
            depth -= 1
    if in_string:
        raise MalformedInputError(f"{label} contains an unterminated string.")


def _reject_constant(value: str) -> Any:
    raise InvalidInputError(f"JSON constant {value} is not accepted.")


def _parse_number(text: str) -> float | int:
    try:
        value = float(text) if "." in text or "e" in text.lower() else int(text)
    except ValueError as error:
        raise InvalidInputError("A JSON number is malformed.") from error
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidInputError("JSON numbers must be finite.")
    if abs(value) > MAX_INPUT_NUMERIC_MAGNITUDE:
        raise OversizedInputError("A JSON number exceeds the supported magnitude.")
    return value


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) > MAX_JSON_OBJECT_KEYS:
        raise OversizedInputError(
            f"A JSON object has more than {MAX_JSON_OBJECT_KEYS} keys."
        )
    result: dict[str, Any] = {}
    for key, value in pairs:
        reject_unsafe_text(key, field="JSON key", allow_path=True)
        if key in result:
            raise InvalidInputError(f"JSON key {key!r} appears more than once.")
        result[key] = value
    return result


def _validate_values(value: Any, *, field: str, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise OversizedInputError(
            f"{field} nesting exceeds {MAX_JSON_DEPTH} levels."
        )
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        reject_unsafe_text(value, field=field, allow_path=True)
        if field in _IDENTIFIER_FIELDS:
            validate_identifier(value, field=field)
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidInputError(f"{field} must be finite.")
        if abs(value) > MAX_INPUT_NUMERIC_MAGNITUDE:
            raise OversizedInputError(f"{field} exceeds the supported magnitude.")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_field = key if isinstance(key, str) else field
            _validate_values(child, field=child_field, depth=depth + 1)
            if key in _IDENTIFIER_LIST_FIELDS and isinstance(child, list):
                for item in child:
                    if isinstance(item, str):
                        validate_identifier(item, field=str(key))
        return
    if isinstance(value, list):
        for child in value:
            _validate_values(child, field=field, depth=depth + 1)
        return
    raise InvalidInputError(f"{field} has an unsupported JSON value type.")


def parse_json_text(
    text: str,
    *,
    label: str,
    max_bytes: int = MAX_INPUT_BYTES,
) -> Any:
    """Parse bounded untrusted JSON text into plain Python values."""
    validate_text_size(text, label=label, max_bytes=max_bytes)
    _scan_json_depth(text, label=label)
    try:
        data = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_number,
            parse_int=_parse_number,
        )
    except json.JSONDecodeError as error:
        raise MalformedInputError(f"{label} is not valid JSON: {error.msg}.") from error
    except InputError:
        raise
    except (TypeError, ValueError, RecursionError) as error:
        raise MalformedInputError(f"{label} could not be parsed.") from error
    _validate_values(data, field=label)
    return data


__all__ = [
    "parse_json_text",
    "reject_unsafe_text",
    "validate_csv_input",
    "validate_identifier",
    "validate_text_size",
]
