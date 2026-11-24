"""Optional LLM provider layer.

Pure Python: this package imports no Streamlit and no vendor SDK. It depends on
the standard library, Pydantic, and ``config.settings``/``config.limits`` only.
Core deterministic engineering never imports this package.
"""

from .budget import RequestBudget
from .groq import (
    USER_AGENT,
    GroqProvider,
    HTTPResult,
    default_transport,
    provider_status,
)
from .models import (
    LLMMessage,
    LLMResponse,
    LLMUsage,
    MessageRole,
    ProviderLimits,
    ProviderStatus,
)
from .prompts import (
    EXPLAIN_RESULT,
    INTERPRET_SCENARIO,
    PROMPTS,
    PromptSpec,
    get_prompt,
)
from .provider import LLMProvider
from .structured import extract_json, validate_structured

__all__ = [
    "EXPLAIN_RESULT",
    "INTERPRET_SCENARIO",
    "PROMPTS",
    "USER_AGENT",
    "GroqProvider",
    "HTTPResult",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "MessageRole",
    "PromptSpec",
    "ProviderLimits",
    "ProviderStatus",
    "RequestBudget",
    "default_transport",
    "extract_json",
    "get_prompt",
    "provider_status",
    "validate_structured",
]
