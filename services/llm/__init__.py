"""Optional LLM provider layer.

Pure Python: this package imports no Streamlit and no vendor SDK. It depends on
the standard library, Pydantic, and ``config.settings``/``config.limits`` only.
Core deterministic engineering never imports this package.
"""

from .budget import RequestBudget
from .groq import GroqProvider, HTTPResult, default_transport, provider_status
from .models import (
    LLMMessage,
    LLMResponse,
    LLMUsage,
    MessageRole,
    ProviderStatus,
)
from .provider import LLMProvider
from .structured import extract_json, validate_structured

__all__ = [
    "GroqProvider",
    "HTTPResult",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "MessageRole",
    "ProviderStatus",
    "RequestBudget",
    "default_transport",
    "extract_json",
    "provider_status",
    "validate_structured",
]
