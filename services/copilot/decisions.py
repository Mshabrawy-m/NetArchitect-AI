"""C4: session-bounded design decisions recorded after explicit user actions.

Decision records contain only typed ids, labels, and deterministic fingerprints.
No language model contributes to them, and no prompt, raw prose, or API key is
ever stored. The log lives in session state through :mod:`ui.state` accessors and
is capped by ``MAX_COPILOT_DECISIONS``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.limits import MAX_COPILOT_DECISIONS

_MAX_DETAIL_ITEMS = 8
_MAX_DETAIL_CHARS = 200


class DecisionKind(str, Enum):
    """The only explicit actions that may enter the decision log."""

    suggestion_accepted = "suggestion_accepted"
    sample_applied = "sample_applied"
    snapshot_saved = "snapshot_saved"
    security_proposal_accepted = "security_proposal_accepted"
    optimization_candidate_selected = "optimization_candidate_selected"


class DecisionRecord(BaseModel):
    """One frozen, timestamped design decision with deterministic provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DecisionKind
    subject_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    page: str = Field(min_length=1, max_length=100)
    source_fingerprint: str = Field(default="", max_length=128)
    result_fingerprint: str = Field(default="", max_length=128)
    details: tuple[tuple[str, str], ...] = Field(
        default_factory=tuple,
        max_length=_MAX_DETAIL_ITEMS,
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("details")
    @classmethod
    def _bound_details(cls, value: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
        for key, item in value:
            if len(key) > _MAX_DETAIL_CHARS or len(item) > _MAX_DETAIL_CHARS:
                raise ValueError("Decision details are too long.")
        return value


class DecisionLog:
    """A bounded tuple of decision records with canonical JSON export."""

    def __init__(self, *, max_entries: int = MAX_COPILOT_DECISIONS) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self.records: tuple[DecisionRecord, ...] = ()

    def add(
        self,
        *,
        kind: DecisionKind,
        subject_id: str,
        title: str,
        page: str,
        source_fingerprint: str = "",
        result_fingerprint: str = "",
        details: tuple[tuple[str, str], ...] = (),
    ) -> DecisionRecord:
        """Append one decision with an injected UTC timestamp."""
        record = DecisionRecord(
            kind=kind,
            subject_id=subject_id,
            title=title,
            page=page,
            source_fingerprint=source_fingerprint,
            result_fingerprint=result_fingerprint,
            details=details,
        )
        self.records = (*self.records, record)[-self.max_entries :]
        return record

    def rows(self) -> tuple[dict[str, str], ...]:
        """Return display-safe rows for the Digital Twin page."""
        return tuple(
            {
                "Time": record.created_at.isoformat(),
                "Decision": record.title,
                "Kind": record.kind.value.replace("_", " "),
                "Subject": record.subject_id,
                "Page": record.page,
                "Source": record.source_fingerprint[:12] or "not recorded",
                "Result": record.result_fingerprint[:12] or "not recorded",
            }
            for record in reversed(self.records)
        )

    def to_json(self) -> str:
        """Return canonical JSON for caching and in-memory export."""
        return json.dumps(
            [json.loads(item.model_dump_json()) for item in self.records],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @classmethod
    def from_json(
        cls,
        payload: str,
        *,
        max_entries: int = MAX_COPILOT_DECISIONS,
    ) -> DecisionLog:
        """Rebuild a bounded log from its canonical JSON payload."""
        log = cls(max_entries=max_entries)
        if not payload:
            return log
        items: Any = json.loads(payload)
        if not isinstance(items, list):
            raise TypeError("Decision payload must be a list.")
        parsed = tuple(DecisionRecord.model_validate(item) for item in items)
        log.records = parsed[-log.max_entries :]
        return log


__all__ = ["DecisionKind", "DecisionLog", "DecisionRecord"]
