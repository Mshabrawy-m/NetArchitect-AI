"""Sample-project validity and explicit-confirmation coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services.validation import build_design_health
from simulation import twin_fingerprint
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.sample_projects import (
    PENDING_KEY,
    SAMPLE_PROJECTS,
    build_sample,
    sample_by_key,
)

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def test_three_labeled_samples_are_deterministic_and_valid() -> None:
    assert [sample.key for sample in SAMPLE_PROJECTS] == [
        "small-office",
        "campus",
        "spine-leaf-dc",
    ]
    for sample in SAMPLE_PROJECTS:
        assert sample.name.startswith("SAMPLE - ")
        twin = build_sample(sample.key)
        assert twin.topology.name == sample.name
        assert sample.summary == (
            f"{len(twin.topology.devices)} devices | "
            f"{len(twin.topology.links)} links | "
            f"{len(twin.demands)} demands"
        )
        assert build_design_health(twin).is_valid
        assert twin_fingerprint_stable(sample.key)


def twin_fingerprint_stable(key: str) -> bool:
    return twin_fingerprint(build_sample(key)) == twin_fingerprint(build_sample(key))


def test_loading_without_confirmation_is_rejected() -> None:
    at = AppTest.from_string("""
from ui.sample_projects import load_sample
try:
    load_sample("small-office", confirmed=False)
except ValueError as error:
    from ui import state
    state.session_set("__sample_error", str(error))
""").run()
    assert not at.exception
    assert "explicit confirmation" in at.session_state["__sample_error"]


def _dashboard_with_existing_twin() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = build_sample("campus")
    at.run()
    open_page(at, "Dashboard")
    assert not at.exception
    return at


def test_selecting_a_sample_does_not_replace_the_current_twin() -> None:
    at = _dashboard_with_existing_twin()
    existing = at.session_state[state.TWIN_KEY]

    at.button(key="sample_select_small-office").click().run()

    assert not at.exception
    assert at.session_state[state.TWIN_KEY] is existing
    assert at.session_state[PENDING_KEY] == "small-office"


def test_cancelling_a_sample_leaves_the_current_twin_untouched() -> None:
    at = _dashboard_with_existing_twin()
    existing = at.session_state[state.TWIN_KEY]
    at.button(key="sample_select_small-office").click().run()

    at.button(key="sample_cancel").click().run()

    assert not at.exception
    assert at.session_state[state.TWIN_KEY] is existing
    assert PENDING_KEY not in at.session_state


def test_confirming_a_sample_replaces_the_twin_with_a_new_one() -> None:
    at = _dashboard_with_existing_twin()
    existing = at.session_state[state.TWIN_KEY]
    at.button(key="sample_select_small-office").click().run()

    at.button(key="sample_confirm_load").click().run()

    assert not at.exception
    loaded = at.session_state[state.TWIN_KEY]
    assert loaded is not existing
    assert loaded.metadata.name == sample_by_key("small-office").name
    assert PENDING_KEY not in at.session_state


def test_unknown_sample_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown sample project"):
        build_sample("missing")
