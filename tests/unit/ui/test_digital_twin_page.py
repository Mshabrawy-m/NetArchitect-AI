"""AppTest smoke tests for the Phase 6 Digital Twin page."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from digital_twin import (
    DeviceState,
    DigitalTwin,
    OperationalState,
    TwinMetadata,
    apply_failure,
)
from network.topology import generate_ring
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.ui.nav_helpers import open_page
from ui import state

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def test_digital_twin_page_requires_a_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    open_page(at, "Digital Twin")

    assert not at.exception
    assert any("No digital twin is loaded" in info.value for info in at.info)


def test_digital_twin_page_shows_categorized_design_health() -> None:
    twin = make_twin(
        device_states=(
            DeviceState(device_id="ghost", state=OperationalState.down),
        )
    )
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = twin
    open_page(at, "Digital Twin")

    assert not at.exception
    subheaders = [element.value for element in at.get("subheader")]
    assert "Design health" in subheaders
    assert any("design-health finding" in error.value for error in at.error)
    metrics = {element.label: element.value for element in at.get("metric")}
    assert metrics["Error"] == "1"


def test_digital_twin_page_summarizes_state_and_creates_snapshot() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    open_page(at, "Topology Editor")
    at.button(key="generate_topology").click().run()

    open_page(at, "Digital Twin")
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
    open_page(at, "Routing Analysis")

    assert not at.exception
    assert any("currently models 1 failed device" in info.value for info in at.info)
