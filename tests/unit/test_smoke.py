"""Smoke test for the Phase 1 project skeleton.

One cohesive test verifies that the configuration layer loads, resource
limits are defined, and all third-party dependencies are importable.
"""

import config.limits
from config.settings import get_settings


def test_smoke_imports_and_settings() -> None:
    """Settings load and all core dependencies import successfully."""
    settings = get_settings()
    assert settings.APP_NAME == "NetArchitect AI"

    assert config.limits.MAX_NODES > 0
    assert config.limits.MAX_OPTIMIZATION_ITERATIONS > 0

    # Third-party dependencies must be importable.
    import networkx  # noqa: F401
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    import plotly  # noqa: F401
    import pydantic  # noqa: F401
    import reportlab  # noqa: F401
    import scipy  # noqa: F401
    import streamlit  # noqa: F401
