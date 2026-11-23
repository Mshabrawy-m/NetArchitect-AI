"""AppTest smoke tests for the Phase 7c Simulation Lab page."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from config.settings import get_settings
from services.llm.testing import FakeProvider
from simulation import (
    MODEL_NOTE,
    FailureSweepDepth,
    FailureSweepStopReason,
    RoutingMode,
    compare_routing_modes,
    run_failure_sweep,
)
from tests.unit.simulation.helpers import diamond_twin, make_demand
from tests.unit.ui.nav_helpers import open_page
from ui import i18n, state
from ui.components import copilot as copilot_component
from ui.components import editors
from ui.pages import simulation_lab

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


@pytest.fixture
def configured_key(monkeypatch, request):
    """Set the sole supported key source and clear the cached settings."""

    def _set(secret: str) -> None:
        monkeypatch.setenv("GROQ_API_KEY", secret)
        get_settings.cache_clear()

    request.addfinalizer(get_settings.cache_clear)
    return _set


def _twin_with_demand():
    return diamond_twin(demands=(make_demand("a-to-d", "a", "d"),))


def test_simulation_lab_requires_a_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    open_page(at, "Simulation Lab")

    assert not at.exception
    assert any("No digital twin is loaded" in info.value for info in at.info)
    assert any("Topology Editor" in info.value for info in at.info)


def test_simulation_lab_rejects_invalid_scenario() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    at.button(key="simulation_validate_scenario").click().run()

    assert not at.exception
    assert any(
        "requires exactly one affected link" in error.value for error in at.error
    )
    assert not at.session_state[state.SIMULATION_HISTORY_KEY].runs


def test_simulation_lab_demand_editor_writes_to_twin() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = diamond_twin()
    open_page(at, "Simulation Lab")

    at.session_state["simulation_demand_editor"] = {
        "edited_rows": {},
        "added_rows": [
            {
                "name": "new-flow",
                "source": "a",
                "destination": "d",
                "bandwidth_mbps": 25.0,
                "priority": 1,
            }
        ],
        "deleted_rows": [],
    }
    at.button(key="simulation_apply_demands").click().run()

    assert not at.exception
    assert not at.error
    twin = at.session_state[state.TWIN_KEY]
    assert len(twin.demands) == 1
    assert twin.demands[0].name == "new-flow"
    assert twin.demands[0].bandwidth_mbps == 25.0


def test_rejected_demand_edit_resets_the_editor_widget() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    at.session_state["simulation_demand_editor"] = {
        "edited_rows": {0: {"source": "ghost"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.button(key="simulation_apply_demands").click().run()

    assert not at.exception
    assert any("Demand changes rejected" in error.value for error in at.error)
    assert at.session_state["editor_key_versions"]["simulation_demand_editor"] == 1
    fresh = at.session_state.get("simulation_demand_editor_v1")
    assert not fresh or not fresh.get("edited_rows")
    twin = at.session_state[state.TWIN_KEY]
    assert twin.demands[0].source == "a"


def test_simulation_lab_runs_and_compares_scenarios() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    assert any(MODEL_NOTE in info.value for info in at.info)
    assert at.button(key="simulation_apply_demands")
    assert at.button(key="simulation_run_scenario")

    # Form widgets are committed on submit; setting their session keys is the
    # AppTest equivalent of a user filling the form before clicking Run.
    at.session_state["simulation_scenario_type"] = "Multiple link failures"
    at.session_state["simulation_scenario_name"] = "Lose both branches"
    at.session_state["simulation_affected_links"] = ["ab", "bd", "ac", "cd"]
    at.button(key="simulation_run_scenario").click().run()

    assert not at.exception
    history = at.session_state[state.SIMULATION_HISTORY_KEY]
    assert len(history.runs) == 1
    run = history.runs[0]
    assert run.scenario.name == "Lose both branches"
    assert run.comparison.newly_unserved_demands == ("a-to-d",)
    assert any("Newly unserved" in warning.value for warning in at.warning)

    at.session_state["simulation_scenario_name"] = "Lose the other branch"
    at.session_state["simulation_affected_links"] = ["ac", "cd"]
    at.button(key="simulation_run_scenario").click().run()

    assert not at.exception
    history = at.session_state[state.SIMULATION_HISTORY_KEY]
    assert len(history.runs) == 2
    assert at.selectbox(key="simulation_compare_left")
    assert at.selectbox(key="simulation_compare_right")
    assert at.download_button(key="simulation_download_json")
    assert at.download_button(key="simulation_download_comparison")


def test_copilot_interprets_without_key_and_only_fills_the_form() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    assert not at.exception
    assert at.text_input(key="simulation_copilot_sentence")
    at.text_input(key="simulation_copilot_sentence").set_value("fail link ab")
    at.button(key="simulation_copilot_interpret").click().run()

    assert not at.exception
    assert at.text_area(key="simulation_copilot_preview")
    assert len(at.session_state[state.SIMULATION_HISTORY_KEY].runs) == 0

    at.button(key="simulation_copilot_apply").click().run()
    assert not at.exception
    assert at.session_state["simulation_scenario_type"] == "Single link failure"
    assert at.session_state["simulation_affected_links"] == ["ab"]
    assert len(at.session_state[state.SIMULATION_HISTORY_KEY].runs) == 0


def test_copilot_with_key_uses_audited_ai_draft(monkeypatch, configured_key) -> None:
    reply = json.dumps(
        {
            "intent": "fail_link",
            "entity_ids": ["ab"],
            "numeric_literals": [],
            "demand_names": [],
            "question": "",
            "reason": "",
        }
    )
    monkeypatch.setattr(
        simulation_lab,
        "_copilot_provider",
        lambda: FakeProvider([reply]),
    )
    configured_key("environment-test-key")
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    at.text_input(key="simulation_copilot_sentence").set_value(
        "please take the ab link down"
    )
    at.button(key="simulation_copilot_interpret").click().run()

    assert not at.exception
    assert at.text_area(key="simulation_copilot_preview")
    assert any("AI draft" in caption.value for caption in at.caption)
    assert len(at.session_state[state.SIMULATION_HISTORY_KEY].runs) == 0
    rendered = "\n".join(
        [caption.value for caption in at.caption]
        + [element.value for element in at.markdown]
    )
    assert "environment-test-key" not in rendered


def _run_scenario_in_app(at: AppTest) -> None:
    at.session_state["simulation_scenario_type"] = "Multiple link failures"
    at.session_state["simulation_scenario_name"] = "Lose both branches"
    at.session_state["simulation_affected_links"] = ["ab", "bd", "ac", "cd"]
    at.button(key="simulation_run_scenario").click().run()


def test_c3_explanations_work_without_a_key() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")
    _run_scenario_in_app(at)

    assert not at.exception
    assert at.button(key="copilot_why_simulation")
    assert at.button(key="copilot_why_route")
    at.button(key="copilot_why_simulation").click().run()
    at.button(key="copilot_why_route").click().run()

    assert not at.exception
    results = at.session_state[copilot_component.EXPLANATION_STATE_KEY]
    assert {key: value.target.value for key, value in results.items()} == {
        "copilot_why_simulation": "simulation",
        "copilot_why_route": "route",
    }
    assert all(not value.has_ai for value in results.values())
    captions = [caption.value for caption in at.caption]
    assert "Deterministic explanation" in captions
    assert not any("AI-generated" in caption for caption in captions)


def test_c3_explanations_use_audited_ai_with_a_key(
    monkeypatch,
    configured_key,
) -> None:
    replies = [
        json.dumps({"text": "The modeled path follows the cheaper branch."}),
        json.dumps({"text": "The demand can still use the alternate branch."}),
    ]
    pending = iter(replies)
    monkeypatch.setattr(
        copilot_component,
        "_provider",
        lambda: FakeProvider([next(pending)]),
    )
    configured_key("environment-test-key")
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")
    _run_scenario_in_app(at)

    at.button(key="copilot_why_simulation").click().run()
    at.button(key="copilot_why_route").click().run()

    assert not at.exception
    results = at.session_state[copilot_component.EXPLANATION_STATE_KEY]
    assert all(value.has_ai for value in results.values())
    rendered = "\n".join(
        [caption.value for caption in at.caption]
        + [element.value for element in at.markdown]
    )
    assert "AI-generated" in rendered
    assert "environment-test-key" not in rendered


def test_simulation_lab_renders_e5_controls() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    assert not at.exception
    assert at.selectbox(key="simulation_routing_mode")
    assert at.data_editor(key=editors.editor_key("simulation_shared_risk_editor"))
    assert at.button(key="simulation_apply_shared_risk_groups")
    assert at.button(key="simulation_clear_shared_risk_groups")
    assert at.button(key="simulation_mode_compare_run")
    assert at.radio(key="simulation_sweep_depth")
    assert at.button(key="simulation_sweep_run")
    assert at.button(key="simulation_sweep_cancel_button")


def test_routing_mode_selector_changes_parsed_assumptions() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = _twin_with_demand()
    open_page(at, "Simulation Lab")

    assert not at.exception
    selector = at.selectbox(key="simulation_routing_mode")
    assert i18n.t("simulation.routing_mode.single_path") in selector.options
    assert i18n.t("simulation.routing_mode.ecmp") in selector.options

    single = simulation_lab._parse_assumptions(
        70.0, 90.0, 100.0, "{}", RoutingMode.single_path
    )
    ecmp = simulation_lab._parse_assumptions(
        70.0, 90.0, 100.0, "{}", RoutingMode.ecmp
    )
    assert single.routing_mode is RoutingMode.single_path
    assert ecmp.routing_mode is RoutingMode.ecmp


def test_simulation_lab_renders_injected_sweep_and_mode_comparison() -> None:
    twin = _twin_with_demand()
    sweep = run_failure_sweep(twin, limit=1)
    comparison = compare_routing_modes(
        twin, modes=(RoutingMode.single_path, RoutingMode.ecmp)
    )
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    at.session_state[state.TWIN_KEY] = twin
    at.session_state[state.SIMULATION_SWEEPS_KEY] = (sweep,)
    at.session_state[state.SIMULATION_MODE_COMPARISONS_KEY] = (comparison,)
    open_page(at, "Simulation Lab")

    assert not at.exception
    headings = [subheader.value for subheader in at.subheader]
    assert any("Failure sweep" in value for value in headings)
    assert any("Routing mode comparison" in value for value in headings)
    assert at.download_button(key="simulation_download_sweep_json")
    assert at.download_button(key="simulation_download_sweep_csv")
    assert at.download_button(key="simulation_download_mode_compare")


def _sweep_page(twin, **session_values: object):
    at = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
    at.session_state[state.TWIN_KEY] = twin
    for key, value in session_values.items():
        at.session_state[key] = value
    open_page(at, "Simulation Lab")
    return at


def _stored_sweeps(at):
    return at.session_state[state.SIMULATION_SWEEPS_KEY]


def test_failure_sweep_run_from_zero_shows_a_result_table() -> None:
    at = _sweep_page(_twin_with_demand())

    at.button(key="simulation_sweep_run").click().run()

    assert not at.exception
    sweeps = _stored_sweeps(at)
    assert len(sweeps) == 1
    # Hand: the diamond fixture has four links and four devices, so N-1 plans
    # eight modeled failure cases.
    assert sweeps[-1].total_cases == 8
    assert sweeps[-1].evaluated_cases == 8
    assert sweeps[-1].stop_reason is FailureSweepStopReason.completed
    assert any(not frame.value.empty for frame in at.dataframe)
    assert at.session_state[state.SIMULATION_SWEEP_CURSOR_KEY]["simulation_sweep"] == 0


def test_failure_sweep_cancel_before_first_slice_is_safe() -> None:
    at = _sweep_page(
        _twin_with_demand(),
        **{
            "simulation_sweep_running": True,
            simulation_lab.SWEEP_CANCEL_KEY: True,
            state.SIMULATION_SWEEP_CURSOR_KEY: {"simulation_sweep": 0},
            "simulation_sweep_pieces": [],
        },
    )

    assert not at.exception
    sweeps = _stored_sweeps(at)
    assert len(sweeps) == 1
    assert sweeps[-1].evaluated_cases == 0
    assert sweeps[-1].stop_reason is FailureSweepStopReason.cancelled
    assert at.session_state["simulation_sweep_running"] is False


def test_failure_sweep_can_run_twice_after_completion() -> None:
    at = _sweep_page(_twin_with_demand())

    at.button(key="simulation_sweep_run").click().run()
    assert not at.exception
    assert len(_stored_sweeps(at)) == 1

    at.button(key="simulation_sweep_run").click().run()

    assert not at.exception
    sweeps = _stored_sweeps(at)
    assert len(sweeps) == 2
    assert all(
        sweep.stop_reason is FailureSweepStopReason.completed for sweep in sweeps
    )
    assert at.session_state[state.SIMULATION_SWEEP_CURSOR_KEY]["simulation_sweep"] == 0


def test_failure_sweep_with_zero_cases_reports_no_failures() -> None:
    at = _sweep_page(
        _twin_with_demand(),
        simulation_sweep_depth=simulation_lab.SWEEP_DEPTH_LABELS[FailureSweepDepth.n2],
    )

    at.button(key="simulation_sweep_run").click().run()

    assert not at.exception
    sweeps = _stored_sweeps(at)
    assert len(sweeps) == 1
    assert sweeps[-1].total_cases == 0
    assert sweeps[-1].evaluated_cases == 0
    assert sweeps[-1].stop_reason is FailureSweepStopReason.no_failures
    assert any("No failure case was evaluated" in info.value for info in at.info)


def test_failure_sweep_twin_change_resets_the_cursor() -> None:
    at = _sweep_page(
        _twin_with_demand(),
        **{
            "simulation_sweep_running": True,
            simulation_lab.SWEEP_TWIN_FINGERPRINT_KEY: "stale-twin-fingerprint",
            state.SIMULATION_SWEEP_CURSOR_KEY: {"simulation_sweep": 3},
            "simulation_sweep_pieces": [],
        },
    )

    assert not at.exception
    assert at.session_state[state.SIMULATION_SWEEP_CURSOR_KEY]["simulation_sweep"] == 0
    assert at.session_state["simulation_sweep_pieces"] == []
    assert at.session_state["simulation_sweep_running"] is False
    assert any("twin changed" in warning.value for warning in at.warning)


def _piece(case_count: int, reason: FailureSweepStopReason):
    return SimpleNamespace(cases=(None,) * case_count, stop_reason=reason)


def test_sweep_bootstrap_and_terminal_reason_are_total_for_empty_states() -> None:
    reasons = tuple(FailureSweepStopReason)
    piece_states = (
        (),
        (_piece(0, FailureSweepStopReason.cancelled),),
        (_piece(1, FailureSweepStopReason.completed),),
        (
            _piece(1, FailureSweepStopReason.case_limit),
            _piece(1, FailureSweepStopReason.runtime_limit),
        ),
    )
    for total, cursor, pieces, cancelled in itertools.product(
        range(3), range(4), piece_states, (False, True)
    ):
        bootstrap = simulation_lab._sweep_bootstrap(
            total=total,
            cursor=cursor,
            pieces=pieces,
            cancelled=cancelled,
        )
        assert 0 <= bootstrap.cursor <= total
        if not pieces:
            # Hand: with no pieces the cursor is the start of the next slice,
            # never a skipped position from a stale session value.
            assert bootstrap.cursor == 0
            assert bootstrap.stop_reason == (
                FailureSweepStopReason.cancelled if cancelled else None
            )
            expected_seed = (
                FailureSweepStopReason.no_failures
                if total == 0
                else FailureSweepStopReason.cancelled
                if cancelled
                else None
            )
            assert bootstrap.seed_reason is expected_seed
        else:
            assert bootstrap.cursor == min(
                sum(len(piece.cases) for piece in pieces), total
            )
            assert bootstrap.seed_reason is None
            assert bootstrap.stop_reason == (
                FailureSweepStopReason.cancelled if cancelled else pieces[-1].stop_reason
            )

        final = simulation_lab._sweep_terminal_reason(
            cursor=bootstrap.cursor,
            total=total,
            cancelled=cancelled,
            stop_reason=bootstrap.stop_reason,
        )
        assert final in reasons
        if cancelled:
            assert final is FailureSweepStopReason.cancelled

