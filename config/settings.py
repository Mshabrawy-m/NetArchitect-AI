"""Application settings for NetArchitect AI.

Settings are loaded from environment variables and, when available,
Streamlit secrets. A Pydantic ``BaseModel`` validates the values and
provides defaults so the application instantiates with no secrets and no
Streamlit context.

``pydantic-settings`` is intentionally NOT a dependency; overrides are
read manually from ``os.environ`` and ``st.secrets`` (the Streamlit access
is guarded so it never fails outside a Streamlit runtime).
"""

from __future__ import annotations

import functools
import os

from pydantic import BaseModel

# Setting keys that may be overridden by environment variables or secrets.
_SETTING_KEYS: tuple[str, ...] = (
    "APP_NAME",
    "APP_VERSION",
    "DEPLOYMENT_TARGET",
    "GROQ_API_KEY",
)


class Settings(BaseModel):
    """Application configuration values.

    All fields have defaults, so a ``Settings`` instance can be created
    with no environment variables and no Streamlit secrets present.
    """

    APP_NAME: str = "NetArchitect AI"
    APP_VERSION: str = "0.1.0"
    DEPLOYMENT_TARGET: str = "Streamlit Community Cloud Free"
    # Optional. Core deterministic features work without any API key.
    GROQ_API_KEY: str = ""


def _read_streamlit_secrets() -> dict[str, str]:
    """Return overrides found in Streamlit secrets, if available.

    Streamlit may be absent or unavailable outside a Streamlit runtime, so
    the import and access are guarded. Any error returns an empty dict.
    """
    try:
        import streamlit as st
    except ImportError:
        return {}

    try:
        secrets = st.secrets
        overrides: dict[str, str] = {}
        for key in _SETTING_KEYS:
            if key in secrets:
                overrides[key] = secrets[key]
        return overrides
    except Exception:  # noqa: BLE001 - broad guard so settings never fail to load
        return {}


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache the application :class:`Settings`.

    Precedence: Streamlit secrets override environment variables, which
    override the model defaults. Instantiates successfully with no secrets
    and no Streamlit context.
    """
    overrides: dict[str, str] = {}

    for key in _SETTING_KEYS:
        value = os.environ.get(key)
        if value is not None:
            overrides[key] = value

    # Streamlit secrets take precedence over environment variables.
    overrides.update(_read_streamlit_secrets())

    return Settings(**overrides)
