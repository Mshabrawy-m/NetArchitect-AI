"""Versioned widget keys for rejected ``st.data_editor`` submissions.

Streamlit keeps edit deltas in the widget's session state keyed by its widget
key. If a submitted table is rejected by an engine, the rejected delta stays in
that key and the table keeps showing rows that were never applied. Bumping the
version changes the widget key on the next run, so the table is rebuilt from the
current model instead of the rejected delta.

Version 0 keeps the plain base key. This preserves existing sessions and tests
that seed the base key directly.
"""

from __future__ import annotations

from ui import state

EDITOR_VERSIONS_KEY = "editor_key_versions"


def editor_key(base: str) -> str:
    """Return the current widget key for one logical editor."""
    versions = state.session_get(EDITOR_VERSIONS_KEY, {})
    version = versions.get(base, 0) if isinstance(versions, dict) else 0
    return base if not version else f"{base}_v{version}"


def bump_editor_key(base: str) -> int:
    """Discard the editor's rejected state by advancing its widget key version."""
    versions = state.session_get(EDITOR_VERSIONS_KEY, {})
    if not isinstance(versions, dict):
        versions = {}
    version = int(versions.get(base, 0)) + 1
    versions[base] = version
    state.session_set(EDITOR_VERSIONS_KEY, versions)
    return version


__all__ = ["EDITOR_VERSIONS_KEY", "bump_editor_key", "editor_key"]
