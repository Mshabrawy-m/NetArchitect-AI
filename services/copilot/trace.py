"""Bounded prompt trace for optional copilot language calls.

Trace records contain prompt ids and versions, schema names, model names, and
cache outcomes. They never contain API keys, raw user sentences, or raw model
responses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from config.limits import MAX_COPILOT_TRACE_ENTRIES


class PromptTraceRecord(BaseModel):
    """One non-secret record describing a copilot language request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    cache_hit: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromptTrace:
    """A bounded tuple of prompt trace records."""

    def __init__(self, *, max_entries: int = MAX_COPILOT_TRACE_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self.records: tuple[PromptTraceRecord, ...] = ()

    def add(
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        schema_name: str,
        model: str,
        cache_hit: bool = False,
    ) -> PromptTraceRecord:
        """Append one record with an injected UTC timestamp."""
        record = PromptTraceRecord(
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            schema_name=schema_name,
            model=model,
            cache_hit=cache_hit,
        )
        self.records = (*self.records, record)[-self.max_entries :]
        return record

    def rows(self) -> tuple[dict[str, Any], ...]:
        """Return display-safe rows for the Settings page."""
        return tuple(
            {
                "Prompt": record.prompt_id,
                "Version": record.prompt_version,
                "Schema": record.schema_name,
                "Model": record.model,
                "Cache hit": "yes" if record.cache_hit else "no",
                "Time": record.created_at.isoformat(),
            }
            for record in self.records
        )


__all__ = ["PromptTrace", "PromptTraceRecord"]
