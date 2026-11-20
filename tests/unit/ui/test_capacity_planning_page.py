"""AppTest coverage for the Phase 13c Capacity Planning page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from forecasting import SeriesUnit
from tests.unit.capacity.helpers import line_capacity_twin
from tests.unit.forecasting.helpers import make_series
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.pages import capacity_planning

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _capacity_page(twin=None, series=()) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    if twin is not None:
        at.session_state[state.TWIN_KEY] = twin
    if series:
        at.session_state[state.CAPACITY_SERIES_KEY] = tuple(series)
    at.run()
    open_page(at, "Capacity Planning")
    return at


def test_capacity_planning_requires_a_twin() -> None:
    at = _capacity_page()

    assert not at.exception
    assert at.title[0].value == "Capacity Planning"
    assert any(capacity_planning.MODEL_NOTE in info.value for info in at.info)
    assert any("No digital twin with a topology" in info.value for info in at.info)
    assert any("Topology Editor" in info.value for info in at.info)
    assert not at.tabs
    assert not at.download_button


def test_capacity_planning_shows_four_tabs_and_labels_generated_data() -> None:
    at = _capacity_page(line_capacity_twin())

    assert not at.exception
    assert [tab.label for tab in at.tabs] == [
        "Data",
        "Forecast",
        "Capacity",
        "Downloads",
    ]
    assert at.text_area(key=capacity_planning.CSV_KEY)
    assert at.button(key=capacity_planning.PARSE_KEY)
    assert at.button(key=capacity_planning.SYN_GENERATE_KEY)

    at.button(key=capacity_planning.PARSE_KEY).click().run()
    series = at.session_state[state.CAPACITY_SERIES_KEY]
    assert len(series) == 1
    assert series[0].label == "USER-SUPPLIED"
    assert any("Accepted 1 series" in success.value for success in at.success)

    at.button(key=capacity_planning.SYN_GENERATE_KEY).click().run()
    series = at.session_state[state.CAPACITY_SERIES_KEY]
    assert len(series) == 1
    assert series[0].label == "SYNTHETIC"
    assert any("SYNTHETIC series" in success.value for success in at.success)
    assert at.button(key=capacity_planning.FORECAST_KEY)


def test_capacity_planning_builds_forecast_and_evaluates_capacity() -> None:
    twin = line_capacity_twin()
    series = (
        make_series(
            [30.0] * 10,
            series_id="subscribers",
            unit=SeriesUnit.users,
        ),
    )
    at = _capacity_page(twin, series)

    at.button(key=capacity_planning.FORECAST_KEY).click().run()
    forecast = at.session_state[state.CAPACITY_FORECAST_KEY]
    assert not at.exception
    assert len(forecast.results) == 1
    assert at.session_state[state.CAPACITY_FORECAST_KEY] is forecast

    at.selectbox(key=f"{capacity_planning.MAPPING_KEY_PREFIX}0").select("call").run()
    at.number_input(key=capacity_planning.PER_USER_KEY).set_value(1.0).run()
    at.button(key=capacity_planning.EVALUATE_KEY).click().run()

    assert not at.exception
    history = at.session_state[state.CAPACITY_HISTORY_KEY]
    assert len(history.runs) == 1
    run = history.runs[0]
    assert run.projection.demands[0].name == "call"
    assert run.projection.demands[0].data_label == "USER-SUPPLIED"
    assert len(run.steps) == 2
    assert any(
        "Capacity analysis completed" in success.value for success in at.success
    )

    for key in (
        capacity_planning.SERIES_DOWNLOAD_KEY,
        capacity_planning.FORECAST_CSV_DOWNLOAD_KEY,
        capacity_planning.FORECAST_JSON_DOWNLOAD_KEY,
        capacity_planning.BOTTLENECK_DOWNLOAD_KEY,
        capacity_planning.UPGRADE_DOWNLOAD_KEY,
        capacity_planning.RUN_JSON_DOWNLOAD_KEY,
    ):
        assert at.download_button(key=key)
