"""Stable, round-trippable JSON export for a report document.

The JSON payload is the document's own validated model dump. Key order is
sorted, indentation is fixed, and the encoding is UTF-8, so the same document
always produces the same bytes. :func:`from_json` validates the payload back
into a :class:`~services.reporting.models.ReportDocument`; the round trip is
exact for every field the model stores.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from core.exceptions import ReportExportError
from services.reporting.models import REPORT_SCHEMA_VERSION, ReportDocument

from .common import enforce_size


def to_json(document: ReportDocument) -> bytes:
    """Serialize ``document`` to deterministic UTF-8 JSON bytes."""
    payload = document.model_dump(mode="json")
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return enforce_size((text + "\n").encode("utf-8"), kind="JSON")


def from_json(data: bytes | str) -> ReportDocument:
    """Validate JSON bytes or text back into a report document."""
    try:
        text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    except UnicodeDecodeError as error:
        raise ReportExportError("The JSON export is not valid UTF-8.") from error
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ReportExportError(
            f"The JSON export is not valid JSON: {error.msg}."
        ) from error
    if not isinstance(parsed, dict):
        raise ReportExportError("The JSON export must contain one object.")
    version = parsed.get("schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise ReportExportError(
            f"Unsupported report schema version {version!r}; this build reads "
            f"version {REPORT_SCHEMA_VERSION}."
        )
    try:
        return ReportDocument.model_validate(parsed)
    except ValidationError as error:
        raise ReportExportError(
            "The JSON export does not match the report document schema."
        ) from error


__all__ = ["from_json", "to_json"]
