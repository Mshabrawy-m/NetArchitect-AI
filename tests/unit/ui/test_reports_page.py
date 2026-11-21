"""AppTest coverage for the Phase 11c Reports & Documentation page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from agents import run_structured_design
from capacity import CapacityHistory, DemandMapping, evaluate_capacity
from core.schemas.scenario import ScenarioType
from simulation import ScenarioHistory, run_failure_sweep, run_scenario
from tests.unit.agents.helpers import sample_requirements
from tests.unit.capacity.helpers import constant_run, line_capacity_twin
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.simulation.helpers import line_twin, make_demand, make_scenario
from tests.unit.ui.nav_helpers import open_page
from ui import state
from ui.pages import ai_designer

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"

DOWNLOAD_KEYS = (
    "reports_download_pdf",
    "reports_download_markdown",
    "reports_download_json",
    "reports_download_csv",
    "reports_download_templates",
)


def _reports_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    assert not at.exception
    open_page(at, "Reports & Documentation")
    assert not at.exception
    return at


def _find_frame(at: AppTest, column: str):
    for frame in at.get("dataframe"):
        if column in getattr(frame.value, "columns", []):
            return frame.value
    return None


def test_without_a_twin_the_page_explains_the_required_input() -> None:
    at = _reports_page()

    assert any("No digital twin" in info.value for info in at.info)
    assert any("Topology Editor" in info.value for info in at.info)
    assert not at.get("download_button")


def test_populated_page_previews_sections_and_offers_every_export() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = make_twin()
    at.run()
    open_page(at, "Reports & Documentation")

    assert not at.exception
    assert at.multiselect(key="reports_sections")
    for key in DOWNLOAD_KEYS:
        assert at.download_button(key=key)

    assert any(
        success.value.startswith("Consistent:")
        for success in at.success
    )
    headings = [markdown.value for markdown in at.markdown]
    assert any("Architecture summary" in value for value in headings)
    assert any("Routing and reachability" in value for value in headings)

    unavailable = _find_frame(at, "Producing page")
    assert unavailable is not None
    pages = set(unavailable["Producing page"])
    assert {"Simulation Lab", "Optimization Center", "AI Network Designer"} <= pages

    ip_plan = _find_frame(at, "Subnet")
    assert ip_plan is not None
    assert "Network" in ip_plan.columns


def test_report_timestamp_is_stable_for_one_twin_and_resets_for_a_new_one() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = make_twin()
    at.run()
    open_page(at, "Reports & Documentation")

    def prepared_line() -> str:
        return next(
            caption.value
            for caption in at.caption
            if "Prepared at" in caption.value
        )

    first = prepared_line()
    at.run()
    assert prepared_line() == first

    changed = make_twin()
    changed = changed.model_copy(
        update={"metadata": changed.metadata.model_copy(update={"name": "New twin"})}
    )
    at.session_state[state.TWIN_KEY] = changed
    at.run()
    assert prepared_line() != first


def test_section_selection_limits_the_preview_and_downloads() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = make_twin()
    at.run()
    open_page(at, "Reports & Documentation")

    at.multiselect(key="reports_sections").set_value(["routing"]).run()

    assert not at.exception
    headings = [markdown.value for markdown in at.markdown]
    assert any("1. Routing and reachability" in value for value in headings)
    assert not any("Architecture summary" in value for value in headings)
    for key in DOWNLOAD_KEYS:
        assert at.download_button(key=key)


def test_without_a_section_selection_the_page_asks_for_one() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = make_twin()
    at.run()
    open_page(at, "Reports & Documentation")

    at.multiselect(key="reports_sections").set_value([]).run()

    assert not at.exception
    assert any(
        "Select at least one section" in warning.value
        for warning in at.warning
    )
    assert not at.get("download_button")


def test_a_retained_workflow_fills_the_agent_trace_section() -> None:
    workflow = run_structured_design(sample_requirements())
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = make_twin()
    at.session_state[ai_designer.PLAN_STATE_KEY] = workflow
    at.run()
    open_page(at, "Reports & Documentation")

    assert not at.exception
    unavailable = _find_frame(at, "Producing page")
    assert unavailable is not None
    assert "AI Network Designer" not in set(unavailable["Producing page"])
    selector = at.multiselect(key="reports_sections")
    assert "Agent execution trace (available)" in selector.options
    assert "agent_trace" in selector.value
    headings = [markdown.value for markdown in at.markdown]
    assert any("Agent execution trace" in value for value in headings)


def test_a_retained_scenario_run_fills_the_simulation_section() -> None:
    twin = line_twin(demands=(make_demand("a-to-c", "a", "c", 80.0),))
    run = run_scenario(
        twin,
        make_scenario(ScenarioType.single_link_failure, affected_links=["ab"]),
    )
    history = ScenarioHistory()
    history.add(run)

    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.SIMULATION_HISTORY_KEY] = history
    at.run()
    open_page(at, "Reports & Documentation")

    assert not at.exception
    selector = at.multiselect(key="reports_sections")
    assert "Simulation before and after (available)" in selector.options
    assert "simulation" in selector.value
    unavailable = _find_frame(at, "Producing page")
    assert unavailable is not None
    assert "Simulation before and after" not in set(unavailable["Section"])
    headings = [markdown.value for markdown in at.markdown]
    assert any("Simulation before and after" in value for value in headings)


def test_a_retained_capacity_run_fills_the_capacity_section() -> None:
    twin = line_capacity_twin()
    forecast = constant_run(30.0)
    mapping = DemandMapping(series_to_demand={"s1": "call"}, per_user_mbps=1.0)
    run = evaluate_capacity(twin, forecast, mapping)
    history = CapacityHistory()
    history.add(run)

    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.CAPACITY_HISTORY_KEY] = history
    at.run()
    open_page(at, "Reports & Documentation")

    assert not at.exception
    selector = at.multiselect(key="reports_sections")
    assert "Capacity planning (available)" in selector.options
    assert "capacity" in selector.value
    assert at.selectbox(key="reports_capacity_source")

    unavailable = _find_frame(at, "Producing page")
    assert unavailable is not None
    assert "Capacity Planning" not in set(unavailable["Producing page"])
    headings = [markdown.value for markdown in at.markdown]
    assert any("Capacity planning" in value for value in headings)
    assert any(success.value.startswith("Consistent:") for success in at.success)


def test_e5_source_selectors_are_available() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = make_twin()
    at.run()
    open_page(at, "Reports & Documentation")

    assert not at.exception
    for key in (
        "reports_sweep_source",
        "reports_mode_compare_source",
        "reports_sensitivity_source",
        "reports_rerank_source",
    ):
        selectbox = at.selectbox(key=key)
        assert selectbox
        assert "None" in selectbox.options


def test_a_retained_failure_sweep_fills_the_failure_sweep_section() -> None:
    twin = make_twin()
    sweep = run_failure_sweep(twin, limit=1)
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.SIMULATION_SWEEPS_KEY] = (sweep,)
    at.run()
    open_page(at, "Reports & Documentation")

    assert not at.exception
    selector = at.multiselect(key="reports_sections")
    assert "Failure sweep (available)" in selector.options
    assert "failure_sweep" in selector.value
    unavailable = _find_frame(at, "Producing page")
    assert unavailable is not None
    assert "Failure sweep" not in set(unavailable["Section"])
    headings = [markdown.value for markdown in at.markdown]
    assert any("Failure sweep" in value for value in headings)
    assert any(success.value.startswith("Consistent:") for success in at.success)
