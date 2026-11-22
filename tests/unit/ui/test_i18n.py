"""Ar/en catalog, fallback, RTL, and Settings language-switch coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.unit.ui.nav_helpers import open_page
from ui import i18n

APP_PATH = Path(__file__).resolve().parents[3] / "app.py"
FSI, PDI = "\u2068", "\u2069"


def _plain(text: str) -> str:
    """Remove Unicode direction isolates for readable value assertions."""
    return text.replace(FSI, "").replace(PDI, "")


def test_catalogs_have_full_arabic_key_and_placeholder_parity() -> None:
    assert i18n.catalog_parity()
    assert i18n.missing_translation_keys() == ()
    assert set(i18n.AR) == set(i18n.EN)


E5_KEYS = (
    "loading.sweep",
    "loading.mode_compare",
    "loading.sensitivity",
    "simulation.routing_mode",
    "simulation.routing_mode.help",
    "simulation.routing_mode.single_path",
    "simulation.routing_mode.ecmp",
    "simulation.routing_mode.capacity_aware",
    "simulation.shared_risk.title",
    "simulation.shared_risk.caption",
    "simulation.shared_risk.id",
    "simulation.shared_risk.name",
    "simulation.shared_risk.devices",
    "simulation.shared_risk.links",
    "simulation.shared_risk.add",
    "simulation.shared_risk.apply",
    "simulation.shared_risk.clear",
    "simulation.mode_compare.title",
    "simulation.mode_compare.caption",
    "simulation.mode_compare.run",
    "simulation.mode_compare.download",
    "simulation.sweep.title",
    "simulation.sweep.caption",
    "simulation.sweep.depth",
    "simulation.sweep.depth.n1",
    "simulation.sweep.depth.n2",
    "simulation.sweep.subset_links",
    "simulation.sweep.subset_devices",
    "simulation.sweep.max_pairs",
    "simulation.sweep.slice",
    "simulation.sweep.run",
    "simulation.sweep.cancel",
    "simulation.sweep.progress",
    "simulation.sweep.showing",
    "simulation.sweep.download_json",
    "simulation.sweep.download_csv",
    "simulation.sweep.stop_reason",
    "simulation.sweep.no_result",
    "simulation.sweep.srgs",
    "optimization.algorithm.simulated_annealing",
    "optimization.sa.hybrid_start",
    "optimization.sa.hybrid_start.help",
    "optimization.sensitivity.title",
    "optimization.sensitivity.caption",
    "optimization.sensitivity.run",
    "optimization.sensitivity.download",
    "optimization.sensitivity.robust",
    "optimization.sensitivity.no_robust",
    "optimization.sensitivity.complete",
    "optimization.sensitivity.incomplete",
    "optimization.rerank.title",
    "optimization.rerank.caption",
    "optimization.rerank.apply",
    "optimization.rerank.download",
    "optimization.rerank.no_front",
    "optimization.rerank.weights_note",
    "reports.failure_sweep_source",
    "reports.mode_compare_source",
    "reports.sensitivity_source",
    "reports.rerank_source",
)


def test_e5_catalog_keys_are_present_and_parity_is_preserved() -> None:
    for key in E5_KEYS:
        assert key in i18n.EN
        assert key in i18n.AR
    assert i18n.catalog_parity()
    assert i18n.missing_translation_keys() == ()
    assert set(i18n.EN) == set(i18n.AR)


S6_KEYS = (
    "security.page.title",
    "security.page.intro",
    "security.scope",
    "security.empty.message",
    "security.empty.title",
    "security.empty.hint",
    "security.tab.zones",
    "security.tab.policy",
    "security.tab.flow",
    "security.tab.reachability",
    "security.tab.segmentation",
    "security.tab.optimizer",
    "security.tab.zero_trust",
    "security.tab.findings",
    "security.tab.checklist",
    "security.tab.templates",
    "security.reachability.title",
    "security.reachability.caption",
    "security.reachability.blast_radius",
    "security.reachability.why",
    "security.segmentation.title",
    "security.segmentation.caption",
    "security.segmentation.why",
    "security.optimizer.title",
    "security.optimizer.caption",
    "security.optimizer.select",
    "security.optimizer.apply",
    "security.optimizer.empty",
    "security.optimizer.applied",
    "security.zero_trust.title",
    "security.zero_trust.caption",
    "security.zero_trust.select",
    "security.zero_trust.apply",
    "security.zero_trust.empty",
    "security.zero_trust.applied",
    "security.checklist.title",
    "security.checklist.caption",
    "security.checklist.version",
    "security.checklist.health",
    "status.pass",
    "status.fail",
    "status.not-modeled",
    "status.exposed",
)


def test_s6_catalog_keys_are_present_and_parity_is_preserved() -> None:
    for key in S6_KEYS:
        assert key in i18n.EN
        assert key in i18n.AR
    assert i18n.catalog_parity()
    assert i18n.missing_translation_keys() == ()
    assert set(i18n.EN) == set(i18n.AR)


L5_KEYS = (
    "nav.label.l3_design",
    "nav.help.l3_design",
    "page.l3_design",
    "page.l3_design.description",
    "l3.scope",
    "l3.tab.ipv6",
    "l3.tab.nat",
    "l3.tab.ospf",
    "l3.tab.ha",
    "l3.tab.findings",
    "ip.tab.dual_stack",
    "ip.tab.nat",
)


def test_l5_catalog_keys_are_present_and_parity_is_preserved() -> None:
    for key in L5_KEYS:
        assert key in i18n.EN
        assert key in i18n.AR
    assert i18n.catalog_parity()
    assert i18n.missing_translation_keys() == ()
    assert set(i18n.EN) == set(i18n.AR)


W5_KEYS = (
    "nav.label.l2_design",
    "nav.help.l2_design",
    "page.l2_design",
    "page.l2_design.description",
    "l2.scope",
    "l2.model_notes",
    "l2.tab.l2",
    "l2.tab.wan",
    "l2.tab.wireless",
    "l2.tab.qos",
    "l2.tab.findings",
    "l2.tab.l2.description",
    "l2.tab.wan.description",
    "l2.tab.wireless.description",
    "l2.tab.qos.description",
    "l2.tab.findings.description",
    "l2.l2.title",
    "l2.wan.title",
    "l2.wireless.title",
    "l2.qos.title",
    "l2.findings.title",
    "l2.l2.scope",
    "l2.wan.scope",
    "l2.wireless.scope",
    "l2.qos.scope",
    "l2.editor.gateways",
    "l2.editor.root_priorities",
    "l2.editor.vlan_spread_threshold",
    "l2.editor.bundles",
    "l2.editor.site_types",
    "l2.editor.hq_sites",
    "l2.editor.areas",
    "l2.editor.default_class",
    "l2.editor.class_caps",
    "l2.l2.editor",
    "l2.wan.editor",
    "l2.wireless.editor",
    "l2.qos.editor",
    "l2.button.apply_design",
    "l2.button.clear_design",
    "l2.button.add_bundle",
    "l2.button.add_area",
    "l2.button.add_cap",
    "l2.button.remove_selected",
    "l2.l2.apply",
    "l2.wan.apply",
    "l2.wireless.apply",
    "l2.qos.apply",
    "l2.l2.clear",
    "l2.wan.clear",
    "l2.wireless.clear",
    "l2.qos.clear",
    "l2.notice.no_twin",
    "l2.notice.no_design",
    "l2.notice.design_saved",
    "l2.notice.design_cleared",
    "l2.notice.no_findings",
    "l2.notice.model_only",
    "l2.notice.no_live_protocol",
    "l2.notice.no_rf",
    "l2.notice.no_queue",
    "l2.why.l2",
    "l2.why.wan",
    "l2.why.wireless",
    "l2.why.qos",
    "l2.why.findings",
    "l2.why.button",
    "l2.l2.why",
    "l2.wan.why",
    "l2.wireless.why",
    "l2.qos.why",
    "l2.field.vlan_id",
    "l2.field.gateway_device",
    "l2.field.switch_id",
    "l2.field.priority",
    "l2.field.link_ids",
    "l2.field.site_id",
    "l2.field.site_type",
    "l2.field.area_id",
    "l2.field.area_m2",
    "l2.field.clients",
    "l2.field.client_mbps",
    "l2.field.ap_capacity_mbps",
    "l2.field.coverage_radius_m",
    "l2.field.utilization_target",
    "l2.field.overlap_factor",
    "l2.field.link_id",
    "l2.field.traffic_class",
    "l2.field.share_cap",
    "l2.field.default_class",
    "l2.empty.no_bundles",
    "l2.empty.no_areas",
    "l2.empty.no_caps",
    "l2.empty.no_findings",
    "l2.review.run",
    "l2.review.cancel",
    "l2.review.clear",
    "l2.review.running",
    "l2.review.empty",
    "l2.review.done",
    "l2.section.layer2",
    "l2.section.wan",
    "l2.section.wireless",
    "l2.section.qos",
    "l2.section.findings",
)


def test_w5_catalog_keys_are_present_and_parity_is_preserved() -> None:
    for key in W5_KEYS:
        assert key in i18n.EN
        assert key in i18n.AR
    assert i18n.catalog_parity()
    assert i18n.missing_translation_keys() == ()
    assert set(i18n.EN) == set(i18n.AR)


def test_w5_arabic_values_are_translated_not_english_copies() -> None:
    for key in (
        "nav.label.l2_design",
        "nav.help.l2_design",
        "page.l2_design",
        "page.l2_design.description",
        "l2.scope",
        "l2.tab.l2",
        "l2.tab.wan",
        "l2.tab.wireless",
        "l2.tab.qos",
        "l2.tab.findings",
        "l2.notice.no_twin",
        "l2.why.l2",
        "l2.why.qos",
    ):
        assert _plain(i18n.translate(key, language="ar")) != i18n.EN[key]
        assert any("\u0600" <= char <= "\u06ff" for char in i18n.AR[key])


def test_translate_falls_back_to_english_for_a_missing_arabic_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "AR", dict(i18n.AR))
    monkeypatch.setattr(i18n, "EN", dict(i18n.EN))
    i18n.AR.pop("progress.title")
    i18n.EN["progress.title"] = "Project progress"

    assert _plain(i18n.translate("progress.title", language="ar")) == (
        "Project progress"
    )


def test_translate_falls_back_when_arabic_placeholders_are_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "AR", dict(i18n.AR))
    i18n.AR["progress.detail.design"] = "{missing} devices"

    value = i18n.translate(
        "progress.detail.design",
        {"devices": 3, "links": 4},
        language="ar",
    )
    assert "3" in value
    assert "devices" in value
    assert "links" in value


def test_unknown_key_is_deterministic() -> None:
    assert i18n.translate("not.in.catalog", language="en") == "not.in.catalog"
    assert _plain(i18n.translate("not.in.catalog", language="ar")) == (
        "not.in.catalog"
    )


def test_engineering_terms_numbers_and_cidrs_stay_ltr() -> None:
    protected = i18n.protect_latin_tokens(
        "استخدم OSPF و VLAN مع CIDR 10.0.0.0/8"
    )
    for token in ("OSPF", "VLAN", "CIDR", "10.0.0.0/8"):
        assert f"{FSI}{token}{PDI}" in protected
    assert i18n.protect_latin_tokens("بدون رموز لاتينية") == (
        "بدون رموز لاتينية"
    )

    monkeypatch_language = pytest.MonkeyPatch()
    monkeypatch_language.setattr(
        i18n, "current_language", lambda: "ar", raising=False
    )
    try:
        label = i18n.page_label("VLAN & DHCP Planner")
        assert f"{FSI}VLAN{PDI}" in label
        assert f"{FSI}DHCP{PDI}" in label
        assert i18n.direction() == "rtl"
        assert i18n.ltr("10.0.0.0/8") == f"{FSI}10.0.0.0/8{PDI}"
        assert i18n.ltr(None) == ""
    finally:
        monkeypatch_language.undo()


def test_language_values_normalize_to_supported_codes() -> None:
    assert i18n.normalize_language("AR") == "ar"
    assert i18n.normalize_language("العربية") == "ar"
    assert i18n.normalize_language("en-US") == "en"
    assert i18n.normalize_language(None) == "en"
    assert i18n.normalize_language("unknown") == "en"


def test_arabic_session_renders_rtl_css_and_localized_dashboard() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.session_state[i18n.LANGUAGE_KEY] = "ar"
    at.run()

    assert not at.exception
    assert any("direction: rtl" in html.value for html in at.html)
    assert any(".i18n-ltr" in html.value for html in at.html)

    open_page(at, "Dashboard")
    assert not at.exception
    assert at.title[0].value == "لوحة التحكم"
    assert "البدء السريع" in [header.value for header in at.subheader]
    assert any(
        "نموذج - مكتب صغير" in text.value for text in at.markdown
    )
    assert any("تقدم المشروع" in caption.value for caption in at.caption)
    assert any(
        "التصميم" in link.label for link in at.get("page_link")
    )
    assert any(f"{FSI}VLAN{PDI}" in caption.value for caption in at.caption)
    assert at.session_state[i18n.LANGUAGE_KEY] == "ar"


def test_settings_language_toggle_switches_session_only() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    open_page(at, "Settings")

    assert not at.exception
    control = at.segmented_control[0]
    assert control.key == i18n.LANGUAGE_KEY
    assert control.label == "Language"
    assert control.value == "en"
    assert not at.html

    control.set_value("ar").run()
    assert not at.exception
    assert at.title[0].value == "الإعدادات"
    assert at.segmented_control[0].label == "اللغة"
    assert at.session_state[i18n.LANGUAGE_KEY] == "ar"
    assert any("direction: rtl" in html.value for html in at.html)

    at.segmented_control[0].set_value("en").run()
    assert not at.exception
    assert at.title[0].value == "Settings"
    assert at.session_state[i18n.LANGUAGE_KEY] == "en"
    assert not at.html
