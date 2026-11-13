"""Provider-independent LLM interface.

The rest of the application depends on :class:`LLMProvider`, never on a
concrete vendor SDK. Implementations must return typed responses, raise the
typed errors in :mod:`core.exceptions`, and never expose credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from .models import LLMMessage, LLMResponse

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMProvider(ABC):
    """Interface every LLM provider implementation must satisfy."""

    name: str = "provider"
    model: str = ""

    @abstractmethod
    def complete(
        self,
        messages: Sequence[LLMMessage],
        schema: type[BaseModel] | None = None,
        *,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Return one assistant response.

        When ``schema`` is supplied, the implementation must validate the
        response against it (with a bounded repair loop) and populate
        :attr:`LLMResponse.structured`; invalid output must raise a typed
        error rather than return partial data.
        """


__all__ = ["LLMProvider"]
