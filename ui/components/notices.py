"""One-shot notices that survive a forced rerun.

When an editor submission is rejected the page advances the editor version and
reruns so the rejected rows disappear. A direct ``st.error`` would be discarded
by that rerun, so the message is queued and rendered on the next run.
"""

from __future__ import annotations

from collections.abc import Iterator

import streamlit as st

from ui import state

NOTICES_KEY = "ui_notices"
LEVELS = frozenset({"info", "success", "warning", "error"})


def queue_notice(level: str, message: str, *, title: str = "") -> None:
    """Queue one notice for the next rerun."""
    if level not in LEVELS:
        raise ValueError(f"Unsupported notice level: {level!r}")
    notices = list(_notices())
    notices.append((level, message, title))
    state.session_set(NOTICES_KEY, notices)


def _notices() -> Iterator[tuple[str, str, str]]:
    value = state.session_get(NOTICES_KEY, [])
    if not isinstance(value, list):
        return iter(())
    return iter(
        item
        for item in value
        if isinstance(item, tuple) and len(item) == 3
    )


def render_notices() -> None:
    """Render and clear every queued notice."""
    for level, message, title in state.session_pop(NOTICES_KEY, []):
        if title:
            getattr(st, level)(message, title=title)
        else:
            getattr(st, level)(message)


__all__ = ["LEVELS", "NOTICES_KEY", "queue_notice", "render_notices"]
