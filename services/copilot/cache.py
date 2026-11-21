"""Bounded session cache for optional copilot language responses.

The key includes the model, prompt id and version, schema name, and a hash of
the typed input. A cache hit avoids the provider entirely, so it cannot consume
LLM budget. No credential is ever part of a key or a stored value.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from config.limits import MAX_COPILOT_CACHE_ENTRIES


def input_hash(payload: object) -> str:
    """Return a stable SHA-256 digest of one typed payload."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    """Non-secret identity of one cached copilot response."""

    model: str
    prompt_id: str
    prompt_version: str
    schema_name: str
    input_digest: str

    def value(self) -> str:
        """Return the canonical cache key string."""
        payload = {
            "model": self.model,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "schema_name": self.schema_name,
            "input_digest": self.input_digest,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, str]:
        """Return a non-secret, display-safe description."""
        return {
            "model": self.model,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "schema_name": self.schema_name,
            "input_digest": self.input_digest[:12],
        }


class CopilotCache:
    """A bounded, insertion-ordered cache of validated Pydantic responses."""

    def __init__(self, *, max_entries: int = MAX_COPILOT_CACHE_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._entries: OrderedDict[str, BaseModel] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: CacheKey, expected: type[BaseModel]) -> BaseModel | None:
        """Return one cached value when it matches the requested schema."""
        value = self._entries.get(key.value())
        if value is None or not isinstance(value, expected):
            self.misses += 1
            return None
        self.hits += 1
        self._entries.move_to_end(key.value())
        return value

    def put(self, key: CacheKey, value: BaseModel) -> BaseModel:
        """Store one validated value, evicting the oldest entry when full."""
        if not isinstance(value, BaseModel):
            raise TypeError("CopilotCache stores only Pydantic models")
        identifier = key.value()
        if identifier in self._entries:
            self._entries[identifier] = value
        else:
            self._entries[identifier] = value
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return value

    def snapshot(self) -> dict[str, int]:
        """Return bounded, non-secret cache counters."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self._entries),
            "max_entries": self.max_entries,
        }

    def clear(self) -> None:
        """Remove cached values and reset counters."""
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def describe(self) -> tuple[dict[str, str], ...]:
        """Return display-safe key metadata without any cached value."""
        keys = tuple(self._entries)
        values: list[dict[str, str]] = []
        for identifier in keys:
            # Keys are digests, so only their short prefix is retained here.
            values.append(
                {
                    "key": identifier[:12],
                    "model": self._entries[identifier].__class__.__name__,
                }
            )
        return tuple(values)


def build_key(
    *,
    model: str,
    prompt_id: str,
    prompt_version: str,
    schema_name: str,
    payload: dict[str, Any],
) -> CacheKey:
    """Build one cache key from explicit, non-secret parts."""
    return CacheKey(
        model=model,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        schema_name=schema_name,
        input_digest=input_hash(payload),
    )


__all__ = ["CacheKey", "CopilotCache", "build_key", "input_hash"]
