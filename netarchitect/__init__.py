"""Deterministic, standard-library command-line interface for NetArchitect AI.

Importing this package never loads the Streamlit web application. The public
surface is intentionally small: :func:`main` for the ``python -m netarchitect``
entry point and :data:`__version__` for callers that need the application
version.
"""

from __future__ import annotations

from config.settings import Settings

from .cli import main

__version__: str = Settings().APP_VERSION

__all__ = ["__version__", "main"]
