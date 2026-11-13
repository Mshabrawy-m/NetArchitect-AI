"""Scripted LLM provider test double.

This module is a test aid, not a user-facing demo mode. It returns exactly the
scripted replies it is given (text, malformed output, or a typed exception) and
never contacts a network or reads an API key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from core.exceptions import LLMProviderError
from services.llm.budget import RequestBudget
from services.llm.models import LLMMessage, LLMResponse, LLMUsage
from services.llm.provider import LLMProvider
from services.llm.structured import validate_structured


@dataclass
class FakeCall:
    """One recorded call made to :class:`FakeProvider`."""

    messages: tuple[LLMMessage, ...]
    schema: str | None


@dataclass
class FakeProvider(LLMProvider):
    """A deterministic test double with a bounded script."""

    replies: Sequence[str | Exception]
    model: str = "fake-model"
    budget: RequestBudget | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    name: str = "fake"
    calls: list[FakeCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._script = list(self.replies)

    def complete(
        self,
        messages: Sequence[LLMMessage],
        schema: type[BaseModel] | None = None,
        *,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Return the next scripted reply."""
        normalized = tuple(
            message
            if isinstance(message, LLMMessage)
            else LLMMessage.model_validate(message)
            for message in messages
        )
        self.calls.append(
            FakeCall(
                messages=normalized,
                schema=None if schema is None else schema.__name__,
            )
        )
        if self.budget is not None:
            self.budget.begin_call()
        if not self._script:
            raise LLMProviderError("The scripted FakeProvider has no replies left.")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        structured = None
        if schema is not None:
            structured = validate_structured(item, schema).model_dump(mode="json")
        if self.budget is not None:
            self.budget.record(self.usage)
        return LLMResponse(
            text=item,
            model=self.model,
            usage=self.usage,
            structured=structured,
        )


__all__ = ["FakeCall", "FakeProvider"]
