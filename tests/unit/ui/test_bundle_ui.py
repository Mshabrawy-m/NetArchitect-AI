"""AppTest coverage for the B2 in-memory project bundle UI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from digital_twin import DigitalTwin, TwinMetadata
from services.bundle import CURRENT_BUNDLE_VERSION, BundleData, build_bundle
from simulation import twin_fingerprint
from tests.unit.digital_twin.helpers import CREATED_AT, make_twin
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.pages import digital_twin as page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _bundle_payload(name: str = "Imported twin") -> tuple[bytes, DigitalTwin]:
    twin = make_twin(metadata=TwinMetadata(name=name, created_at=CREATED_AT))
    data = BundleData(
        twin=twin,
        created_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        source_app_version="test",
        bundle_version=CURRENT_BUNDLE_VERSION,
    )
    return build_bundle(data), twin


def _open_digital_twin(at: AppTest) -> AppTest:
    open_page(at, "Digital Twin")
    return at


def _count(elements: object, key: str) -> int:
    """Count rendered elements by user key (AppTest raises for a missing key)."""
    return sum(1 for element in elements if getattr(element, "key", None) == key)


def _upload(at: AppTest, payload: bytes, *, name: str = "project.zip") -> AppTest:
    at.file_uploader(key=page.BUNDLE_UPLOAD_KEY).set_value(
        (name, payload, "application/zip")
    )
    return at.run()


def test_bundle_controls_render_from_empty_state() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at = _open_digital_twin(at)

    assert not at.exception
    assert at.file_uploader(key=page.BUNDLE_UPLOAD_KEY)
    assert _count(at.button, page.BUNDLE_PREPARE_KEY) == 0
    assert _count(at.download_button, page.BUNDLE_DOWNLOAD_KEY) == 0
    assert _count(at.button, page.BUNDLE_CONFIRM_KEY) == 0
    assert state.TWIN_KEY not in at.session_state


def test_save_prepare_download_then_dashboard_prompt_and_run_twice() -> None:
    twin = make_twin()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin
    at.run()
    at = _open_digital_twin(at)

    assert not at.exception
    at.button(key=page.BUNDLE_PREPARE_KEY).click().run()
    assert not at.exception
    assert at.download_button(key=page.BUNDLE_DOWNLOAD_KEY)
    assert state.BUNDLE_SAVED_FINGERPRINT_KEY in at.session_state

    open_page(at, "Dashboard")
    assert not at.exception
    assert not any(
        "unsaved changes" in warning.value for warning in at.warning
    ), "A freshly prepared bundle must not show the unsaved prompt."

    open_page(at, "Digital Twin")
    at.button(key=page.BUNDLE_PREPARE_KEY).click().run()
    assert not at.exception
    assert _count(at.download_button, page.BUNDLE_DOWNLOAD_KEY) == 1

    at.session_state[state.TWIN_KEY] = make_twin(
        metadata=TwinMetadata(name="Changed twin", created_at=CREATED_AT)
    )
    open_page(at, "Dashboard")
    assert any(
        "unsaved changes" in warning.value for warning in at.warning
    ), "Changing the twin after saving must raise the unsaved prompt."


def test_first_click_import_from_empty_state_replaces_twin() -> None:
    payload, imported = _bundle_payload()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at = _open_digital_twin(at)

    at = _upload(at, payload)
    assert not at.exception
    assert any(
        imported.metadata.name in markdown.value for markdown in at.markdown
    ), "A typed preview must be shown before confirmation."
    assert at.radio(key=page.BUNDLE_MODE_KEY).value == "replace"

    at.button(key=page.BUNDLE_CONFIRM_KEY).click().run()
    assert not at.exception
    restored = at.session_state[state.TWIN_KEY]
    assert isinstance(restored, DigitalTwin)
    assert restored.metadata.name == imported.metadata.name
    assert twin_fingerprint(restored) == twin_fingerprint(imported)
    assert state.BUNDLE_PREVIEW_KEY not in at.session_state
    assert _count(at.button, page.BUNDLE_CONFIRM_KEY) == 0


def test_import_as_new_snapshot_keeps_current_twin() -> None:
    payload, imported = _bundle_payload(name="Snapshot twin")
    current = make_twin()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = current
    at.run()
    at = _open_digital_twin(at)

    at = _upload(at, payload)
    at.radio(key=page.BUNDLE_MODE_KEY).set_value("snapshot").run()
    at.button(key=page.BUNDLE_CONFIRM_KEY).click().run()

    assert not at.exception
    assert twin_fingerprint(at.session_state[state.TWIN_KEY]) == twin_fingerprint(
        current
    )
    snapshots = at.session_state[state.SNAPSHOTS_KEY].snapshots
    assert len(snapshots) == 1
    assert snapshots[0].twin.metadata.name == imported.metadata.name


def test_cancel_and_rerun_do_not_restage_the_same_upload() -> None:
    payload, _ = _bundle_payload()
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at = _open_digital_twin(at)
    at = _upload(at, payload)

    assert any("Bundle preview" in markdown.value for markdown in at.markdown)
    at.button(key=page.BUNDLE_CANCEL_KEY).click().run()

    assert not at.exception
    assert state.TWIN_KEY not in at.session_state
    assert state.BUNDLE_PREVIEW_KEY not in at.session_state
    assert state.BUNDLE_STAGED_KEY not in at.session_state
    assert state.BUNDLE_INSPECTED_KEY not in at.session_state
    assert state.BUNDLE_PROCESSED_KEY in at.session_state

    at.run()
    assert not at.exception
    assert not any("Bundle preview" in markdown.value for markdown in at.markdown)
    assert _count(at.button, page.BUNDLE_CONFIRM_KEY) == 0


def test_hostile_and_empty_uploads_are_safe() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at = _open_digital_twin(at)

    at = _upload(at, b"not a zip file")
    assert not at.exception
    assert state.TWIN_KEY not in at.session_state
    assert state.BUNDLE_PREVIEW_KEY not in at.session_state
    assert any("could not be imported" in error.value for error in at.error)

    at.file_uploader(key=page.BUNDLE_UPLOAD_KEY).set_value(None)
    at.run()
    assert not at.exception
    assert not at.error
    assert state.TWIN_KEY not in at.session_state
