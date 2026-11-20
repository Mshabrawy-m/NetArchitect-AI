"""AppTest helper for the grouped ``st.navigation`` structure."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from ui.navigation import PAGE_FILES


def open_page(at: AppTest, page: str) -> AppTest:
    """Switch an AppTest session to a declared page by its canonical title."""
    if page not in PAGE_FILES:
        raise AssertionError(f"Unknown page: {page!r}")
    at.switch_page(PAGE_FILES[page]).run()
    return at
