"""AppTest coverage for the L2 Design page and its bounded review loop."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from network.l2.models import L2Design
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.wan.models import SiteType, WanDesign
from network.wireless.models import WirelessArea, WirelessDesign
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.ui.nav_helpers import open_page
from ui import i18n, state
from ui.cache import L2_REVIEW_SECTIONS, L2DesignReview, l2_review_key
from ui.components.copilot import EXPLANATION_STATE_KEY
from ui.components.editors import editor_key
from ui.pages import l2_design as page

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"


def _page(twin=None, **session_values: object) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    if twin is not None:
        at.session_state[state.TWIN_KEY] = twin
    for key, value in session_values.items():
        at.session_state[key] = value
    at.run()
    open_page(at, "L2 Design")
    return at


def _twin_with_all_models():
    return make_twin(
        l2_design=L2Design(
            gateway_by_vlan={10: "sw1"},
            root_priorities={"sw1": 4096},
        ),
        wan_design=WanDesign(
            site_types={"hq": SiteType.hq, "br1": SiteType.branch},
            hq_site_ids=("hq",),
        ),
        wireless_design=WirelessDesign(
            areas=(WirelessArea(id="area-1", area_m2=400.0, clients=100),),
        ),
        qos_design=QosDesign(
            default_class=TrafficClass.best_effort,
            class_share_caps=(
                ClassShareCap(
                    link_id="l1",
                    traffic_class=TrafficClass.voice,
                    share_cap=0.2,
                ),
            ),
        ),
    )


def _review_table(at: AppTest):
    expected = ["Section", "Findings", "Summary"]
    for frame in at.dataframe:
        if list(frame.value.columns) == expected:
            return frame.value
    raise AssertionError("The bounded review summary table was not rendered.")


def _status_messages(at: AppTest) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(message.value for message in messages)
        for messages in (at.info, at.success, at.warning, at.error)
    )


def test_l2_design_requires_a_twin() -> None:
    at = _page()

    assert not at.exception
    assert at.title[0].value == "L2 Design"
    assert any(page.MODEL_NOTE in info.value for info in at.info)
    assert any(
        "No digital twin with a topology is loaded" in info.value for info in at.info
    )
    assert not at.tabs


def test_l2_design_shows_five_tabs_and_every_editor_and_button() -> None:
    at = _page(make_twin())

    assert not at.exception
    assert [tab.label for tab in at.tabs] == [
        i18n.t("l2.tab.l2"),
        i18n.t("l2.tab.wan"),
        i18n.t("l2.tab.wireless"),
        i18n.t("l2.tab.qos"),
        i18n.t("l2.tab.findings"),
    ]
    for editor_base in (
        page.L2_EDITOR_BASE,
        page.WAN_EDITOR_BASE,
        page.WIRELESS_EDITOR_BASE,
        page.QOS_EDITOR_BASE,
    ):
        assert at.data_editor(key=editor_key(editor_base))
    for key in (
        page.L2_APPLY_KEY,
        page.L2_CLEAR_KEY,
        page.WAN_APPLY_KEY,
        page.WAN_CLEAR_KEY,
        page.WIRELESS_APPLY_KEY,
        page.WIRELESS_CLEAR_KEY,
        page.QOS_APPLY_KEY,
        page.QOS_CLEAR_KEY,
        page.REVIEW_RUN_KEY,
        page.REVIEW_CANCEL_BUTTON_KEY,
        page.REVIEW_CLEAR_KEY,
    ):
        assert at.button(key=key)


def test_l2_editors_apply_and_clear_four_bounded_models() -> None:
    at = _page(make_twin())

    at.button(key=page.L2_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.l2_design is not None
    assert twin.l2_design.etherchannel_bundles[0].link_ids == ("l1", "l2")

    at.button(key=page.WAN_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.wan_design is not None
    assert twin.wan_design.site_types["hq"] is SiteType.hq

    at.button(key=page.WIRELESS_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.wireless_design is not None
    assert twin.wireless_design.areas[0].id == "area-1"

    at.button(key=page.QOS_APPLY_KEY).click().run()
    assert not at.exception
    twin = at.session_state[state.TWIN_KEY]
    assert twin.qos_design is not None
    assert twin.qos_design.class_share_caps[0].link_id == "l1"
    assert any(
        "QoS admission design saved" in success.value for success in at.success
    )

    for key, field in (
        (page.QOS_CLEAR_KEY, "qos_design"),
        (page.WIRELESS_CLEAR_KEY, "wireless_design"),
        (page.WAN_CLEAR_KEY, "wan_design"),
        (page.L2_CLEAR_KEY, "l2_design"),
    ):
        at.button(key=key).click().run()
        assert not at.exception
        assert getattr(at.session_state[state.TWIN_KEY], field) is None


def test_l2_design_offers_all_four_copilot_why_buttons() -> None:
    at = _page(_twin_with_all_models())

    assert not at.exception
    for key in (
        page.L2_WHY_KEY,
        page.WAN_WHY_KEY,
        page.WIRELESS_WHY_KEY,
        page.QOS_WHY_KEY,
    ):
        assert at.button(key=key)

    for key in (
        page.L2_WHY_KEY,
        page.WAN_WHY_KEY,
        page.WIRELESS_WHY_KEY,
        page.QOS_WHY_KEY,
    ):
        at.button(key=key).click().run()
        assert not at.exception

    results = at.session_state[EXPLANATION_STATE_KEY]
    assert {key: value.target.value for key, value in results.items()} == {
        page.L2_WHY_KEY: "l2_design",
        page.WAN_WHY_KEY: "wan_design",
        page.WIRELESS_WHY_KEY: "wireless_design",
        page.QOS_WHY_KEY: "qos_design",
    }
    assert all(not value.has_ai for value in results.values())


def test_l2_review_run_from_zero_shows_a_result_table() -> None:
    twin = make_twin()
    at = _page(twin)

    at.button(key=page.REVIEW_RUN_KEY).click().run()

    assert not at.exception
    result = at.session_state[page.REVIEW_RESULT_KEY]
    assert isinstance(result, L2DesignReview)
    assert result.twin_version == l2_review_key(twin)
    assert result.sections == L2_REVIEW_SECTIONS
    assert result.status == page.REVIEW_DONE
    assert at.session_state[page.REVIEW_COMPLETIONS_KEY] == 1
    assert at.session_state[page.REVIEW_RUNNING_KEY] is False
    assert at.session_state[page.REVIEW_CURSOR_KEY] == 0
    assert at.session_state[page.REVIEW_PIECES_KEY] == ()
    assert list(_review_table(at)["Section"]) == [
        "Layer-2 switching",
        "WAN and multi-site",
        "Abstract wireless",
        "QoS admission",
    ]
    assert any(
        i18n.t("l2.review.done") in success.value for success in at.success
    )


def test_l2_review_cancel_before_first_slice_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twin = make_twin()
    real_fragment = page._run_review_fragment

    # Hold the synchronous fragment at zero pieces so the enabled Cancel
    # control can be clicked before any section is evaluated. The real fragment
    # is restored for the rerun triggered by that click.
    monkeypatch.setattr(page, "_run_review_fragment", lambda _twin: None)
    at = _page(
        twin,
        **{
            page.REVIEW_RUNNING_KEY: True,
            page.REVIEW_CANCEL_KEY: False,
            page.REVIEW_CURSOR_KEY: 0,
            page.REVIEW_PIECES_KEY: (),
            page.REVIEW_KEY_KEY: l2_review_key(twin),
        },
    )
    monkeypatch.setattr(page, "_run_review_fragment", real_fragment)

    at.button(key=page.REVIEW_CANCEL_BUTTON_KEY).click().run()

    assert not at.exception
    result = at.session_state[page.REVIEW_RESULT_KEY]
    assert isinstance(result, L2DesignReview)
    assert result.status == page.REVIEW_CANCELLED
    assert result.l2_loops == ()
    assert result.wan_links == ()
    assert result.wireless_areas == ()
    assert result.qos_caps == ()
    assert at.session_state[page.REVIEW_RUNNING_KEY] is False
    assert at.session_state[page.REVIEW_CURSOR_KEY] == 0
    assert at.session_state[page.REVIEW_PIECES_KEY] == ()
    assert at.session_state[page.REVIEW_COMPLETIONS_KEY] == 1


def test_l2_review_can_run_twice_after_completion() -> None:
    at = _page(make_twin())

    at.button(key=page.REVIEW_RUN_KEY).click().run()
    assert not at.exception
    assert at.session_state[page.REVIEW_COMPLETIONS_KEY] == 1

    at.button(key=page.REVIEW_RUN_KEY).click().run()

    assert not at.exception
    assert at.session_state[page.REVIEW_COMPLETIONS_KEY] == 2
    result = at.session_state[page.REVIEW_RESULT_KEY]
    assert isinstance(result, L2DesignReview)
    assert result.status == page.REVIEW_DONE
    assert at.session_state[page.REVIEW_CURSOR_KEY] == 0
    assert at.session_state[page.REVIEW_PIECES_KEY] == ()


def test_l2_review_twin_change_mid_run_resets_the_cursor() -> None:
    twin = make_twin()
    at = _page(
        twin,
        **{
            page.REVIEW_RUNNING_KEY: True,
            page.REVIEW_KEY_KEY: "stale-review-key",
            page.REVIEW_CURSOR_KEY: 3,
            page.REVIEW_PIECES_KEY: (),
        },
    )

    assert not at.exception
    assert at.session_state.get(page.REVIEW_RESULT_KEY) is None
    assert at.session_state[page.REVIEW_KEY_KEY] == l2_review_key(twin)
    assert at.session_state[page.REVIEW_CURSOR_KEY] == 0
    assert at.session_state[page.REVIEW_PIECES_KEY] == ()
    assert at.session_state[page.REVIEW_RUNNING_KEY] is False
    assert at.session_state.get(page.REVIEW_COMPLETIONS_KEY, 0) == 0
    assert any("twin changed" in warning.value for warning in at.warning)


def test_l2_review_clear_removes_every_stored_key() -> None:
    at = _page(make_twin())
    at.button(key=page.REVIEW_RUN_KEY).click().run()
    assert at.session_state[page.REVIEW_RESULT_KEY] is not None

    at.button(key=page.REVIEW_CLEAR_KEY).click().run()

    assert not at.exception
    for key in page.REVIEW_KEYS:
        assert key not in at.session_state
    assert any(i18n.t("l2.review.empty") in info.value for info in at.info)


def test_l2_review_table_and_notices_are_deterministic() -> None:
    at = _page(make_twin())

    at.button(key=page.REVIEW_RUN_KEY).click().run()
    assert not at.exception
    first_table = _review_table(at).to_dict("records")
    first_notices = _status_messages(at)

    at.button(key=page.REVIEW_RUN_KEY).click().run()

    assert not at.exception
    assert _review_table(at).to_dict("records") == first_table
    assert _status_messages(at) == first_notices
    assert any(
        "No class share caps are stored" in caption.value for caption in at.caption
    )


def test_l2_review_bootstrap_and_terminal_state_are_total_for_empty_inputs() -> None:
    statuses = (
        page.REVIEW_DONE,
        page.REVIEW_CANCELLED,
        page.REVIEW_EMPTY,
        page.REVIEW_INCOMPLETE,
    )
    piece_states = (
        (),
        (L2DesignReview(twin_version="x", status=page.REVIEW_CANCELLED),),
        (L2DesignReview(twin_version="x", status=page.REVIEW_EMPTY),),
    )
    for total, cursor, pieces, cancelled in itertools.product(
        range(3), range(4), piece_states, (False, True)
    ):
        bootstrap = page._review_bootstrap(
            total=total,
            cursor=cursor,
            pieces=pieces,
            cancelled=cancelled,
        )
        assert 0 <= bootstrap.cursor <= total
        expected_stop: str | None = None
        for piece in pieces:
            expected_stop = piece.status
        if not pieces:
            assert bootstrap.cursor == 0
            assert bootstrap.stop_reason == (
                page.REVIEW_CANCELLED if cancelled else None
            )
            expected_seed: str | None = (
                page.REVIEW_EMPTY
                if total == 0
                else page.REVIEW_CANCELLED
                if cancelled
                else page.REVIEW_DONE
                if cursor >= total
                else None
            )
            assert bootstrap.seed_reason == expected_seed
        else:
            assert bootstrap.stop_reason == (
                page.REVIEW_CANCELLED if cancelled else expected_stop
            )
            assert bootstrap.seed_reason is None
        assert bootstrap.seed_reason is None or bootstrap.seed_reason in statuses
        if bootstrap.stop_reason is not None:
            assert bootstrap.stop_reason in statuses
