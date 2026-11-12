"""Deterministic network-engineering services.

This package is intentionally free of Streamlit, LLM, and agent dependencies.
Every module here is a pure, testable engineering service that operates on the
typed domain models from :mod:`core.schemas`.

``network.topology`` holds the topology engine: graph conversion, immutable
editing operations, connectivity analysis, JSON serialization, and topology
generators.
"""
