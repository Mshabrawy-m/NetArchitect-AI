"""Navigation coverage for every page in the sidebar."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import PAGES
from tests.unit.digital_twin.helpers import make_twin
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"

_PLACEHOLDER_WORDS = ("coming soon", "later phase", "will be implemented")


def _visible_text(at: AppTest) -> str:
    groups = (
        at.title,
        at.header,
        at.subheader,
        at.caption,
        at.info,
        at.warning,
        at.error,
        at.success,
    )
    return " ".join(
        element.value
        for group in groups
        for element in group
    ).lower()


@pytest.mark.parametrize("page", PAGES)
def test_every_nav_page_loads_without_a_twin(page: str) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    assert not at.exception

    at.selectbox(key="page_nav").select(page).run()

    assert not at.exception
    assert at.title[0].value == page
    assert not any(word in _visible_text(at) for word in _PLACEHOLDER_WORDS)


@pytest.mark.parametrize("page", PAGES)
def test_every_nav_page_loads_with_a_twin(page: str) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at.session_state[state.TWIN_KEY] = make_twin()
    at.selectbox(key="page_nav").select(page).run()

    assert not at.exception
    assert at.title[0].value == page
    assert not any(word in _visible_text(at) for word in _PLACEHOLDER_WORDS)
