"""Shared loading indicator for bounded, synchronous UI actions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st

from ui import i18n


@contextmanager
def working(message: str) -> Iterator[None]:
    """Show one loading message while a bounded action runs.

    The action stays on the script thread: no worker, thread, timer, or disk
    write is introduced. Callers keep their own typed error handling.
    """
    with st.spinner(i18n.tx(message)):
        yield


__all__ = ["working"]
