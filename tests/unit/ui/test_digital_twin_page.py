"""AppTest smoke tests for the Phase 6 Digital Twin page."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from digital_twin import DigitalTwin, TwinMetadata, apply_failure
from network.topology import generate_ring
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def test_digital_twin_page_requires_a_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    at.selectbox(key="page_nav").select("Digital Twin").run()

    assert not at.exception
    assert any("No digital twin is loaded" in info.value for info in at.info)


def test_digital_twin_page_summarizes_state_and_creates_snapshot() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.selectbox(key="page_nav").select("Topology Editor").run()
    at.button(key="generate_topology").click().run()

    at.selectbox(key="page_nav").select("Digital Twin").run()
    assert not at.exception
    assert at.get("dataframe")
    assert any("single source of truth" in caption.value for caption in at.caption)

    at.text_input(key="twin_snapshot_label").set_value("baseline").run()
    at.button(key="twin_create_snapshot").click().run()
    assert not at.exception

    store = at.session_state[state.SNAPSHOTS_KEY]
    assert [snapshot.label for snapshot in store.snapshots] == ["baseline"]
    assert store.snapshots[0].twin == at.session_state[state.TWIN_KEY]

    # With one snapshot, the comparison defaults to snapshot vs current twin.
    assert any("identical" in success.value for success in at.success)


def test_routing_page_applies_twin_operational_failures() -> None:
    twin = DigitalTwin(
        metadata=TwinMetadata(
            name="Ring",
            created_at=datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
        ),
        topology=generate_ring(node_count=4),
    )
    twin = apply_failure(twin, device_ids=["ring-node-00"])

    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = twin
    at.selectbox(key="page_nav").select("Routing Analysis").run()

    assert not at.exception
    assert any("currently models 1 failed device" in info.value for info in at.info)
