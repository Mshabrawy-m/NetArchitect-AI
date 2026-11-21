"""Single bridge to the security agent's existing prose audit vocabulary."""

from __future__ import annotations

from agents.security_agent import (
    FORBIDDEN_EXPLANATION_TERMS as FORBIDDEN_TERMS,
)
from agents.security_agent import (
    numeric_tokens,
)

__all__ = ["FORBIDDEN_TERMS", "numeric_tokens"]
